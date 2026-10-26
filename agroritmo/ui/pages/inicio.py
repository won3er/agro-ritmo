"""Página inicial com demonstração guiada de ponta a ponta."""
from __future__ import annotations

import streamlit as st

from ...analytics import validar_recomendacoes
from ...domain.defaults import EXEMPLOS, exemplo_soja
from ...domain.units import brl, formatar_duracao, num
from ...optimization import dimensionar_frota
from ...scenarios import cenarios_padrao, comparar
from .. import state
from ..nav import pagina
from ..widgets import cabecalho, md

PASSOS = [
    ("1", "Configure a operação", "Talhões, colheitadeiras, caminhões, recebimento, turnos, custos, clima.", "operacao"),
    ("2", "Simule", "Motor de eventos discretos com reprodução visual de cada máquina.", "simulacao"),
    ("3", "Leia o painel", "Indicadores medidos, calculados e estimados — sempre identificados.", "painel"),
    ("4", "Encontre gargalos", "Evidência, fórmula do impacto e recomendação validada por nova simulação.", "gargalos"),
    ("5", "Compare cenários", "Lado a lado, com replicações e análise de sensibilidade.", "cenarios"),
    ("6", "Otimize", "OR-Tools CP-SAT para frota, distribuição, sequência; busca simulada para recebimento.", "otimizacao"),
    ("7", "Calibre e reporte", "Observações reais, calibração, PDF/Excel/CSV reproduzíveis.", "calibracao"),
]


def render() -> None:
    cabecalho("AgroRitmo", "Plataforma de inteligência operacional para colheita e transporte de grãos")
    st.markdown("#### Como organizar máquinas, caminhões, horários e recebimento para colher e transportar mais grãos, "
                "com menos ociosidade, menor custo e sem gargalos?")
    st.caption("O AgroRitmo representa a operação do talhão até a unidade de recebimento, simula o que acontece minuto a minuto, "
               "identifica onde o fluxo trava e testa alternativas antes de mobilizar recursos.")

    cols = st.columns(len(PASSOS))
    for c, (n, t, d, pg) in zip(cols, PASSOS):
        with c:
            st.markdown(f'<div class="ar-step"><div class="n">PASSO {n}</div><div class="t">{t}</div><div class="d">{d}</div></div>',
                        unsafe_allow_html=True)
            st.page_link(pagina(pg), label="Abrir", icon="➡️")

    st.divider()
    esq, dir_ = st.columns([1.15, 1])
    with esq:
        st.subheader("Demonstração guiada")
        st.markdown("Executa o fluxo completo sobre um **cenário sintético de exemplo** (soja, 1.120 ha, 6 talhões, 3 colheitadeiras, "
                    "6 caminhões): simulação → gargalos com validação → 12 cenários comparados → dimensionamento ótimo da frota.")
        st.caption("Os valores do exemplo são ilustrativos e estão marcados como tal em todas as telas e relatórios.")
        exemplo = st.selectbox("Cenário de exemplo", list(EXEMPLOS))
        if st.button("▶ Executar demonstração completa", type="primary", use_container_width=True):
            barra = st.progress(0.0, "Carregando cenário de exemplo...")
            cfg = EXEMPLOS[exemplo]()
            state.definir_cfg(cfg)
            barra.progress(0.1, "Simulando a operação...")
            res = state.executar()
            barra.progress(0.25, "Validando recomendações dos gargalos com novas simulações...")
            validar_recomendacoes(res, st.session_state.gargalos)
            barra.progress(0.45, "Comparando cenários...")
            st.session_state.comparacao = comparar(cfg, cenarios_padrao(cfg), 1, "custo_por_t")
            barra.progress(0.75, "Otimizando o tamanho da frota (CP-SAT + simulação)...")
            st.session_state.otim_frota = dimensionar_frota(cfg)
            barra.progress(1.0, "Pronto.")
            st.session_state.demo_ok = True
            st.rerun()
        if st.session_state.get("demo_ok") and state.resultado() is not None:
            res = state.resultado()
            k = state.kpis_atuais()
            st.success("Demonstração executada. Resumo:")
            st.markdown(md(
                f"- **Simulação:** {num(res.entregue_t, 0)} t entregues em {formatar_duracao(res.duracao_h * 60)}, "
                f"{brl(k['custo_total'])} ({brl(k['custo_por_t'])}/t).\n"
                f"- **Principal gargalo:** {st.session_state.gargalos[0].titulo if st.session_state.gargalos else '—'}.\n"
                f"- **Melhor cenário (custo/t):** {st.session_state.comparacao.melhor}.\n"
                f"- **Frota recomendada (simulada):** {st.session_state.otim_frota.recomendacao.get('caminhoes_simulado', '—')} caminhões."))
            c1, c2, c3, c4 = st.columns(4)
            c1.page_link(pagina("simulacao"), label="Ver simulação visual", icon="▶️")
            c2.page_link(pagina("painel"), label="Painel executivo", icon="📊")
            c3.page_link(pagina("gargalos"), label="Gargalos", icon="🚧")
            c4.page_link(pagina("cenarios"), label="Cenários", icon="🧭")
    with dir_:
        st.subheader("Princípios")
        st.markdown(
            "- **Nada é decorativo:** posições e estados na tela vêm dos eventos do simulador.\n"
            "- **Origem de cada número:** `MEDIDO` na simulação, `CALCULADO` por fórmula, `INFORMADO` pelo usuário, `ESTIMADO` por modelo aproximado.\n"
            "- **Sem perdas inventadas:** toda consequência financeira mostra fórmula e parâmetros.\n"
            "- **Otimização honesta:** cada resultado informa método, restrições e se é ótimo, aproximado ou heurístico.\n"
            "- **Reprodutível:** mesma configuração + mesma semente = mesmo resultado (verificado por hash).\n"
            "- **Calibrável:** compare com observações reais antes de confiar nos números.")

