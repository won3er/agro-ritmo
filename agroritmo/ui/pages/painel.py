"""Painel executivo."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ...analytics import (
    calcular_custos,
    chegadas_por_hora,
    composicao_ciclo,
    resumo_custos,
    serie_temporal,
    utilizacao_caminhoes,
    utilizacao_colheitadeiras,
)
from ...domain.units import brl, num
from .. import charts, state
from ..nav import pagina
from ..widgets import banner_origem, cabecalho, exigir_resultado, kpi, md, severidade


def render() -> None:
    cfg = state.cfg()
    cabecalho("Painel executivo", "Indicadores derivados da última simulação — cada número traz sua origem.")
    banner_origem(cfg)
    if not exigir_resultado():
        return
    res = state.resultado()
    k = state.kpis_atuais()
    pend = res.em_tanques_t + res.em_caminhoes_t

    st.markdown("##### Produção e prazo")
    c = st.columns(6)
    with c[0]:
        kpi("Toneladas colhidas", k["t_colhidas"], "t", "medido", f"de {num(k['t_previstas'], 0)} t previstas", 0)
    with c[1]:
        kpi("Transportadas e descarregadas", k["t_entregues"], "t", "medido", f"{num(pend, 1)} t pendentes no fim", 0)
    with c[2]:
        kpi("Área concluída", k["pct_area"], "%", "calculado", f"{num(k['area_colhida'], 0)} de {num(k['area_total'], 0)} ha")
    with c[3]:
        kpi("Duração da operação", k["duracao_h"], "h", "medido", f"{int(k['dias_operacao'])} dias de calendário")
    with c[4]:
        alvo = cfg.janela.data_alvo_dias
        det = (f"prazo {num(alvo, 0)} d — {'atendido' if res.t_fim / 1440 <= alvo else 'excedido'}" if alvo else "sem prazo definido")
        kpi("Conclusão", res.t_fim / 1440, "dias", "medido", det)
    with c[5]:
        kpi("Produtividade média", k["prod_colheita_t_h"], "t/h·máq", "medido", f"{num(k['prod_colheita_ha_h'], 2)} ha/h colhendo")

    st.markdown("##### Custos e utilização")
    c = st.columns(6)
    with c[0]:
        kpi("Custo operacional", k["custo_total"], "", "calculado", "Σ componentes (ver composição)", moeda=True)
    with c[1]:
        kpi("Custo por tonelada", k["custo_por_t"], "R$/t", "calculado", f"{brl(k['custo_por_ha'])}/ha", 2)
    with c[2]:
        kpi("Utilização colheitadeiras", k["util_colheitadeiras"], "%", "medido", "colhendo ÷ horas de turno")
    with c[3]:
        kpi("Utilização caminhões", k["util_caminhoes"], "%", "medido", "ciclo produtivo ÷ jornada")
    with c[4]:
        kpi("Ocupação das moegas", k["util_recepcao"], "%", "medido", "descarga ÷ (moegas × horas abertas)")
    with c[5]:
        kpi("Vazão entregue", k["vazao_t_dia"], "t/dia", "calculado", f"{int(k['cargas'])} cargas, {num(k['ocupacao_media_carga'], 0)}% de ocupação", 0)

    st.markdown("##### Esperas e filas")
    c = st.columns(6)
    with c[0]:
        kpi("Colheitadeiras sem caminhão", k["espera_colh_caminhao_h"], "h", "medido", "soma das máquinas")
    with c[1]:
        kpi("Caminhões aguardando no campo", k["caminhao_aguardando_h"], "h", "medido", "fila atrás de outro caminhão/máquina parada")
    with c[2]:
        kpi("Fila de descarga", k["fila_descarga_h"], "h", "medido", f"média {num(k['fila_media_min'], 1)} min por carga")
    with c[3]:
        kpi("Aguardando unidade fechada", k["fila_fechada_h"], "h", "medido", "cargas retidas fora do horário")
    with c[4]:
        kpi("Fila máxima", k["fila_max"], "caminhões", "medido", "simultâneos na unidade", 0)
    with c[5]:
        kpi("Pico aguardando transporte", k["aguardando_transporte_max"], "t", "medido", "tanques + caminhões no campo")

    serie = serie_temporal(res, 15.0)
    g1, g2 = st.columns(2)
    g1.plotly_chart(charts.producao(serie), use_container_width=True)
    g2.plotly_chart(charts.volumes_em_processo(serie), use_container_width=True)
    g1, g2 = st.columns(2)
    g1.plotly_chart(charts.filas(serie), use_container_width=True)
    g2.plotly_chart(charts.chegadas(chegadas_por_hora(res)), use_container_width=True)
    g1, g2 = st.columns(2)
    g1.plotly_chart(charts.utilizacao(utilizacao_colheitadeiras(res), "colheitadeira",
                                      ["colhendo", "descarregando", "aguardando_caminhao", "deslocando", "manutencao_programada",
                                       "falha", "parada_clima", "ocioso"], "Utilização das colheitadeiras (horas por estado)"),
                    use_container_width=True)
    g2.plotly_chart(charts.utilizacao(utilizacao_caminhoes(res), "caminhao",
                                      ["em_carregamento", "carregando", "manobra", "transporte_carregado", "descarregando",
                                       "retorno_vazio", "aguardando_carregamento", "fila_descarga", "fila_unidade_fechada", "falha"],
                                      "Utilização dos caminhões (horas por estado)"), use_container_width=True)
    g1, g2 = st.columns(2)
    custos = calcular_custos(res)
    g1.plotly_chart(charts.custos(resumo_custos(custos)), use_container_width=True)
    g2.plotly_chart(charts.ciclo(composicao_ciclo(res)), use_container_width=True)

    st.markdown("##### Principais gargalos")
    gs = st.session_state.get("gargalos") or []
    if not gs:
        st.info("Nenhum gargalo relevante identificado.")
    for g in gs[:3]:
        st.markdown(md(f"{severidade(g.severidade)} **{g.titulo}** — {g.evidencia}"), unsafe_allow_html=True)
    st.page_link(pagina("gargalos"), label="Ver evidências, fórmulas e recomendações", icon="🚧")

    st.markdown("##### Cenário atual × otimizado")
    linhas = _atual_vs_otimizado(k)
    if linhas is None:
        st.info("Ainda não há cenário otimizado. Rode a otimização de frota ou a comparação de cenários para preencher este quadro.")
        c1, c2 = st.columns(2)
        c1.page_link(pagina("otimizacao"), label="Otimização", icon="🎯")
        c2.page_link(pagina("cenarios"), label="Cenários", icon="🧭")
    else:
        st.dataframe(linhas, use_container_width=True, hide_index=True)
        st.caption("Valores do cenário otimizado obtidos por simulação (mesma semente). Diferença = otimizado − atual.")


def _atual_vs_otimizado(k: dict):
    comp = st.session_state.get("comparacao")
    of = st.session_state.get("otim_frota")
    alvo, nome = None, None
    if comp is not None and comp.melhor and comp.melhor != "Original":
        r = next(x for x in comp.resultados if x.nome == comp.melhor)
        alvo, nome = r.media, f"Melhor cenário: {comp.melhor}"
    elif of is not None and "caminhoes_simulado" in of.recomendacao:
        sim = of.detalhes["simulacao"]
        row = sim[sim["caminhoes"] == of.recomendacao["caminhoes_simulado"]].iloc[0]
        alvo, nome = row.to_dict(), f"Frota otimizada: {of.recomendacao['caminhoes_simulado']} caminhões"
    if alvo is None:
        return None
    metricas = [("duracao_h", "Duração (h)"), ("custo_total", "Custo total (R$)"), ("custo_por_t", "Custo por t (R$/t)"),
                ("espera_colh_caminhao_h", "Colheitadeiras aguardando (h)"), ("fila_descarga_h", "Fila de descarga (h)"),
                ("util_caminhoes", "Utilização caminhões (%)")]
    out = []
    for m, rot in metricas:
        a, b = k.get(m), alvo.get(m)
        out.append({"Indicador": rot, "Atual": a, nome: b, "Diferença": (b - a) if a is not None and b is not None else None})
    return pd.DataFrame(out)
