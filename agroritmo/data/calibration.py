"""Comparação simulado × observado e calibração de parâmetros a partir de observações reais.

A calibração é unidimensional por métrica: um fator multiplicativo sobre o parâmetro que mais
determina a métrica é ajustado por busca de seção áurea (cada avaliação = uma simulação) para
minimizar |simulado − observado|. O resultado é salvo como uma NOVA operação com os parâmetros
marcados como ``calibrado`` — os parâmetros originais (padrão de exemplo ou informados) são preservados.

Uma operação só deve ser considerada representativa depois de calibrada e validada com
observações independentes das usadas na calibração.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from ..analytics.kpis import calcular_kpis, kpis_dict
from ..domain.models import OperationConfig, OrigemDado
from ..simulation import SimulationResult, simular


def _cargas(res: SimulationResult) -> pd.DataFrame:
    return res.cargas[res.cargas["status"] == "entregue"]


METRICAS_OBSERVAVEIS: dict[str, dict] = {
    "duracao_dias": {"rotulo": "Duração total da operação", "unidade": "dias",
                     "sim": lambda r, k: k["duracao_h"] / 24, "parametro": "eficiencia_campo"},
    "vazao_t_dia": {"rotulo": "Toneladas entregues por dia", "unidade": "t/dia",
                    "sim": lambda r, k: k["vazao_t_dia"], "parametro": "eficiencia_campo"},
    "ritmo_colheita_ha_h": {"rotulo": "Ritmo de colheita por máquina (horas colhendo)", "unidade": "ha/h",
                            "sim": lambda r, k: k["prod_colheita_ha_h"], "parametro": "eficiencia_campo"},
    "prod_colheita_t_h": {"rotulo": "Produção por hora colhendo, por máquina", "unidade": "t/h",
                          "sim": lambda r, k: k["prod_colheita_t_h"], "parametro": "eficiencia_campo"},
    "tempo_viagem_carregado_min": {"rotulo": "Tempo médio de viagem carregado (campo → unidade)", "unidade": "min",
                                   "sim": lambda r, k: float((_cargas(r)["t_chegada_unidade"] - _cargas(r)["t_saida_campo"]).mean()),
                                   "parametro": "velocidade_caminhao"},
    "tempo_descarga_min": {"rotulo": "Tempo médio de descarga na unidade", "unidade": "min",
                           "sim": lambda r, k: float((_cargas(r)["t_fim_descarga"] - _cargas(r)["t_inicio_descarga"]).mean()),
                           "parametro": "tempo_fixo_recebimento"},
    "espera_fila_min": {"rotulo": "Espera média na fila da unidade", "unidade": "min",
                        "sim": lambda r, k: k["fila_media_min"], "parametro": "capacidade_recebimento"},
    "cargas_dia": {"rotulo": "Cargas entregues por dia", "unidade": "cargas/dia",
                   "sim": lambda r, k: k["cargas"] / max(k["dias_operacao"], 1), "parametro": "eficiencia_campo"},
}

# parâmetro -> (rótulo, modificação, caminhos de proveniência, limites do fator)
PARAMETROS_CALIBRAVEIS = {
    "eficiencia_campo": ("Eficiência de campo das colheitadeiras", "eficiencia_campo", (0.4, 1.6)),
    "velocidade_caminhao": ("Velocidade dos caminhões", "velocidade_caminhao", (0.4, 2.0)),
    "tempo_fixo_recebimento": ("Tempo fixo de recebimento (pesagem/classificação)", "tempo_fixo_recebimento", (0.2, 4.0)),
    "capacidade_recebimento": ("Capacidade de recebimento", "capacidade_recebimento", (0.3, 3.0)),
}


def valores_simulados(res: SimulationResult, kpis: Optional[dict] = None) -> dict[str, float]:
    kpis = kpis or kpis_dict(calcular_kpis(res))
    out = {}
    for m, spec in METRICAS_OBSERVAVEIS.items():
        try:
            out[m] = float(spec["sim"](res, kpis))
        except Exception:  # noqa: BLE001
            out[m] = math.nan
    return out


def comparar_observado(res: SimulationResult, observacoes: pd.DataFrame, tolerancia_pct: float = 10.0) -> pd.DataFrame:
    """Tabela simulado × observado (média das observações por métrica)."""
    if observacoes is None or observacoes.empty:
        return pd.DataFrame(columns=["metrica", "rotulo", "unidade", "observado", "n_obs", "simulado", "erro", "erro_pct", "dentro_tolerancia"])
    sim = valores_simulados(res)
    linhas = []
    for metrica, grp in observacoes.groupby("metrica"):
        spec = METRICAS_OBSERVAVEIS.get(metrica)
        obs = float(grp["valor"].mean())
        s = sim.get(metrica, math.nan) if spec else math.nan
        erro = s - obs
        pct = erro / obs * 100 if obs else math.nan
        linhas.append({"metrica": metrica, "rotulo": spec["rotulo"] if spec else "(métrica não reconhecida)",
                       "unidade": spec["unidade"] if spec else "", "observado": obs, "n_obs": len(grp), "simulado": s,
                       "erro": erro, "erro_pct": pct, "dentro_tolerancia": abs(pct) <= tolerancia_pct if not math.isnan(pct) else False})
    return pd.DataFrame(linhas)


@dataclass
class ResultadoCalibracao:
    metrica: str
    parametro: str
    fator: float
    observado: float
    simulado_antes: float
    simulado_depois: float
    avaliacoes: pd.DataFrame
    config_calibrada: OperationConfig

    @property
    def erro_antes_pct(self) -> float:
        return (self.simulado_antes - self.observado) / self.observado * 100

    @property
    def erro_depois_pct(self) -> float:
        return (self.simulado_depois - self.observado) / self.observado * 100


def calibrar(cfg: OperationConfig, metrica: str, observado: float, parametro: Optional[str] = None, iteracoes: int = 14,
             progresso: Optional[Callable[[int, int, str], None]] = None) -> ResultadoCalibracao:
    from ..scenarios.modifications import Modificacao, aplicar

    spec = METRICAS_OBSERVAVEIS[metrica]
    parametro = parametro or spec["parametro"]
    rot, tipo_mod, (lo, hi) = PARAMETROS_CALIBRAVEIS[parametro]
    cache: dict[float, float] = {}
    linhas = []

    def avaliar(f: float) -> float:
        f = round(f, 6)
        if f not in cache:
            c = aplicar(cfg, [Modificacao(tipo=tipo_mod, valor=f)])
            r = simular(c)
            v = float(spec["sim"](r, kpis_dict(calcular_kpis(r))))
            cache[f] = v
            linhas.append({"fator": f, "simulado": v, "erro_abs": abs(v - observado)})
        return abs(cache[f] - observado)

    avaliar(1.0)
    antes = cache[1.0]
    gr = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c = b - gr * (b - a)
    d = a + gr * (b - a)
    for i in range(iteracoes):
        if progresso:
            progresso(i, iteracoes, f"Calibrando {rot}")
        if avaliar(c) < avaliar(d):
            b = d
        else:
            a = c
        c = b - gr * (b - a)
        d = a + gr * (b - a)
    candidatos = {f: abs(v - observado) for f, v in cache.items()}
    fator = min(candidatos, key=candidatos.get)
    calibrada = aplicar(cfg, [Modificacao(tipo=tipo_mod, valor=fator)])
    d_cfg = calibrada.model_dump()
    d_cfg["nome"] = f"{cfg.nome} (calibrada)"[:120]
    prov = dict(cfg.proveniencia)
    for caminho in caminhos_parametro(calibrada, parametro):
        prov[caminho] = OrigemDado.CALIBRADO.value
    d_cfg["proveniencia"] = prov
    d_cfg["descricao"] = (cfg.descricao + f"\nCalibrada: {rot} × {fator:.3f} para reproduzir {spec['rotulo']} = "
                          f"{observado:g} {spec['unidade']}.").strip()
    calibrada = OperationConfig.model_validate(d_cfg)
    return ResultadoCalibracao(metrica=metrica, parametro=parametro, fator=fator, observado=observado, simulado_antes=antes,
                               simulado_depois=cache[fator],
                               avaliacoes=pd.DataFrame(linhas).sort_values("fator").reset_index(drop=True),
                               config_calibrada=calibrada)


def caminhos_parametro(cfg: OperationConfig, parametro: str) -> list[str]:
    if parametro == "eficiencia_campo":
        return [f"colheitadeiras.{c.id}.eficiencia_campo" for c in cfg.colheitadeiras]
    if parametro == "velocidade_caminhao":
        return [f"frota.{g.id}.{v}" for g in cfg.frota for v in ("velocidade_carregado_km_h", "velocidade_vazio_km_h")]
    if parametro == "tempo_fixo_recebimento":
        return ["recebimento.tempo_fixo_min"]
    if parametro == "capacidade_recebimento":
        return ["recebimento.capacidade_t_h"]
    return []


def tabela_parametros(cfg: OperationConfig) -> pd.DataFrame:
    """Todos os parâmetros com sua origem (exemplo, usuário, importado, calibrado)."""
    linhas = []

    def add(caminho: str, rotulo: str, valor, unidade: str):
        linhas.append({"parametro": caminho, "descricao": rotulo, "valor": valor, "unidade": unidade,
                       "origem": cfg.origem_de(caminho).value})

    add("cultura", "Cultura", cfg.crop.nome, "—")
    add("cultura.kg_por_saca", "Massa da saca", cfg.kg_por_saca, "kg")
    for t in cfg.talhoes:
        p = f"talhoes.{t.id}"
        add(f"{p}.area_ha", f"Talhão {t.id} — área", t.area_ha, "ha")
        add(f"{p}.produtividade_sc_ha", f"Talhão {t.id} — produtividade", t.produtividade_sc_ha, "sc/ha")
        add(f"{p}.distancia_km", f"Talhão {t.id} — distância", t.distancia_km, "km")
        add(f"{p}.prioridade", f"Talhão {t.id} — prioridade", t.prioridade, "1–5")
    for c in cfg.colheitadeiras:
        p = f"colheitadeiras.{c.id}"
        for campo, rot, un in [("capacidade_campo_ha_h", "capacidade nominal", "ha/h"), ("eficiencia_campo", "eficiência de campo", "0–1"),
                               ("capacidade_tanque_t", "tanque", "t"), ("tempo_descarga_tanque_min", "descarga do tanque", "min"),
                               ("disponibilidade_mecanica", "disponibilidade", "0–1"), ("mttr_h", "MTTR", "h"),
                               ("parada_programada_min_dia", "manutenção diária", "min"), ("custo_fixo_h", "custo fixo", "R$/h"),
                               ("custo_variavel_h", "custo variável", "R$/h"), ("consumo_l_h", "consumo", "L/h")]:
            add(f"{p}.{campo}", f"{c.id} — {rot}", getattr(c, campo), un)
    for g in cfg.frota:
        p = f"frota.{g.id}"
        for campo, rot, un in [("quantidade", "quantidade", "un"), ("capacidade_t", "capacidade", "t"),
                               ("velocidade_carregado_km_h", "velocidade carregado", "km/h"),
                               ("velocidade_vazio_km_h", "velocidade vazio", "km/h"), ("tempo_manobra_min", "manobra", "min"),
                               ("disponibilidade_mecanica", "disponibilidade", "0–1"), ("custo_fixo_h", "custo fixo", "R$/h"),
                               ("custo_variavel_km", "custo variável", "R$/km"), ("consumo_km_l", "rendimento", "km/L")]:
            add(f"{p}.{campo}", f"{g.id} — {rot}", getattr(g, campo), un)
    r = cfg.recebimento
    for campo, rot, un in [("n_moegas", "moegas", "un"), ("capacidade_t_h", "capacidade", "t/h"),
                           ("tempo_fixo_min", "tempo fixo por caminhão", "min"), ("hora_abertura", "abertura", "h"),
                           ("hora_fechamento", "fechamento", "h"), ("custo_recebimento_t", "custo de recepção", "R$/t")]:
        add(f"recebimento.{campo}", f"Recebimento — {rot}", getattr(r, campo), un)
    j = cfg.janela
    for campo, rot, un in [("colheita_inicio_h", "início da colheita", "h"), ("colheita_fim_h", "fim da colheita", "h"),
                           ("caminhoes_inicio_h", "início jornada caminhões", "h"), ("caminhoes_fim_h", "fim jornada caminhões", "h"),
                           ("horizonte_dias", "janela disponível", "dias"), ("data_alvo_dias", "prazo desejado", "dias")]:
        add(f"janela.{campo}", f"Janela — {rot}", getattr(j, campo), un)
    add("custos.preco_diesel_l", "Preço do diesel", cfg.custos.preco_diesel_l, "R$/L")
    add("custos.valor_saca", "Preço de referência da saca", cfg.custos.valor_saca, "R$/sc")
    add("simulacao.semente", "Semente aleatória", cfg.simulacao.semente, "—")
    add("simulacao.variabilidade_cv", "Variabilidade dos tempos (CV)", cfg.simulacao.variabilidade_cv, "—")
    return pd.DataFrame(linhas)
