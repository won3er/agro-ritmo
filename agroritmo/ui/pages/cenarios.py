"""Comparação de cenários e análise de sensibilidade."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ...reports.export import exportar_csv
from ...scenarios import OBJETIVOS, PARAMETROS, Cenario, Modificacao, aplicar, cenarios_padrao, comparar, tornado, varredura
from ...scenarios.compare import METRICAS_COMPARACAO
from .. import charts, state
from ..widgets import banner_origem, cabecalho, md, vazio

TIPOS_CUSTOM = {
    "caminhoes_extra": ("Caminhões adicionais (pode ser negativo)", "valor"),
    "colheitadeira_extra": ("Colheitadeiras adicionais", "valor"),
    "capacidade_recebimento": ("Fator de capacidade de recebimento", "valor"),
    "moegas": ("Número de moegas", "valor"),
    "fator_distancia": ("Fator de distância/tempo de transporte", "valor"),
    "disponibilidade": ("Disponibilidade mecânica (0–1)", "valor"),
    "produtividade": ("Fator de produtividade", "valor"),
    "eficiencia_campo": ("Fator de eficiência de campo", "valor"),
    "horas_colheita": ("Horas a mais no turno de colheita", "valor"),
    "chuva": ("Chuva (dia, hora, duração)", "evento"),
    "falha_equipamento": ("Falha de equipamento (recurso, dia, hora, duração)", "evento"),
    "sequencia": ("Regra de sequência", "ordem"),
}


def render() -> None:
    cfg = state.cfg()
    cabecalho("Cenários e sensibilidade", "Compare alternativas lado a lado e veja quais parâmetros mais mexem nos resultados.")
    banner_origem(cfg)
    t1, t2 = st.tabs(["Comparação de cenários", "Análise de sensibilidade"])
    with t1:
        _comparacao(cfg)
    with t2:
        _sensibilidade(cfg)


def _comparacao(cfg) -> None:
    padrao = cenarios_padrao(cfg)
    nomes = [c.nome for c in padrao]
    st.session_state.setdefault("cen_custom", [])
    a, b = st.columns([2, 1])
    sel = a.multiselect("Cenários pré-definidos", nomes, default=nomes,
                        help="Cenários marcados como condição externa (chuva, produtividade...) são testes de estresse e não concorrem ao 'melhor'.")
    with b:
        rep = st.number_input("Replicações (sementes) por cenário", 1, 20, 1, help="Com replicações, a tabela mostra média e IC 95%.")
        objetivo = st.selectbox("Objetivo para escolher o melhor", list(OBJETIVOS), format_func=OBJETIVOS.get)

    with st.expander(f"➕ Cenário personalizado ({len(st.session_state.cen_custom)} criado(s))"):
        nome = st.text_input("Nome do cenário", "Meu cenário")
        tipo = st.selectbox("Alteração", list(TIPOS_CUSTOM), format_func=lambda x: TIPOS_CUSTOM[x][0])
        kind = TIPOS_CUSTOM[tipo][1]
        mod = None
        if kind == "valor":
            val = st.number_input("Valor", value=1.0, step=0.05)
            mod = Modificacao(tipo=tipo, valor=val)
        elif kind == "evento":
            c1, c2, c3, c4 = st.columns(4)
            rec = c1.selectbox("Recurso", [c.id for c in cfg.colheitadeiras] + [cid for cid, _ in cfg.caminhoes_expandidos()]) \
                if tipo == "falha_equipamento" else None
            dia = c2.number_input("Dia", 1, cfg.janela.horizonte_dias, 2)
            hora = c3.number_input("Hora", 0.0, 23.5, 10.0, step=0.5)
            dur = c4.number_input("Duração (h)", 0.5, 240.0, 12.0)
            mod = Modificacao(tipo=tipo, recurso_id=rec, dia=dia, hora=hora, duracao_h=dur)
        else:
            mod = Modificacao(tipo=tipo, ordem=st.selectbox("Regra", ["proximidade", "prioridade", "reversa"]))
        controlavel = st.checkbox("É uma decisão gerencial (concorre ao melhor cenário)", tipo not in ("chuva", "falha_equipamento",
                                                                                                      "produtividade", "fator_distancia"))
        acum = st.session_state.setdefault("cen_mods", [])
        c1, c2, c3 = st.columns(3)
        if c1.button("Adicionar alteração"):
            acum.append(mod)
        if c2.button("Criar cenário", disabled=not acum and mod is None):
            mods = acum or [mod]
            try:
                aplicar(cfg, mods)
                st.session_state.cen_custom.append(Cenario(nome=nome, modificacoes=mods, controlavel=controlavel))
                st.session_state.cen_mods = []
                st.toast(f"Cenário '{nome}' criado.")
            except (ValidationError, ValueError) as e:
                st.error(f"Cenário inválido: {e}")
        if c3.button("Limpar personalizados"):
            st.session_state.cen_custom, st.session_state.cen_mods = [], []
        if acum:
            st.caption("Alterações acumuladas: " + "; ".join(m.descrever() for m in acum))
        for c in st.session_state.cen_custom:
            st.caption(f"• **{c.nome}** — {c.descrever()}")

    if st.button("▶ Executar comparação", type="primary"):
        cens = [c for c in padrao if c.nome in sel] + st.session_state.cen_custom
        if not any(c.nome == "Original" for c in cens):
            cens.insert(0, Cenario(nome="Original"))
        barra = st.progress(0.0)
        st.session_state.comparacao = comparar(cfg, cens, int(rep), objetivo,
                                               progresso=lambda i, n, s: barra.progress(i / n, f"Simulando cenário: {s}"))
        barra.empty()

    comp = st.session_state.get("comparacao")
    if comp is None:
        vazio("Selecione os cenários e clique em Executar comparação.")
        return
    tab = comp.tabela
    if comp.melhor:
        st.success(md(f"**Melhor cenário para o objetivo '{OBJETIVOS[comp.objetivo]}': {comp.melhor}.** {comp.justificativa}"))
    else:
        st.warning(comp.justificativa)
    cols = ["cenario", "tipo", "modificacoes"] + [m for m, _, _ in METRICAS_COMPARACAO]
    extra = [c for c in tab.columns if c.startswith("delta_")]
    fmt = {m: st.column_config.NumberColumn(r, format="%.2f") for m, r, _ in METRICAS_COMPARACAO}
    fmt["custo_total"] = st.column_config.NumberColumn("Custo total (R$)", format="R$ %.0f")
    fmt["concluida"] = st.column_config.NumberColumn("Concluída (fração)", format="%.2f")
    for d in extra:
        fmt[d] = st.column_config.NumberColumn(d.replace("delta_", "Δ ").replace("_pct", " (%)"), format="%+.1f%%")
    st.dataframe(tab[cols + extra], use_container_width=True, hide_index=True, column_config=fmt)
    if any(c.endswith("_ic95") for c in tab.columns):
        st.caption("Intervalos de confiança de 95% (meia-largura) disponíveis na exportação CSV e nas barras de erro.")
    g1, g2 = st.columns(2)
    g1.plotly_chart(charts.fronteira(tab, comp.melhor), use_container_width=True)
    g2.plotly_chart(charts.comparacao(tab, "custo_por_t", "Custo por tonelada (R$/t)", comp.melhor), use_container_width=True)
    g1, g2 = st.columns(2)
    g1.plotly_chart(charts.comparacao(tab, "duracao_h", "Duração (h)", comp.melhor), use_container_width=True)
    g2.plotly_chart(charts.comparacao(tab, "espera_colh_caminhao_h", "Colheitadeiras aguardando caminhão (h)", comp.melhor),
                    use_container_width=True)
    g1, g2 = st.columns(2)
    g1.plotly_chart(charts.comparacao(tab, "fila_descarga_h", "Fila de descarga (h)", comp.melhor), use_container_width=True)
    g2.plotly_chart(charts.comparacao(tab, "util_caminhoes", "Utilização dos caminhões (%)", comp.melhor), use_container_width=True)
    c1, c2 = st.columns([1, 2])
    c1.download_button("⬇ Comparação (CSV)", exportar_csv(tab), "comparacao_cenarios.csv", mime="text/csv")
    with c2:
        adotar = st.selectbox("Adotar um cenário de decisão como operação atual", ["—"] + [r.nome for r in comp.resultados
                                                                                        if r.cenario.controlavel and r.nome != "Original"])
        if adotar != "—" and st.button("Adotar cenário"):
            r = next(x for x in comp.resultados if x.nome == adotar)
            d = r.config.model_dump()
            d["nome"] = f"{cfg.nome} — {adotar}"[:120]
            from ...domain.models import OperationConfig
            state.definir_cfg(OperationConfig.model_validate(d))
            st.session_state.form_ver = st.session_state.get("form_ver", 0) + 1
            st.success(f"Cenário '{adotar}' adotado como operação atual. Simule novamente para atualizar o painel.")


def _sensibilidade(cfg) -> None:
    st.markdown("**Tornado** — cada parâmetro varia ± X% isoladamente; mostra a variação percentual do indicador.")
    c1, c2, c3 = st.columns(3)
    var = c1.slider("Variação (±%)", 5, 50, 20, 5) / 100
    params = c2.multiselect("Parâmetros", list(PARAMETROS), default=list(PARAMETROS), format_func=lambda p: PARAMETROS[p][0])
    rep = c3.number_input("Replicações", 1, 10, 1, key="rep_sens")
    if st.button("▶ Executar tornado", type="primary"):
        barra = st.progress(0.0)
        st.session_state.tornado = tornado(cfg, var, ("custo_por_t", "duracao_h", "custo_total"), params, int(rep),
                                           progresso=lambda i, n, s: barra.progress(i / n, s))
        barra.empty()
    td = st.session_state.get("tornado")
    if td is not None:
        g1, g2 = st.columns(2)
        g1.plotly_chart(charts.tornado(td, "custo_por_t", "custo por tonelada"), use_container_width=True)
        g2.plotly_chart(charts.tornado(td, "duracao_h", "duração"), use_container_width=True)
        with st.expander("Tabela do tornado"):
            st.dataframe(td, use_container_width=True, hide_index=True)
    st.divider()
    st.markdown("**Varredura** — um parâmetro percorre uma faixa de valores.")
    c1, c2, c3 = st.columns(3)
    p = c1.selectbox("Parâmetro", list(PARAMETROS), format_func=lambda x: PARAMETROS[x][0], key="p_varr")
    lo, hi = c2.slider("Faixa do fator", 0.3, 2.5, (0.6, 1.6), 0.1)
    n = c3.number_input("Pontos", 3, 15, 6)
    if st.button("▶ Executar varredura"):
        import numpy as np
        fatores = [round(float(x), 3) for x in np.linspace(lo, hi, int(n))]
        if p == "n_caminhoes":
            fatores = sorted({max(1, round(cfg.n_caminhoes * f)) / cfg.n_caminhoes for f in fatores})
        barra = st.progress(0.0)
        st.session_state.varredura = (p, varredura(cfg, p, fatores, progresso=lambda i, n_, s: barra.progress(i / n_, s)))
        barra.empty()
    vr = st.session_state.get("varredura")
    if vr is not None:
        p_, df = vr
        st.plotly_chart(charts.varredura(df, PARAMETROS[p_][0]), use_container_width=True)
        st.dataframe(df[["descricao", "duracao_h", "custo_total", "custo_por_t", "espera_colh_caminhao_h", "fila_descarga_h",
                         "concluida"]], use_container_width=True, hide_index=True)
