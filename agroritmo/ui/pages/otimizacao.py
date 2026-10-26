"""Otimização: frota, distribuição, sequência de talhões e capacidade de recebimento."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ...domain.models import OperationConfig
from ...domain.units import brl, num
from ...optimization import (
    OBJETIVOS_SEQ,
    buscar_capacidade_recebimento,
    dimensionar_frota,
    distribuir_frota_atual,
    otimizar_sequencia,
)
from ...scenarios import Modificacao, aplicar
from .. import charts, state
from ..charts import LAYOUT
from ..widgets import banner_origem, cabecalho, vazio


def _metodo(r) -> None:
    ot = r.status.upper()
    cor = "success" if ot.startswith("ÓTIMO") else "warning"
    getattr(st, cor)(f"**Status da solução:** {r.status}")
    with st.expander("Método, restrições e limitações", expanded=False):
        st.markdown(f"**Método:** {r.metodo}")
        st.markdown("**Restrições consideradas:**\n" + "\n".join(f"- {x}" for x in r.restricoes))
        st.markdown("**Limitações:**\n" + "\n".join(f"- {x}" for x in r.limitacoes))


def _adotar(novo: OperationConfig, msg: str) -> None:
    state.definir_cfg(novo)
    st.session_state.form_ver = st.session_state.get("form_ver", 0) + 1
    st.success(msg + " Simule novamente para atualizar painel e gargalos.")


def render() -> None:
    cfg = state.cfg()
    cabecalho("Otimização de recursos", "OR-Tools CP-SAT onde há um modelo de otimização exato; busca por simulação onde não há.")
    banner_origem(cfg)
    t1, t2, t3, t4 = st.tabs(["Tamanho da frota", "Distribuição dos caminhões", "Sequência dos talhões", "Capacidade de recebimento"])

    with t1:
        st.markdown("Quantos caminhões (e de quais grupos) minimizam o custo por tonelada — ou o tempo — respeitando a janela?")
        c1, c2, c3 = st.columns(3)
        extra = c1.number_input("Caminhões extras avaliados por grupo", 0, 20, 6)
        obj = c2.selectbox("Objetivo", ["custo_por_t", "duracao_h", "prazo_custo"],
                           format_func={"custo_por_t": "Menor custo por tonelada", "duracao_h": "Menor duração",
                                        "prazo_custo": "Menor custo/t cumprindo o prazo desejado"}.get)
        rep = c3.number_input("Replicações na validação", 1, 10, 1, key="rep_frota")
        if st.button("▶ Otimizar frota", type="primary"):
            barra = st.progress(0.0, "Resolvendo CP-SAT para cada tamanho de frota...")
            st.session_state.otim_frota = dimensionar_frota(cfg, int(extra), obj, True, int(rep),
                                                            progresso=lambda i, n, s: barra.progress(0.2 + 0.8 * i / n, s))
            barra.empty()
        r = st.session_state.get("otim_frota")
        if r is None:
            vazio("Execute a otimização da frota.")
        else:
            _metodo(r)
            rec = r.recomendacao
            m = st.columns(4)
            m[0].metric("Frota atual", f"{rec['atual']} caminhões")
            m[1].metric("Ótimo do modelo analítico", f"{rec['caminhoes_analitico']}",
                        ", ".join(f"{k}={v}" for k, v in rec["composicao_analitico"].items() if v), delta_color="off")
            if "caminhoes_simulado" in rec:
                m[2].metric("Melhor validado por simulação", f"{rec['caminhoes_simulado']}", rec["composicao_simulado"], delta_color="off")
                m[3].metric("Custo/t simulado", brl(rec["custo_por_t_simulado"]), f"{num(rec['duracao_h_simulada'], 1)} h", delta_color="off")
            st.caption(f"Acima de {rec['saturacao_k']} caminhões a vazão não aumenta no modelo analítico "
                       f"({num(rec['vazao_max_t_h'], 1)} t/h, limitada pela colheita ou pelo recebimento).")
            sim = r.detalhes.get("simulacao")
            st.plotly_chart(charts.frota(r.tabela, sim), use_container_width=True)
            a, b = st.columns(2)
            with a:
                st.markdown("**Modelo analítico (CP-SAT) — valores ESTIMADOS**")
                st.dataframe(r.tabela, hide_index=True, use_container_width=True, height=300)
            with b:
                st.markdown("**Validação por simulação — valores MEDIDOS/CALCULADOS na simulação**")
                st.dataframe(sim, hide_index=True, use_container_width=True)
            if "caminhoes_simulado" in rec and rec["caminhoes_simulado"] != rec["atual"]:
                if st.button(f"Adotar frota de {rec['caminhoes_simulado']} caminhões ({rec['composicao_simulado']})"):
                    comp = dict(p.split("=") for p in rec["composicao_simulado"].split(", ") if "=" in p)
                    comp = {g.id: int(comp.get(g.id, 0)) for g in cfg.frota}
                    _adotar(aplicar(cfg, [Modificacao(tipo="composicao_frota", alocacao=comp)]), "Frota otimizada adotada.")

    with t2:
        st.markdown("Como distribuir os caminhões existentes entre as colheitadeiras (alocação dedicada) para maximizar a vazão.")
        if st.button("▶ Otimizar distribuição", type="primary"):
            with st.spinner("Resolvendo e validando..."):
                st.session_state.otim_dist = distribuir_frota_atual(cfg, True)
        r = st.session_state.get("otim_dist")
        if r is None:
            vazio("Execute a otimização da distribuição.")
        else:
            _metodo(r)
            rec = r.recomendacao
            st.markdown("**Alocação recomendada:** " + ", ".join(f"{h}: {n} caminhão(ões)" for h, n in rec["alocacao"].items())
                        + f" — vazão estimada {num(rec['vazao_t_h'], 1)} t/h")
            st.dataframe(r.tabela, hide_index=True, use_container_width=True)
            if "simulacao" in r.detalhes:
                st.markdown("**Validação por simulação: despacho dinâmico × alocação dedicada otimizada**")
                st.dataframe(r.detalhes["simulacao"], hide_index=True, use_container_width=True)
                sim = r.detalhes["simulacao"]
                melhor = sim.sort_values("custo_por_t").iloc[0]["cenario"]
                st.caption(f"Na simulação, o menor custo por tonelada foi obtido com: **{melhor}**.")
            if st.button("Adotar alocação dedicada otimizada"):
                _adotar(aplicar(cfg, [Modificacao(tipo="alocacao", alocacao=rec["alocacao"], ordem=rec["mapa_caminhoes"])]),
                        "Alocação dedicada adotada.")

    with t3:
        st.markdown("Qual colheitadeira colhe cada talhão, e em que ordem, respeitando prioridades, deslocamentos e liberação dos talhões.")
        c1, c2 = st.columns(2)
        obj = c1.selectbox("Objetivo do sequenciamento", list(OBJETIVOS_SEQ), format_func=lambda k: OBJETIVOS_SEQ[k][2])
        lim = c2.number_input("Tempo limite do solver (s)", 1, 120, 10)
        if st.button("▶ Otimizar sequência", type="primary"):
            with st.spinner("Resolvendo CP-SAT e validando por simulação..."):
                st.session_state.otim_seq = otimizar_sequencia(cfg, obj, float(lim), True)
        r = st.session_state.get("otim_seq")
        if r is None:
            vazio("Execute a otimização da sequência.")
        else:
            _metodo(r)
            rec = r.recomendacao
            m = st.columns(3)
            m[0].metric("Objetivo CP-SAT", num(rec["objetivo"] or 0, 0))
            m[1].metric("Objetivo da regra por prioridade", num(rec["objetivo_guloso"], 0))
            m[2].metric("Melhoria sobre a regra", f"{num(rec['melhoria_pct'] or 0, 1)}%")
            if (rec["melhoria_pct"] or 0) < 0.05:
                st.info("A regra atual (prioridade + próxima máquina livre) já é ótima para esta instância — o CP-SAT prova que não há "
                        "sequência melhor no modelo de sequenciamento.")
            tab = r.tabela.copy()
            if len(tab):
                fig = go.Figure(go.Bar(
                    y=tab["colheitadeira"], x=tab["duracao_h"], base=tab["inicio_h_efetivas"], orientation="h", text=tab["talhao"],
                    marker_color=[{1: "#2FA866", 2: "#38B6C4", 3: "#F0A73A", 4: "#7B93C4", 5: "#6F8396"}[p] for p in tab["prioridade"]],
                    hovertemplate="%{text}: %{base:.1f} h → %{x:.1f} h de colheita<extra></extra>"))
                fig.update_yaxes(autorange="reversed")
                fig.update_xaxes(title="horas efetivas de colheita (sem noites, chuva ou esperas) — cor = prioridade")
                fig.update_layout(**LAYOUT, height=260, title="Plano de sequência por colheitadeira")
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(r.tabela, hide_index=True, use_container_width=True)
            if "simulacao" in r.detalhes:
                st.markdown("**Validação por simulação**")
                st.dataframe(r.detalhes["simulacao"], hide_index=True, use_container_width=True)
                st.caption(f"Término médio ponderado por prioridade: regra atual {num(r.detalhes['termino_ponderado_h_base'], 1)} h × "
                           f"plano {num(r.detalhes['termino_ponderado_h_otimizado'], 1)} h (relógio da simulação).")
            if rec["plano"] and st.button("Adotar plano de sequência"):
                _adotar(aplicar(cfg, [Modificacao(tipo="sequencia", ordem=rec["plano"])]), "Plano de sequência adotado.")

    with t4:
        st.markdown("Menor capacidade de recebimento que mantém a espera média por carga abaixo de uma meta.")
        c1, c2 = st.columns(2)
        meta = c1.slider("Espera média máxima por carga (min)", 2, 60, 10)
        rep = c2.number_input("Replicações", 1, 10, 1, key="rep_rec")
        if st.button("▶ Buscar capacidade", type="primary"):
            with st.spinner("Bisseção por simulação..."):
                st.session_state.otim_receb = buscar_capacidade_recebimento(cfg, float(meta), replicacoes=int(rep))
        r = st.session_state.get("otim_receb")
        if r is None:
            vazio("Execute a busca de capacidade de recebimento.")
        else:
            _metodo(r)
            rec = r.recomendacao
            m = st.columns(4)
            m[0].metric("Capacidade atual", f"{num(rec['capacidade_atual_t_h'], 0)} t/h")
            m[1].metric("Recomendada (simulação)", f"{num(rec['capacidade_t_h'], 0)} t/h",
                        f"espera {num(rec['fila_media_min'], 1)} min", delta_color="off")
            m[2].metric("Pico de colheita (estimado)", f"{num(rec['demanda_pico_t_h'], 1)} t/h")
            m[3].metric("Mínimo diário (estimado)", f"{num(rec['capacidade_minima_diaria_t_h'], 1)} t/h")
            st.caption("Estimativas analíticas: " + rec["formula"])
            fig = px.line(r.tabela, x="capacidade_t_h", y="fila_media_min", markers=True)
            fig.add_hline(y=meta, line_dash="dash", line_color="#F0A73A", annotation_text="meta")
            fig.update_layout(**LAYOUT, height=300, title="Espera média por carga × capacidade (pontos simulados)")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(r.tabela, hide_index=True, use_container_width=True)
