"""Relatórios (PDF), exportações (Excel/CSV) e reprodutibilidade."""
from __future__ import annotations

import streamlit as st

from ...reports import PacoteRelatorio, config_json, exportar_csv, exportar_csv_zip, exportar_excel, gerar_pdf
from ...simulation import hash_resultado, simular
from .. import state
from ..widgets import banner_origem, cabecalho, exigir_resultado, vazio


def render() -> None:
    cfg = state.cfg()
    cabecalho("Relatórios e exportação", "Relatório para gestores, dados completos para análise e registro para reprodução.")
    banner_origem(cfg)
    if not exigir_resultado():
        return
    res = state.resultado()
    comp = st.session_state.get("comparacao")
    c1, c2 = st.columns(2)
    incl_comp = c1.checkbox("Incluir comparação de cenários", comp is not None, disabled=comp is None)
    incl_val = c2.checkbox("Incluir validação das recomendações", any(g.impacto for g in (st.session_state.gargalos or [])))
    if incl_val and not any(g.impacto for g in (st.session_state.gargalos or [])):
        st.caption("As recomendações ainda não foram validadas — serão validadas ao gerar o relatório.")

    if st.button("⚙ Gerar arquivos", type="primary"):
        with st.spinner("Montando relatório..."):
            gs = st.session_state.gargalos or []
            if incl_val and not any(g.impacto for g in gs):
                from ...analytics import validar_recomendacoes
                validar_recomendacoes(res, gs)
            otim = {}
            if incl_comp and comp is not None:
                otim["justificativa"] = f"Melhor cenário: {comp.melhor}. {comp.justificativa}"
            of = st.session_state.get("otim_frota")
            if of is not None:
                otim["frota_analitico"] = of.tabela
                otim["frota_simulado"] = of.detalhes.get("simulacao")
            pacote = PacoteRelatorio.montar(res, gs, comp.tabela if (incl_comp and comp is not None) else None, otim)
            st.session_state.arquivos = {
                "pdf": gerar_pdf(pacote), "xlsx": exportar_excel(pacote), "zip": exportar_csv_zip(pacote),
                "json": config_json(pacote), "eventos": exportar_csv(res.eventos), "cargas": exportar_csv(res.cargas),
                "hash": pacote.hash,
            }
    arq = st.session_state.get("arquivos")
    if arq:
        base = cfg.nome[:40].replace(" ", "_")
        st.success(f"Arquivos gerados (hash do resultado {arq['hash']}).")
        a, b, c = st.columns(3)
        a.download_button("📄 Relatório PDF", arq["pdf"], f"relatorio_{base}.pdf", "application/pdf", use_container_width=True, type="primary")
        b.download_button("📊 Excel completo", arq["xlsx"], f"resultados_{base}.xlsx", use_container_width=True)
        c.download_button("🗂 CSV (zip)", arq["zip"], f"resultados_{base}.zip", "application/zip", use_container_width=True)
        a, b, c = st.columns(3)
        a.download_button("⚙ Configuração (JSON)", arq["json"], f"configuracao_{base}.json", "application/json", use_container_width=True)
        b.download_button("Eventos (CSV)", arq["eventos"], "eventos.csv", "text/csv", use_container_width=True)
        c.download_button("Cargas (CSV)", arq["cargas"], "cargas.csv", "text/csv", use_container_width=True)
        st.caption("O Excel contém: resumo, indicadores com origem, premissas com origem dos parâmetros, custos com fórmulas, "
                   "gargalos, utilização, talhões, cargas, eventos, estados, série temporal, configuração e cenários.")

    st.divider()
    st.subheader("Reprodutibilidade")
    st.markdown("Repita uma execução registrada com a mesma configuração e semente e confira se o resultado é idêntico (hash).")
    repo = state.repositorio()
    hist = repo.listar_execucoes()
    if hist.empty:
        vazio("Nenhuma execução registrada. Registre em ▶ Simulação → Registrar execução.")
        return
    st.dataframe(hist, hide_index=True, use_container_width=True)
    eid = st.selectbox("Execução", hist["id"].tolist(), format_func=lambda i: f"{i} · {hist.set_index('id').loc[i, 'nome']}")
    c1, c2 = st.columns(2)
    if c1.button("🔁 Reexecutar e verificar"):
        cfg_r, kpis, h = repo.carregar_execucao(int(eid))
        novo = simular(cfg_r)
        h2 = hash_resultado(novo)
        (st.success if h2 == h else st.error)(f"Hash registrado {h} · hash reexecutado {h2} — "
                                               f"{'idênticos: resultado reproduzido.' if h2 == h else 'DIFERENTES.'}")
    if c2.button("Carregar configuração desta execução"):
        cfg_r, _, _ = repo.carregar_execucao(int(eid))
        state.definir_cfg(cfg_r)
        state.executar(cfg_r)
        st.rerun()
