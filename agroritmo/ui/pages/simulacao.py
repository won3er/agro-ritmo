"""Execução da simulação, simulador visual, linha do tempo e log de eventos."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from ...analytics import kpis_dict, calcular_kpis
from ...domain.units import formatar_duracao, formatar_relogio, num
from ...simulation import hash_resultado, simular
from ...simulation.records import ROTULOS_ESTADO
from .. import charts, state
from ..components.sim_view import EVENTOS_TEXTO, html_simulador
from ..widgets import banner_origem, cabecalho, vazio


def render() -> None:
    cfg = state.cfg()
    cabecalho("Simulação operacional", "Motor de eventos discretos (SimPy). A tela reproduz os estados registrados pelo simulador.")
    banner_origem(cfg)
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("▶ Executar simulação", type="primary", use_container_width=True):
        with st.spinner("Simulando a operação..."):
            state.executar()
    if c2.button("🔁 Repetir e verificar reprodutibilidade", use_container_width=True, disabled=state.resultado() is None):
        res = state.resultado()
        novo = simular(res.config)  # sem cache: execução independente
        h1, h2 = hash_resultado(res), hash_resultado(novo)
        if h1 == h2:
            st.success(f"Reprodutível: mesma configuração e semente {res.semente} geraram o mesmo resultado (hash {h1}).")
        else:
            st.error(f"Resultado divergente: {h1} × {h2}")
    res = state.resultado()
    if res is None:
        vazio("Execute a simulação para ver a operação em movimento.")
        return
    if state.resultado_desatualizado():
        st.warning("A configuração foi alterada depois desta simulação. Clique em Executar simulação para atualizar.")
    with c3:
        st.markdown(
            f"{'✅ **Operação concluída**' if res.concluida else '⚠️ **Não concluiu dentro da janela**'} · "
            f"início {formatar_relogio(res.t_inicio)} · fim {formatar_relogio(res.t_fim)} · duração {formatar_duracao(res.duracao_h * 60)}  \n"
            f"{num(res.entregue_t, 1)} t entregues · {num(len(res.eventos), 0)} eventos · {len(res.cargas)} cargas · "
            f"semente {res.semente} · executado em {num(res.tempo_execucao_s, 2)} s")

    components.html(html_simulador(res, 700), height=712, scrolling=False)

    tabs = st.tabs(["Linha do tempo", "Log de eventos", "Cargas", "Talhões", "Registrar execução"])
    with tabs[0]:
        f1, f2 = st.columns([1, 3])
        tipo = f1.radio("Recursos", ["Todos", "colheitadeira", "caminhao"], horizontal=False,
                        format_func=lambda x: {"Todos": "Todos", "colheitadeira": "Colheitadeiras", "caminhao": "Caminhões"}[x])
        dias = int(res.t_fim // 1440) + 1
        dia = f2.select_slider("Dia", options=["Todos"] + list(range(1, dias + 1)), value=1 if dias > 3 else "Todos")
        st.plotly_chart(charts.gantt(res, None if tipo == "Todos" else tipo, None if dia == "Todos" else int(dia)),
                        use_container_width=True)
    with tabs[1]:
        ev = res.eventos.copy()
        ev["descricao"] = ev["tipo"].map(EVENTOS_TEXTO).fillna(ev["tipo"].str.lower())
        f1, f2, f3, f4 = st.columns([2, 2, 1, 2])
        tipos = sorted(ev["tipo"].unique())
        padrao = [t for t in tipos if t not in ("COLHEITA", "TRANSBORDO")]
        sel_t = f1.multiselect("Tipos de evento", tipos, default=padrao)
        sel_r = f2.multiselect("Recursos", sorted(r for r in ev["recurso"].unique() if r))
        sel_d = f3.number_input("Dia (0 = todos)", 0, int(ev["dia"].max()), 0)
        busca = f4.text_input("Buscar no detalhe/carga/talhão")
        m = ev["tipo"].isin(sel_t)
        if sel_r:
            m &= ev["recurso"].isin(sel_r)
        if sel_d:
            m &= ev["dia"] == sel_d
        if busca:
            b = busca.lower()
            m &= (ev["detalhe"].str.lower().str.contains(b, regex=False) | ev["carga"].str.lower().str.contains(b, regex=False)
                  | ev["talhao"].str.lower().str.contains(b, regex=False))
        st.caption(f"{int(m.sum()):,} de {len(ev):,} eventos".replace(",", "."))
        st.dataframe(ev[m][["relogio", "tipo", "descricao", "recurso", "talhao", "carga", "qtd_t", "detalhe", "t_min"]],
                     use_container_width=True, hide_index=True, height=420,
                     column_config={"qtd_t": st.column_config.NumberColumn("t", format="%.2f"),
                                    "t_min": st.column_config.NumberColumn("t (min)", format="%.1f")})
    with tabs[2]:
        cg = res.cargas.copy()
        for c in ("t_saida_campo", "t_chegada_unidade", "t_inicio_descarga", "t_fim_descarga"):
            cg[c] = cg[c].map(lambda v: formatar_relogio(v) if v == v and v is not None else "")
        st.dataframe(cg[["carga", "caminhao", "talhao_origem", "quantidade_t", "ocupacao_pct", "t_saida_campo", "t_chegada_unidade",
                         "t_inicio_descarga", "t_fim_descarga", "espera_fila_min", "status", "por_talhao", "por_colheitadeira"]],
                     use_container_width=True, hide_index=True, height=420,
                     column_config={"quantidade_t": st.column_config.NumberColumn("t", format="%.2f"),
                                    "ocupacao_pct": st.column_config.ProgressColumn("Ocupação", min_value=0, max_value=100, format="%.0f%%"),
                                    "espera_fila_min": st.column_config.NumberColumn("Espera na fila (min)", format="%.1f")})
    with tabs[3]:
        tl = res.talhoes.copy()
        tl["inicio"] = tl["inicio_min"].map(lambda v: formatar_relogio(v) if v == v and v is not None else "—")
        tl["fim"] = tl["fim_min"].map(lambda v: formatar_relogio(v) if v == v and v is not None else "—")
        tl["concluido_pct"] = tl["area_colhida_ha"] / tl["area_ha"] * 100
        st.dataframe(tl[["talhao", "nome", "prioridade", "area_ha", "area_colhida_ha", "concluido_pct", "produtividade_sc_ha",
                         "t_previstas", "t_colhidas", "distancia_km", "inicio", "fim"]], use_container_width=True, hide_index=True,
                     column_config={"concluido_pct": st.column_config.ProgressColumn("Concluído", min_value=0, max_value=100, format="%.0f%%")})
    with tabs[4]:
        st.markdown("Registra configuração, semente, indicadores e hash do resultado no banco, para repetir depois e conferir.")
        nome = st.text_input("Nome do registro", f"{cfg.nome} — semente {res.semente}")
        if st.button("Registrar execução"):
            repo = state.repositorio()
            if repo.id_operacao(res.config.nome) is None:
                repo.salvar_operacao(res.config)
            eid = repo.registrar_execucao(res.config, kpis_dict(calcular_kpis(res)), hash_resultado(res), nome)
            st.success(f"Execução registrada (id {eid}, hash {hash_resultado(res)}).")
