"""Indicadores derivados dos registros da simulação.

Cada indicador traz seu **tipo de origem**:
* ``medido``    — observado diretamente nos eventos/estados da simulação;
* ``calculado`` — fórmula sobre valores medidos e informados (ex.: custos);
* ``informado`` — parâmetro fornecido pelo usuário (ou exemplo);
* ``estimado``  — projeção/aproximação (ex.: modelo analítico do otimizador).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..domain.units import MIN_POR_DIA
from ..simulation.calendar import subtract, total
from ..simulation.records import ESTADOS_PRODUTIVOS_CAMINHAO
from ..simulation.results import SimulationResult


@dataclass
class KPI:
    chave: str
    rotulo: str
    valor: Optional[float]
    unidade: str
    tipo: str  # medido | calculado | informado | estimado
    formula: str = ""
    grupo: str = "geral"


def periodo_operacao(res: SimulationResult) -> tuple[float, float]:
    """[00:00 do dia em que a colheita começa, fim da operação]."""
    p0 = math.floor(res.t_inicio / MIN_POR_DIA) * MIN_POR_DIA
    return p0, max(res.t_fim, p0)


def dias_operacao(res: SimulationResult) -> int:
    p0, p1 = periodo_operacao(res)
    return max(1, math.ceil((p1 - p0) / MIN_POR_DIA - 1e-9))


def horas_mobilizadas_colheitadeira(res: SimulationResult) -> float:
    p0, p1 = periodo_operacao(res)
    return total(res.janelas["turno_colheita"], p0, p1) / 60.0


def horas_mobilizadas_caminhao(res: SimulationResult) -> float:
    p0, p1 = periodo_operacao(res)
    return total(res.janelas["jornada_caminhoes"], p0, p1) / 60.0


def horas_por_estado(res: SimulationResult, tipo: str) -> pd.DataFrame:
    """Horas por recurso × estado."""
    sg = res.segmentos[res.segmentos["tipo"] == tipo]
    if sg.empty:
        return pd.DataFrame()
    return sg.pivot_table(index="recurso", columns="estado", values="duracao_min", aggfunc="sum", fill_value=0.0) / 60.0


def horas_estado_em_janela(res: SimulationResult, tipo: str, estados: set[str], janelas: list) -> float:
    sg = res.segmentos[(res.segmentos["tipo"] == tipo) & (res.segmentos["estado"].isin(estados))]
    h = 0.0
    for a, b in zip(sg["inicio"], sg["fim"]):
        h += (b - a) - total(subtract([(a, b)], janelas), a, b)
    return h / 60.0


def utilizacao_colheitadeiras(res: SimulationResult) -> pd.DataFrame:
    hm = horas_mobilizadas_colheitadeira(res)
    hp = horas_por_estado(res, "colheitadeira")
    if hp.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=hp.index)
    out["horas_mobilizadas"] = hm
    for est in ["colhendo", "descarregando", "aguardando_caminhao", "deslocando", "falha", "parada_clima",
                "manutencao_programada", "ocioso"]:
        out[est + "_h"] = hp.get(est, 0.0)
    out["utilizacao_pct"] = out["colhendo_h"] / hm * 100 if hm > 0 else 0.0
    out["espera_caminhao_pct"] = out["aguardando_caminhao_h"] / hm * 100 if hm > 0 else 0.0
    return out.reset_index().rename(columns={"recurso": "colheitadeira"})


def utilizacao_caminhoes(res: SimulationResult) -> pd.DataFrame:
    hm = horas_mobilizadas_caminhao(res)
    hp = horas_por_estado(res, "caminhao")
    if hp.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=hp.index)
    out["horas_mobilizadas"] = hm
    for est in ["aguardando_carregamento", "em_carregamento", "manobra", "carregando", "transporte_carregado", "fila_descarga",
                "fila_unidade_fechada", "descarregando", "retorno_vazio", "falha"]:
        out[est + "_h"] = hp.get(est, 0.0)
    prod = sum(out[e + "_h"] for e in ESTADOS_PRODUTIVOS_CAMINHAO)
    out["produtivo_h"] = prod
    out["utilizacao_pct"] = prod / hm * 100 if hm > 0 else 0.0
    return out.reset_index().rename(columns={"recurso": "caminhao"})


def utilizacao_recepcao(res: SimulationResult) -> dict:
    p0, p1 = periodo_operacao(res)
    aberto_h = total(res.janelas["unidade"], p0, p1) / 60.0
    n = res.config.recebimento.n_moegas
    sg = res.segmentos[(res.segmentos["tipo"] == "caminhao") & (res.segmentos["estado"] == "descarregando")]
    ocup_h = sg["duracao_min"].sum() / 60.0
    return {"horas_abertas": aberto_h, "horas_moega_ocupadas": ocup_h,
            "utilizacao_pct": ocup_h / (aberto_h * n) * 100 if aberto_h > 0 else 0.0}


# ------------------------------------------------------------------------------- séries
def _contagem_estado(sg: pd.DataFrame, tempos: np.ndarray) -> np.ndarray:
    if sg.empty:
        return np.zeros_like(tempos)
    ini = np.sort(sg["inicio"].to_numpy())
    fim = np.sort(sg["fim"].to_numpy())
    return (np.searchsorted(ini, tempos, side="right") - np.searchsorted(fim, tempos, side="right")).astype(float)


def _acumulado(ev: pd.DataFrame, tipo: str, tempos: np.ndarray) -> np.ndarray:
    e = ev[ev["tipo"] == tipo]
    if e.empty:
        return np.zeros_like(tempos)
    t = e["t_min"].to_numpy()
    q = np.cumsum(e["qtd_t"].to_numpy())
    idx = np.searchsorted(t, tempos, side="right")
    return np.where(idx > 0, q[np.maximum(idx - 1, 0)], 0.0)


def serie_temporal(res: SimulationResult, passo_min: float = 15.0) -> pd.DataFrame:
    """Série amostrada a cada ``passo_min`` derivada exclusivamente de eventos e estados."""
    t_end = max(res.t_fim, passo_min)
    tempos = np.arange(0.0, t_end + passo_min, passo_min)
    ev = res.eventos
    colhido = _acumulado(ev, "COLHEITA", tempos)
    transb = _acumulado(ev, "TRANSBORDO", tempos)
    saida = _acumulado(ev, "SAIDA_CAMPO", tempos)
    chegada = _acumulado(ev, "CHEGADA_UNIDADE", tempos)
    ini_desc = _acumulado(ev, "INICIO_DESCARGA", tempos)
    entregue = _acumulado(ev, "FIM_DESCARGA", tempos)
    sg = res.segmentos
    df = pd.DataFrame({
        "t_min": tempos,
        "dia_h": tempos / 60.0,
        "colhido_acum_t": colhido,
        "entregue_acum_t": entregue,
        "em_tanques_t": colhido - transb,
        "em_caminhoes_campo_t": transb - saida,
        "em_transito_t": saida - chegada,
        "na_fila_t": chegada - ini_desc,
        "em_descarga_t": ini_desc - entregue,
    })
    df["aguardando_transporte_t"] = df["em_tanques_t"] + df["em_caminhoes_campo_t"]
    df["aguardando_descarga_t"] = df["na_fila_t"]
    for nome, tipo, estados in [
        ("n_fila_unidade", "caminhao", {"fila_descarga", "fila_unidade_fechada"}),
        ("n_descarregando", "caminhao", {"descarregando"}),
        ("n_aguardando_campo", "caminhao", {"aguardando_carregamento"}),
        ("n_transito", "caminhao", {"transporte_carregado", "retorno_vazio"}),
        ("n_colhendo", "colheitadeira", {"colhendo"}),
        ("n_colh_aguardando", "colheitadeira", {"aguardando_caminhao"}),
    ]:
        df[nome] = _contagem_estado(sg[(sg["tipo"] == tipo) & (sg["estado"].isin(estados))], tempos)
    return df


def chegadas_por_hora(res: SimulationResult) -> pd.DataFrame:
    """Toneladas que chegam à unidade por hora de relógio, vs capacidade de recebimento."""
    ev = res.eventos[res.eventos["tipo"] == "CHEGADA_UNIDADE"]
    if ev.empty:
        return pd.DataFrame(columns=["hora", "t_chegada", "capacidade_t_h"])
    h = (ev["t_min"] // 60).astype(int)
    agg = ev.groupby(h)["qtd_t"].sum()
    idx = pd.RangeIndex(int(res.t_inicio // 60), int(res.t_fim // 60) + 1)
    agg = agg.reindex(idx, fill_value=0.0)
    df = pd.DataFrame({"hora": idx, "t_chegada": agg.to_numpy()})
    df["capacidade_t_h"] = res.config.recebimento.capacidade_t_h
    return df


# ------------------------------------------------------------------------------- KPIs
def calcular_kpis(res: SimulationResult, custos_total: Optional[float] = None) -> list[KPI]:
    cfg = res.config
    from .costs import calcular_custos  # import local para evitar ciclo

    if custos_total is None:
        custos_total = float(calcular_custos(res)["valor"].sum())
    k: list[KPI] = []
    area_col = float(res.talhoes["area_colhida_ha"].sum())
    hm_c = horas_mobilizadas_colheitadeira(res)
    hm_t = horas_mobilizadas_caminhao(res)
    uc = utilizacao_colheitadeiras(res)
    ut = utilizacao_caminhoes(res)
    ur = utilizacao_recepcao(res)
    horas_colhendo = float(uc["colhendo_h"].sum()) if len(uc) else 0.0
    dias = dias_operacao(res)

    k.append(KPI("area_total", "Área a colher", cfg.area_total_ha, "ha", "informado", grupo="producao"))
    k.append(KPI("area_colhida", "Área colhida", area_col, "ha", "medido", grupo="producao"))
    k.append(KPI("pct_area", "Área concluída", area_col / cfg.area_total_ha * 100, "%", "calculado",
                 "área colhida ÷ área total × 100", "producao"))
    k.append(KPI("t_previstas", "Produção prevista", cfg.producao_prevista_t, "t", "calculado",
                 "Σ área × produtividade (sc/ha) × kg/saca ÷ 1000", "producao"))
    k.append(KPI("t_colhidas", "Toneladas colhidas", res.colhido_t, "t", "medido", grupo="producao"))
    k.append(KPI("t_entregues", "Toneladas transportadas e descarregadas", res.entregue_t, "t", "medido", grupo="producao"))
    k.append(KPI("t_pendentes", "Volume aguardando transporte/descarga no fim", res.em_tanques_t + res.em_caminhoes_t, "t",
                 "medido", "em tanques + em caminhões", "producao"))
    k.append(KPI("duracao_h", "Duração da operação", res.duracao_h, "h", "medido",
                 "fim da última descarga − início da colheita", "tempo"))
    k.append(KPI("dias_operacao", "Dias de operação", float(dias), "dias", "medido", grupo="tempo"))
    k.append(KPI("concluida", "Operação concluída na janela", 1.0 if res.concluida else 0.0, "sim/não", "medido", grupo="tempo"))
    k.append(KPI("custo_total", "Custo operacional total", custos_total, "R$", "calculado",
                 "Σ componentes da tabela de custos", "custo"))
    k.append(KPI("custo_por_t", "Custo por tonelada", custos_total / res.entregue_t if res.entregue_t > 0 else None, "R$/t",
                 "calculado", "custo total ÷ toneladas entregues", "custo"))
    k.append(KPI("custo_por_ha", "Custo por hectare", custos_total / area_col if area_col > 0 else None, "R$/ha",
                 "calculado", "custo total ÷ área colhida", "custo"))
    k.append(KPI("prod_colheita_t_h", "Produtividade média de colheita", res.colhido_t / horas_colheita_ou_1(horas_colhendo),
                 "t/h·máquina", "medido", "t colhidas ÷ horas colhendo", "producao"))
    k.append(KPI("prod_colheita_ha_h", "Ritmo médio de colheita", area_col / horas_colheita_ou_1(horas_colhendo),
                 "ha/h·máquina", "medido", "ha colhidos ÷ horas colhendo", "producao"))
    k.append(KPI("vazao_t_dia", "Vazão média entregue", res.entregue_t / dias, "t/dia", "calculado",
                 "t entregues ÷ dias de operação", "producao"))
    k.append(KPI("util_colheitadeiras", "Utilização das colheitadeiras",
                 horas_colhendo / (hm_c * len(cfg.colheitadeiras)) * 100 if hm_c > 0 else 0.0, "%", "medido",
                 "horas colhendo ÷ horas de turno mobilizadas", "utilizacao"))
    k.append(KPI("util_caminhoes", "Utilização dos caminhões",
                 float(ut["produtivo_h"].sum()) / (hm_t * cfg.n_caminhoes) * 100 if hm_t > 0 and len(ut) else 0.0, "%",
                 "medido", "horas em manobra/carregando/transporte/descarga/retorno ÷ horas de jornada mobilizadas", "utilizacao"))
    k.append(KPI("util_recepcao", "Ocupação das moegas", ur["utilizacao_pct"], "%", "medido",
                 "horas de descarga ÷ (moegas × horas abertas)", "utilizacao"))
    k.append(KPI("espera_colh_caminhao_h", "Colheitadeiras aguardando caminhão",
                 float(uc["aguardando_caminhao_h"].sum()) if len(uc) else 0.0, "h", "medido", grupo="espera"))
    k.append(KPI("caminhao_aguardando_h", "Caminhões aguardando carregamento (na jornada)",
                 float(ut["aguardando_carregamento_h"].sum()) if len(ut) else 0.0, "h", "medido", grupo="espera"))
    k.append(KPI("fila_descarga_h", "Caminhões em fila de descarga (unidade aberta)",
                 float(ut["fila_descarga_h"].sum()) if len(ut) else 0.0, "h", "medido", grupo="espera"))
    k.append(KPI("fila_fechada_h", "Caminhões aguardando unidade fechada",
                 float(ut["fila_unidade_fechada_h"].sum()) if len(ut) else 0.0, "h", "medido", grupo="espera"))
    cg = res.cargas[res.cargas["status"] == "entregue"]
    k.append(KPI("fila_media_min", "Espera média por carga na unidade", float(cg["espera_fila_min"].mean()) if len(cg) else 0.0,
                 "min", "medido", grupo="espera"))
    st = serie_temporal(res, 5.0)
    sg = res.segmentos
    fila = sg[(sg["tipo"] == "caminhao") & (sg["estado"].isin(["fila_descarga", "fila_unidade_fechada"]))]
    k.append(KPI("fila_max", "Fila máxima na unidade", float(max_simultaneo(fila)), "caminhões", "medido", grupo="espera"))
    k.append(KPI("aguardando_transporte_max", "Pico de volume aguardando transporte",
                 float(st["aguardando_transporte_t"].max()), "t", "medido", grupo="espera"))
    k.append(KPI("cargas", "Cargas entregues", float(len(cg)), "cargas", "medido", grupo="producao"))
    k.append(KPI("ocupacao_media_carga", "Ocupação média das cargas", float(cg["ocupacao_pct"].mean()) if len(cg) else 0.0,
                 "%", "medido", "t da carga ÷ capacidade do caminhão", "producao"))
    if cfg.janela.data_alvo_dias:
        k.append(KPI("prazo_alvo", "Prazo desejado", cfg.janela.data_alvo_dias, "dias", "informado", grupo="tempo"))
    return k


def max_simultaneo(sg: pd.DataFrame) -> int:
    """Máximo de segmentos simultâneos (varredura exata de eventos +1/−1)."""
    if sg.empty:
        return 0
    marcas = sorted([(a, 1) for a in sg["inicio"]] + [(b, -1) for b in sg["fim"]], key=lambda x: (x[0], x[1]))
    atual = melhor = 0
    for _, d in marcas:
        atual += d
        melhor = max(melhor, atual)
    return melhor


def horas_colheita_ou_1(h: float) -> float:
    return h if h > 1e-9 else 1.0


def kpis_dict(kpis: list[KPI]) -> dict[str, float]:
    return {x.chave: x.valor for x in kpis}


def kpis_df(kpis: list[KPI]) -> pd.DataFrame:
    return pd.DataFrame([asdict(x) for x in kpis])


def composicao_ciclo(res: SimulationResult) -> pd.DataFrame:
    """Tempo médio por carga em cada etapa do ciclo do caminhão (min)."""
    ut = utilizacao_caminhoes(res)
    n = max(int((res.cargas["status"] == "entregue").sum()), 1)
    if ut.empty:
        return pd.DataFrame()
    etapas = [("aguardando_carregamento", "Aguardando carregamento"), ("em_carregamento", "Enchendo junto à máquina"), ("manobra", "Manobra"), ("carregando", "Carregando"),
              ("transporte_carregado", "Transporte carregado"), ("fila_descarga", "Fila de descarga"),
              ("fila_unidade_fechada", "Fila (unidade fechada)"), ("descarregando", "Descarga"),
              ("retorno_vazio", "Retorno vazio")]
    return pd.DataFrame([{"etapa": rot, "estado": e, "min_por_carga": float(ut[e + "_h"].sum()) * 60 / n} for e, rot in etapas])
