"""Análise de gargalos com evidências, fórmulas e validação das recomendações."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ...analytics import gargalos_df, validar_recomendacoes
from ...analytics.bottlenecks import AVALIACOES
from ...domain.units import brl, num
from ...reports.export import exportar_csv
from .. import state
from ..widgets import banner_origem, cabecalho, exigir_resultado, formula, md, severidade


def render() -> None:
    cabecalho("Gargalos da operação", "Identificados automaticamente a partir dos estados e eventos simulados.")
    banner_origem(state.cfg())
    if not exigir_resultado():
        return
    res = state.resultado()
    gs = st.session_state.get("gargalos") or []
    if not gs:
        st.success("Nenhum gargalo relevante pelas regras de análise.")
        return
    validados = any(g.impacto for g in gs)
    c1, c2, c3 = st.columns([1.2, 1, 2])
    rep = c2.number_input("Replicações por validação", 1, 10, 1, help="Mais replicações reduzem o efeito da aleatoriedade.")
    if c1.button("🧪 Validar recomendações por simulação" if not validados else "🔁 Revalidar recomendações", type="primary",
                 use_container_width=True):
        barra = st.progress(0.0)
        validar_recomendacoes(res, gs, int(rep), progresso=lambda i, n, s: barra.progress(i / max(n, 1), f"Simulando: {s}"))
        barra.empty()
        st.rerun()
    c3.caption("Cada recomendação com cenário de validação é testada em uma nova simulação com a mesma semente. "
               "Custos de tempo parado já estão no custo total — a consequência financeira mostra quanto dele foi tempo improdutivo.")

    resumo = pd.DataFrame([{"Severidade": g.severidade, "Gargalo": g.titulo, "Horas": g.duracao_h, "Ocorrências": g.frequencia,
                            "R$ associado": g.consequencia_rs,
                            "Validação": AVALIACOES[g.impacto["avaliacao"]].split(":")[0] if g.impacto else "—"} for g in gs])
    st.dataframe(resumo, use_container_width=True, hide_index=True,
                 column_config={"Horas": st.column_config.NumberColumn(format="%.1f"),
                                "R$ associado": st.column_config.NumberColumn(format="R$ %.2f")})

    for i, g in enumerate(gs, 1):
        with st.container(border=True):
            st.markdown(f"{severidade(g.severidade)} &nbsp; **{i}. {g.titulo}**", unsafe_allow_html=True)
            a, b = st.columns([1.5, 1])
            with a:
                st.markdown(md(f"**Evidência observada na simulação:** {g.evidencia}"))
                st.markdown(f"**Recursos afetados:** {', '.join(g.recursos) or '—'}")
                st.markdown(md(f"**Recomendação:** {g.recomendacao}"))
            with b:
                m1, m2, m3 = st.columns(3)
                m1.metric("Duração", f"{num(g.duracao_h, 1)} h")
                m2.metric("Frequência", f"{g.frequencia}")
                m3.metric("Volume", f"{num(g.consequencia_volume_t, 1)} t")
                st.markdown(md(f"**Consequência financeira estimada:** {brl(g.consequencia_rs)}"))
                formula(g.formula_rs)
            if g.impacto:
                imp = g.impacto
                linhas = []
                for m, rot in [("duracao_h", "Duração (h)"), ("custo_total", "Custo total (R$)"), ("custo_por_t", "Custo por t (R$/t)"),
                               ("t_entregues", "t entregues"), ("espera_colh_caminhao_h", "Colheitadeiras aguardando (h)"),
                               ("fila_descarga_h", "Fila de descarga (h)")]:
                    v = imp[m]
                    linhas.append({"Indicador": rot, "Atual": v["base"], "Com a recomendação": v["novo"], "Diferença": v["delta"],
                                   "Alvo": "◀" if m == imp.get("metrica_alvo") else ""})
                st.markdown(md(f"**Impacto validado por nova simulação** — {imp['descricao']} ({imp['replicacoes']} replicação(ões)):"))
                st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True)
                aval = imp["avaliacao"]
                (st.success if aval == "melhora" else st.warning if aval == "trade_off" else st.error)(AVALIACOES[aval])
            elif g.validacao is not None:
                st.caption(f"Validação disponível: {g.validacao.descrever()} — clique em 'Validar recomendações'.")
            else:
                st.caption("Sem cenário de validação automática para este item (fator não controlável ou recomendação qualitativa).")

    st.download_button("⬇ Gargalos (CSV)", exportar_csv(gargalos_df(gs)), "gargalos.csv", mime="text/csv")
