"""Identificação automática de gargalos a partir dos registros da simulação.

Regras de transparência:
* toda evidência é medida nos estados/eventos simulados;
* toda consequência financeira mostra a fórmula e os parâmetros;
* o custo de recursos parados já está contido no custo total (não é somado de novo) — ele mostra
  quanto do custo foi pago por tempo improdutivo;
* o impacto de cada recomendação só é afirmado depois de validado por uma nova simulação com a
  mesma semente aleatória.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..domain.units import brl, num
from ..scenarios.modifications import Cenario, Modificacao
from ..simulation.results import SimulationResult
from .kpis import (
    chegadas_por_hora,
    horas_estado_em_janela,
    horas_mobilizadas_caminhao,
    horas_mobilizadas_colheitadeira,
    kpis_dict,
    calcular_kpis,
    utilizacao_caminhoes,
    utilizacao_colheitadeiras,
    utilizacao_recepcao,
)


@dataclass
class Gargalo:
    codigo: str
    titulo: str
    severidade: str
    evidencia: str
    duracao_h: float
    frequencia: int
    recursos: list[str]
    consequencia_tempo_h: float
    consequencia_volume_t: float
    consequencia_rs: float
    formula_rs: str
    recomendacao: str
    metricas: dict = field(default_factory=dict)
    validacao: Optional[Cenario] = None
    metrica_alvo: Optional[str] = None
    impacto: Optional[dict] = None

    @property
    def peso(self) -> float:
        return {"alta": 3, "media": 2, "baixa": 1}[self.severidade] * 1e9 + self.consequencia_rs


def _hh(h: float) -> str:
    """Hora decimal → 'HHhMM' (ex.: 20,8 → 20h48)."""
    m = int(round(h * 60))
    return f"{m // 60}h{m % 60:02d}" if m % 60 else f"{m // 60}h"


def _sev(frac: float, alta: float, media: float) -> str:
    return "alta" if frac >= alta else "media" if frac >= media else "baixa"


def _episodios(ev: pd.DataFrame, tipo: str, recurso: Optional[str] = None) -> int:
    e = ev[ev["tipo"] == tipo]
    if recurso:
        e = e[e["recurso"] == recurso]
    return int(len(e))


def identificar_gargalos(res: SimulationResult) -> list[Gargalo]:
    cfg = res.config
    ev = res.eventos
    out: list[Gargalo] = []
    uc = utilizacao_colheitadeiras(res).set_index("colheitadeira")
    ut = utilizacao_caminhoes(res).set_index("caminhao")
    hm_c = horas_mobilizadas_colheitadeira(res)
    hm_t = horas_mobilizadas_caminhao(res)
    ch = res.colheitadeiras.set_index("colheitadeira")
    specs_c = {c.id: c for c in cfg.colheitadeiras}
    specs_t = dict(cfg.caminhoes_expandidos())
    custo_fixo_cam_medio = float(np.mean([g.custo_fixo_h for _, g in cfg.caminhoes_expandidos()]))

    # 1 ── colheitadeiras aguardando caminhão --------------------------------------------
    espera_total = float(uc["aguardando_caminhao_h"].sum()) if len(uc) else 0.0
    colhendo_total = float(uc["colhendo_h"].sum()) if len(uc) else 0.0
    if espera_total > 0.25:
        partes, vol, rs, recursos = [], 0.0, 0.0, []
        for hid, row in uc.iterrows():
            w = float(row["aguardando_caminhao_h"])
            if w <= 0.01:
                continue
            prod = float(ch.loc[hid, "horas_colheita"])
            taxa = (res.talhoes["t_colhidas"].sum() / max(colhendo_total, 1e-9)) if prod <= 0 else \
                float(_t_colhidas_por(res, hid) / prod)
            vol += w * taxa
            rs += w * specs_c[hid].custo_fixo_h
            partes.append(f"{num(w, 1)} h × {brl(specs_c[hid].custo_fixo_h)}/h ({hid})")
            recursos.append(hid)
        ep = _episodios(ev, "ESPERA_CAMINHAO_INICIO")
        frac = espera_total / max(colhendo_total, 1e-9)
        out.append(Gargalo(
            codigo="COLH_AGUARDA_CAMINHAO", titulo="Colheitadeiras paradas aguardando caminhão",
            severidade=_sev(frac, 0.10, 0.04),
            evidencia=(f"{num(espera_total, 1)} h de espera em {ep} episódios (média {num(espera_total * 60 / max(ep, 1), 0)} min); "
                       f"equivale a {num(frac * 100, 1)}% do tempo colhendo."),
            duracao_h=espera_total, frequencia=ep, recursos=recursos, consequencia_tempo_h=espera_total,
            consequencia_volume_t=vol,
            consequencia_rs=rs, formula_rs=" + ".join(partes) + f" = {brl(rs)} (custo fixo pago com a máquina parada)",
            recomendacao="Adicionar 1 caminhão à frota ou redistribuir caminhões para as colheitadeiras com maior espera.",
            metricas={"episodios": ep, "espera_media_min": espera_total * 60 / max(ep, 1),
                      "volume_nao_colhido_no_periodo_t": vol},
            validacao=Cenario(nome="+1 caminhão", modificacoes=[Modificacao(tipo="caminhoes_extra", valor=1)]),
            metrica_alvo="espera_colh_caminhao_h",
        ))

    # 2 ── caminhões ociosos no campo (durante o turno de colheita) ---------------------
    turno = res.janelas["turno_colheita"]
    ocio_turno = horas_estado_em_janela(res, "caminhao", {"aguardando_carregamento"}, turno)
    ocio_total = float(ut["aguardando_carregamento_h"].sum()) if len(ut) else 0.0
    ocio_fora_turno = max(ocio_total - ocio_turno, 0.0)
    horas_turno_frota = hm_c * cfg.n_caminhoes
    if ocio_turno > 0.5 and horas_turno_frota > 0:
        frac = ocio_turno / horas_turno_frota
        if frac >= 0.15:
            rs = ocio_turno * custo_fixo_cam_medio
            out.append(Gargalo(
                codigo="CAMINHOES_OCIOSOS", titulo="Caminhões aguardando carregamento durante o turno de colheita",
                severidade=_sev(frac, 0.40, 0.25),
                evidencia=(f"{num(ocio_turno, 1)} h de caminhões parados junto às colheitadeiras dentro do turno "
                           f"({num(frac * 100, 1)}% das horas de turno da frota)."),
                duracao_h=ocio_turno, frequencia=int((res.cargas["tempo_carregamento_min"] > 0).sum()),
                recursos=list(ut.index), consequencia_tempo_h=ocio_turno, consequencia_volume_t=0.0, consequencia_rs=rs,
                formula_rs=f"{num(ocio_turno, 1)} h × {brl(custo_fixo_cam_medio)}/h (custo fixo médio do caminhão) = {brl(rs)}",
                recomendacao=("Frota acima da necessidade nos períodos de colheita: avaliar retirar 1 caminhão "
                              "(verificar se a espera das colheitadeiras não aumenta)."),
                validacao=Cenario(nome="−1 caminhão", modificacoes=[Modificacao(tipo="caminhoes_extra", valor=-1)])
                if cfg.n_caminhoes > 1 else None,
                metrica_alvo="custo_por_t",
            ))

    # 3 ── jornada de caminhões desalinhada com o turno de colheita --------------------
    j = cfg.janela
    if ocio_fora_turno > 1.0:
        rs = ocio_fora_turno * custo_fixo_cam_medio
        fim_sugerido = min(24.0, max(j.colheita_fim_h + 1.0, min(j.caminhoes_fim_h, j.colheita_fim_h + _ciclo_medio_h(res))))
        ini_sugerido = max(0.0, j.colheita_inicio_h)
        cen = None
        if (ini_sugerido, fim_sugerido) != (j.caminhoes_inicio_h, j.caminhoes_fim_h):
            cen = Cenario(nome="Jornada alinhada ao turno",
                          modificacoes=[Modificacao(tipo="jornada_caminhoes", inicio_h=ini_sugerido, fim_h=round(fim_sugerido, 1))])
        out.append(Gargalo(
            codigo="JORNADA_DESALINHADA", titulo="Caminhões mobilizados fora do turno de colheita",
            severidade=_sev(ocio_fora_turno / max(hm_t * cfg.n_caminhoes, 1e-9), 0.20, 0.08),
            evidencia=(f"{num(ocio_fora_turno, 1)} h de caminhões aguardando no campo quando as colheitadeiras estão fora do turno "
                       f"(jornada {j.caminhoes_inicio_h:.0f}h–{j.caminhoes_fim_h:.0f}h; colheita {j.colheita_inicio_h:.0f}h–{j.colheita_fim_h:.0f}h)."),
            duracao_h=ocio_fora_turno, frequencia=int(res.janelas and len(res.janelas["turno_colheita"])), recursos=list(ut.index),
            consequencia_tempo_h=ocio_fora_turno, consequencia_volume_t=0.0, consequencia_rs=rs,
            formula_rs=f"{num(ocio_fora_turno, 1)} h × {brl(custo_fixo_cam_medio)}/h = {brl(rs)}",
            recomendacao=(f"Ajustar a jornada dos caminhões para {_hh(ini_sugerido)}–{_hh(round(fim_sugerido, 1))} "
                          "(início com a colheita e fim após o último ciclo)."),
            validacao=cen, metrica_alvo="custo_total",
        ))

    # 4 ── fila de descarga com unidade aberta ------------------------------------------
    fila_h = float(ut["fila_descarga_h"].sum()) if len(ut) else 0.0
    cg = res.cargas[res.cargas["status"] == "entregue"]
    if fila_h > 0.5 and len(cg):
        esperas = cg["t_inicio_descarga"] - cg["t_chegada_unidade"]
        n_esperaram = int((esperas > 1.0).sum())
        media = float(fila_h * 60 / len(cg))
        frac = fila_h / max(float(ut["produtivo_h"].sum()), 1e-9)
        rs = sum(float(ut.loc[c, "fila_descarga_h"]) * specs_t[c].custo_fixo_h for c in ut.index)
        out.append(Gargalo(
            codigo="FILA_DESCARGA", titulo="Caminhões parados em fila de descarga",
            severidade=_sev(frac, 0.15, 0.05),
            evidencia=(f"{num(fila_h, 1)} h de fila com a unidade aberta; {n_esperaram} de {len(cg)} cargas esperaram; "
                       f"média de {num(media, 0)} min por carga."),
            duracao_h=fila_h, frequencia=n_esperaram, recursos=[cfg.recebimento.nome], consequencia_tempo_h=fila_h,
            consequencia_volume_t=float((cg["quantidade_t"] * (esperas > 1.0)).sum()), consequencia_rs=rs,
            formula_rs=f"Σ horas em fila por caminhão × custo fixo do caminhão = {brl(rs)}",
            recomendacao="Aumentar a capacidade de recebimento (moega adicional ou maior vazão) ou escalonar a chegada dos caminhões.",
            metricas={"cargas_com_espera": n_esperaram, "espera_media_min": media},
            validacao=Cenario(nome="Recebimento +30%", modificacoes=[Modificacao(tipo="capacidade_recebimento", valor=1.3)]),
            metrica_alvo="fila_descarga_h",
        ))

    # 5 ── unidade fechada retendo cargas -------------------------------------------------
    fech_h = float(ut["fila_unidade_fechada_h"].sum()) if len(ut) else 0.0
    if fech_h > 0.5:
        retidas = res.cargas[(res.cargas["status"] == "entregue")]
        retidas = retidas[retidas["espera_fila_min"] > 60]
        r = cfg.recebimento
        fim = min(24.0, max(r.hora_fechamento, j.caminhoes_fim_h) + 2.0)
        out.append(Gargalo(
            codigo="UNIDADE_FECHADA", titulo="Cargas retidas aguardando a unidade abrir",
            severidade=_sev(fech_h / max(hm_t * cfg.n_caminhoes, 1e-9), 0.10, 0.03),
            evidencia=(f"{num(fech_h, 1)} h de caminhões carregados aguardando a reabertura da unidade "
                       f"({len(retidas)} cargas, {num(float(retidas['quantidade_t'].sum()), 0)} t retidas)."),
            duracao_h=fech_h, frequencia=len(retidas), recursos=[r.nome], consequencia_tempo_h=fech_h,
            consequencia_volume_t=float(retidas["quantidade_t"].sum()), consequencia_rs=0.0,
            formula_rs=("Sem custo direto no modelo (espera fora da jornada não é cobrada); o efeito é a indisponibilidade "
                        "dos caminhões no início do dia seguinte."),
            recomendacao=f"Estender o horário da unidade até {fim:.0f}h ou encerrar o despacho de caminhões mais cedo.",
            validacao=Cenario(nome="Unidade até mais tarde", modificacoes=[
                Modificacao(tipo="horario_recebimento", inicio_h=r.hora_abertura, fim_h=fim)]),
            metrica_alvo="duracao_h",
        ))

    # 6 ── recepção acima da capacidade planejada ---------------------------------------
    cph = chegadas_por_hora(res)
    ur = utilizacao_recepcao(res)
    if len(cph):
        acima = cph[cph["t_chegada"] > cph["capacidade_t_h"] + 1e-9]
        if len(acima) >= 1 or ur["utilizacao_pct"] > 85:
            pico = float(cph["t_chegada"].max())
            out.append(Gargalo(
                codigo="RECEPCAO_SOBRECARGA", titulo="Chegadas acima da capacidade de recebimento",
                severidade=_sev(len(acima) / max(len(cph), 1), 0.10, 0.03) if ur["utilizacao_pct"] <= 85 else "alta",
                evidencia=(f"{len(acima)} hora(s) com chegadas acima de {num(cfg.recebimento.capacidade_t_h, 0)} t/h "
                           f"(pico {num(pico, 0)} t/h); ocupação média das moegas {num(ur['utilizacao_pct'], 1)}%."),
                duracao_h=float(len(acima)), frequencia=len(acima), recursos=[cfg.recebimento.nome],
                consequencia_tempo_h=0.0, consequencia_volume_t=float((acima["t_chegada"] - acima["capacidade_t_h"]).sum()),
                consequencia_rs=0.0, formula_rs="Impacto financeiro contabilizado na fila de descarga (evita dupla contagem).",
                recomendacao="Escalonar a saída dos caminhões ou ampliar a capacidade de recebimento nos horários de pico.",
                metricas={"pico_t_h": pico, "ocupacao_moegas_pct": ur["utilizacao_pct"]},
                validacao=Cenario(nome="Recebimento +30%", modificacoes=[Modificacao(tipo="capacidade_recebimento", valor=1.3)]),
                metrica_alvo="fila_descarga_h",
            ))

    # 7 ── falhas mecânicas --------------------------------------------------------------
    falha_c = float(uc["falha_h"].sum()) if len(uc) else 0.0
    falha_t = float(ut["falha_h"].sum()) if len(ut) else 0.0
    if falha_c + falha_t > 1.0:
        n_f = _episodios(ev, "FALHA")
        frac = falha_c / max(hm_c * len(cfg.colheitadeiras), 1e-9)
        rs = sum(float(uc.loc[h, "falha_h"]) * specs_c[h].custo_fixo_h for h in uc.index) + \
            sum(float(ut.loc[c, "falha_h"]) * specs_t[c].custo_fixo_h for c in ut.index)
        alvo = min(0.98, max(c.disponibilidade_mecanica for c in cfg.colheitadeiras) + 0.03)
        out.append(Gargalo(
            codigo="FALHAS", titulo="Paradas não programadas por falha mecânica",
            severidade=_sev(frac, 0.10, 0.04),
            evidencia=f"{n_f} falhas; {num(falha_c, 1)} h em colheitadeiras e {num(falha_t, 1)} h em caminhões.",
            duracao_h=falha_c + falha_t, frequencia=n_f,
            recursos=sorted(set(ev[ev["tipo"] == "FALHA"]["recurso"])), consequencia_tempo_h=falha_c + falha_t,
            consequencia_volume_t=sum(float(uc.loc[h, "falha_h"]) * _taxa_t_h(res, h) for h in uc.index),
            consequencia_rs=rs, formula_rs=f"Σ horas em reparo × custo fixo do equipamento = {brl(rs)}",
            recomendacao=f"Reforçar manutenção preventiva/peças de reposição para elevar a disponibilidade para {alvo:.0%}.",
            validacao=Cenario(nome=f"Disponibilidade {alvo:.0%}", modificacoes=[Modificacao(tipo="disponibilidade", valor=alvo)]),
            metrica_alvo="duracao_h",
        ))

    # 8 ── equipamentos com baixa utilização -------------------------------------------
    for hid, row in uc.iterrows():
        if row["utilizacao_pct"] < 45 and hm_c > 0:
            perdas = {k: float(row[k + "_h"]) for k in ("aguardando_caminhao", "falha", "parada_clima", "ocioso",
                                                         "deslocando", "manutencao_programada")}
            dominante = max(perdas, key=perdas.get)
            out.append(Gargalo(
                codigo=f"BAIXA_UTIL_{hid}", titulo=f"Baixa utilização da colheitadeira {hid}",
                severidade="media" if row["utilizacao_pct"] < 35 else "baixa",
                evidencia=(f"Colhendo {num(row['utilizacao_pct'], 1)}% das {num(hm_c, 1)} h de turno; maior perda: "
                           f"{dominante.replace('_', ' ')} ({num(perdas[dominante], 1)} h)."),
                duracao_h=hm_c - float(row["colhendo_h"]), frequencia=1, recursos=[hid],
                consequencia_tempo_h=hm_c - float(row["colhendo_h"]), consequencia_volume_t=0.0, consequencia_rs=0.0,
                formula_rs="Custos de tempo parado já detalhados nos gargalos de espera/falha.",
                recomendacao="Atacar a principal causa de perda indicada na evidência.",
                metricas=perdas,
            ))
    util_cam = float(ut["produtivo_h"].sum()) / max(hm_t * cfg.n_caminhoes, 1e-9) * 100 if len(ut) else 0.0
    if util_cam < 35 and not any(g.codigo in ("CAMINHOES_OCIOSOS", "JORNADA_DESALINHADA") for g in out):
        out.append(Gargalo(
            codigo="BAIXA_UTIL_CAMINHOES", titulo="Baixa utilização da frota de caminhões", severidade="baixa",
            evidencia=f"Frota em atividade produtiva {num(util_cam, 1)}% das horas de jornada.",
            duracao_h=0.0, frequencia=1, recursos=list(ut.index), consequencia_tempo_h=0.0, consequencia_volume_t=0.0,
            consequencia_rs=0.0, formula_rs="—", recomendacao="Rever tamanho da frota e jornada.",
        ))

    # 9 ── talhões desfavoráveis (deslocamento/produtividade) --------------------------
    tf = _transporte_por_talhao(res)
    if len(tf) >= 2:
        media_h_t = float(tf["h_caminhao"].sum() / tf["t"].sum())
        for _, row in tf.iterrows():
            if row["h_por_t"] > 1.3 * media_h_t and row["t"] > 0:
                extra_h = (row["h_por_t"] - media_h_t) * row["t"]
                rs = extra_h * custo_fixo_cam_medio
                tal = cfg.talhao(row["talhao"])
                out.append(Gargalo(
                    codigo=f"TALHAO_{row['talhao']}", titulo=f"Talhão {row['talhao']} exige mais transporte por tonelada",
                    severidade="baixa" if row["h_por_t"] < 1.6 * media_h_t else "media",
                    evidencia=(f"{num(row['h_por_t'] * 60, 1)} min de caminhão por t (média da operação "
                               f"{num(media_h_t * 60, 1)} min/t); distância {num(tal.distancia_km, 1)} km; "
                               f"produtividade {num(tal.produtividade_sc_ha, 0)} sc/ha."),
                    duracao_h=float(row["h_caminhao"]), frequencia=int(row["cargas"]), recursos=[row["talhao"]],
                    consequencia_tempo_h=extra_h, consequencia_volume_t=float(row["t"]), consequencia_rs=rs,
                    formula_rs=(f"({num(row['h_por_t'], 4)} − {num(media_h_t, 4)}) h/t × {num(row['t'], 1)} t × "
                                f"{brl(custo_fixo_cam_medio)}/h = {brl(rs)}"),
                    recomendacao=("Concentrar mais caminhões enquanto este talhão é colhido (alocação dedicada) ou "
                                  "programá-lo para quando a frota estiver ociosa."),
                ))

    # 10 ── risco de ultrapassar a janela ----------------------------------------------
    if not res.concluida:
        pend_t = cfg.producao_prevista_t - res.entregue_t
        pend_ha = cfg.area_total_ha - float(res.talhoes["area_colhida_ha"].sum())
        sacas = pend_t * 1000 / cfg.kg_por_saca
        valor = sacas * cfg.custos.valor_saca
        out.append(Gargalo(
            codigo="JANELA_EXCEDIDA", titulo="Operação não conclui dentro da janela disponível", severidade="alta",
            evidencia=(f"Ao fim de {j.horizonte_dias} dias restam {num(pend_ha, 1)} ha e {num(pend_t, 1)} t "
                       "não entregues."),
            duracao_h=0.0, frequencia=1, recursos=[], consequencia_tempo_h=0.0, consequencia_volume_t=pend_t,
            consequencia_rs=valor,
            formula_rs=(f"{num(sacas, 0)} sc × {brl(cfg.custos.valor_saca)}/sc = {brl(valor)} de produção em risco"
                        if cfg.custos.valor_saca > 0 else "Informe o preço de referência da saca para valorar o volume em risco."),
            recomendacao="Adicionar capacidade de colheita (colheitadeira) ou ampliar o turno de colheita.",
            validacao=Cenario(nome="+1 colheitadeira", modificacoes=[Modificacao(tipo="colheitadeira_extra", valor=1)]),
            metrica_alvo="pct_area",
        ))
    elif j.data_alvo_dias and res.t_fim / 1440 > j.data_alvo_dias:
        atraso_d = res.t_fim / 1440 - j.data_alvo_dias
        out.append(Gargalo(
            codigo="PRAZO_EXCEDIDO", titulo="Conclusão após o prazo desejado",
            severidade="alta" if atraso_d > 2 else "media",
            evidencia=(f"Conclusão no dia {num(res.t_fim / 1440, 1)} contra prazo de {num(j.data_alvo_dias, 0)} dias "
                       f"(atraso de {num(atraso_d, 1)} dias)."),
            duracao_h=atraso_d * 24, frequencia=1, recursos=[], consequencia_tempo_h=atraso_d * 24,
            consequencia_volume_t=0.0, consequencia_rs=0.0,
            formula_rs="Sem custo de atraso informado; avaliar perdas de campo por atraso fora do modelo.",
            recomendacao="Adicionar capacidade de colheita ou ampliar o turno de colheita.",
            validacao=Cenario(nome="+1 colheitadeira", modificacoes=[Modificacao(tipo="colheitadeira_extra", valor=1)]),
            metrica_alvo="duracao_h",
        ))

    # 11 ── clima (informativo) ----------------------------------------------------------
    clima_h = float(uc["parada_clima_h"].sum()) if len(uc) else 0.0
    if clima_h > 0.5:
        out.append(Gargalo(
            codigo="CLIMA", titulo="Paradas por chuva e secagem", severidade="baixa",
            evidencia=f"{num(clima_h, 1)} h-máquina paradas por chuva/secagem ({len(res.janelas['chuvas'])} evento(s)).",
            duracao_h=clima_h, frequencia=len(res.janelas["chuvas"]), recursos=list(uc.index),
            consequencia_tempo_h=clima_h, consequencia_volume_t=sum(float(uc.loc[h, "parada_clima_h"]) * _taxa_t_h(res, h) for h in uc.index),
            consequencia_rs=sum(float(uc.loc[h, "parada_clima_h"]) * specs_c[h].custo_fixo_h for h in uc.index),
            formula_rs="Σ horas paradas por clima × custo fixo da colheitadeira",
            recomendacao="Fator não controlável: manter reserva de capacidade (folga de dias na janela) para absorver chuvas.",
        ))

    return sorted(out, key=lambda g: -g.peso)


def validar_recomendacoes(res: SimulationResult, gargalos: list[Gargalo], replicacoes: int = 1,
                          progresso: Optional[Callable[[int, int, str], None]] = None) -> list[Gargalo]:
    """Executa uma nova simulação para cada recomendação com cenário de validação."""
    from ..scenarios.compare import executar_cenario

    base = kpis_dict(calcular_kpis(res)) if replicacoes == 1 else executar_cenario(res.config, Cenario(nome="Base"), replicacoes).media
    cache: dict[str, dict] = {}
    alvos = [g for g in gargalos if g.validacao is not None]
    for i, g in enumerate(alvos):
        chave = g.validacao.descrever()
        if progresso:
            progresso(i, len(alvos), g.validacao.nome)
        if chave not in cache:
            cache[chave] = executar_cenario(res.config, g.validacao, replicacoes).media
        novo = cache[chave]
        imp = {"cenario": g.validacao.nome, "descricao": chave, "replicacoes": replicacoes}
        for m in ("duracao_h", "custo_total", "custo_por_t", "t_entregues", "pct_area", "espera_colh_caminhao_h",
                  "fila_descarga_h", "concluida"):
            b, n = base.get(m), novo.get(m)
            imp[m] = {"base": b, "novo": n, "delta": (n - b) if (b is not None and n is not None) else None}
        imp["metrica_alvo"] = g.metrica_alvo
        d_custo = imp["custo_por_t"]["delta"]
        d_dur = imp["duracao_h"]["delta"]
        partes = []
        if d_dur is not None:
            partes.append(f"duração {'+' if d_dur >= 0 else ''}{num(d_dur, 1)} h")
        if d_custo is not None:
            partes.append(f"custo/t {'+' if d_custo >= 0 else ''}{brl(d_custo)}")
        alvo = imp.get(g.metrica_alvo or "", {})
        if isinstance(alvo, dict) and alvo.get("delta") is not None and g.metrica_alvo not in ("duracao_h", "custo_por_t"):
            partes.append(f"{g.metrica_alvo} {'+' if alvo['delta'] >= 0 else ''}{num(alvo['delta'], 1)}")
        imp["resumo"] = "; ".join(partes)
        imp["avaliacao"] = _avaliar(g.metrica_alvo, alvo, d_custo, d_dur)
        imp["recomendacao_confirmada"] = imp["avaliacao"] in ("melhora", "trade_off")
        g.impacto = imp
    return gargalos


MAIOR_MELHOR = {"pct_area", "t_entregues", "concluida"}
AVALIACOES = {
    "melhora": "Confirmada: melhora o indicador-alvo sem aumentar o custo por tonelada",
    "trade_off": "Confirmada com trade-off: melhora o indicador-alvo, mas aumenta o custo por tonelada",
    "nao_confirmada": "Não confirmada: a nova simulação não melhorou o indicador-alvo",
}


def _avaliar(metrica: Optional[str], alvo: dict, d_custo: Optional[float], d_dur: Optional[float]) -> str:
    tol = 1e-6
    if not metrica or not isinstance(alvo, dict) or alvo.get("delta") is None:
        return "nao_confirmada"
    delta = alvo["delta"]
    melhorou = delta > tol if metrica in MAIOR_MELHOR else delta < -tol
    if metrica == "custo_por_t":
        melhorou = d_custo is not None and d_custo < -tol and (d_dur is None or d_dur <= 24)
        return "melhora" if melhorou else "nao_confirmada"
    if not melhorou:
        return "nao_confirmada"
    return "melhora" if (d_custo is None or d_custo <= tol) else "trade_off"


# --------------------------------------------------------------------------- auxiliares
def _t_colhidas_por(res: SimulationResult, hid: str) -> float:
    ev = res.eventos
    return float(ev[(ev["tipo"] == "COLHEITA") & (ev["recurso"] == hid)]["qtd_t"].sum())


def _taxa_t_h(res: SimulationResult, hid: str) -> float:
    h = float(res.colheitadeiras.set_index("colheitadeira").loc[hid, "horas_colheita"])
    return _t_colhidas_por(res, hid) / h if h > 0 else 0.0


def _ciclo_medio_h(res: SimulationResult) -> float:
    cg = res.cargas[res.cargas["status"] == "entregue"]
    if cg.empty:
        return 2.0
    ida = (cg["t_fim_descarga"] - cg["t_saida_campo"]).median() / 60
    return float(ida * 1.8)


def _transporte_por_talhao(res: SimulationResult) -> pd.DataFrame:
    """Horas de caminhão (transporte carregado + fila + descarga + retorno) por talhão de origem."""
    cfg = res.config
    sg = res.segmentos[res.segmentos["tipo"] == "caminhao"]
    cg = res.cargas[res.cargas["status"] == "entregue"]
    if cg.empty:
        return pd.DataFrame()
    por_carga = sg[sg["carga"].notna()].groupby("carga")["duracao_min"].sum()
    linhas = []
    vel = {g.id: g for g in cfg.frota}
    for tid, grp in cg.groupby("talhao_origem"):
        h = 0.0
        for _, c in grp.iterrows():
            h += float(por_carga.get(c["carga"], 0.0)) / 60
            g = vel[c["tipo_caminhao"]]
            h += c["distancia_km"] / g.velocidade_vazio_km_h  # retorno vazio estimado pela distância
        t = float(grp["quantidade_t"].sum())
        linhas.append({"talhao": tid, "t": t, "cargas": len(grp), "h_caminhao": h, "h_por_t": h / t if t > 0 else math.nan})
    return pd.DataFrame(linhas)


def gargalos_df(gargalos: list[Gargalo]) -> pd.DataFrame:
    return pd.DataFrame([{
        "codigo": g.codigo, "titulo": g.titulo, "severidade": g.severidade, "evidencia": g.evidencia,
        "duracao_h": g.duracao_h, "frequencia": g.frequencia, "recursos": ", ".join(g.recursos),
        "consequencia_tempo_h": g.consequencia_tempo_h, "consequencia_volume_t": g.consequencia_volume_t,
        "consequencia_rs": g.consequencia_rs, "formula_rs": g.formula_rs, "recomendacao": g.recomendacao,
        "validacao": g.validacao.descrever() if g.validacao else "",
        "impacto_validado": g.impacto["resumo"] if g.impacto else "",
        "avaliacao": AVALIACOES[g.impacto["avaliacao"]] if g.impacto else "Sem cenário de validação automática",
    } for g in gargalos])
