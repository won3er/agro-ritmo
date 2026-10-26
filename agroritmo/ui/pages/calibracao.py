"""Observações reais, comparação simulado × observado e calibração."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ...data import METRICAS_OBSERVAVEIS, PARAMETROS_CALIBRAVEIS, calibrar, comparar_observado, importar_arquivo, modelo_csv
from ...data.calibration import tabela_parametros
from ...domain.units import num
from .. import charts, state
from ..widgets import banner_origem, cabecalho, vazio


def render() -> None:
    cfg = state.cfg()
    repo = state.repositorio()
    cabecalho("Dados reais e calibração", "Registre valores observados, compare com a simulação e calibre parâmetros.")
    banner_origem(cfg)
    st.info("Sem calibração e validação, a simulação não representa fielmente uma fazenda real. Use observações de balança, "
            "telemetria ou apontamentos de campo; reserve parte delas para validar após a calibração.")
    oid = repo.id_operacao(cfg.nome)
    if oid is None:
        st.warning("Para registrar observações, salve a operação no banco.")
        if st.button("💾 Salvar operação atual"):
            st.session_state.cfg_id = repo.salvar_operacao(cfg)
            st.rerun()
        return

    t1, t2, t3 = st.tabs(["Observações", "Simulado × observado e calibração", "Origem dos parâmetros"])
    with t1:
        with st.form("obs"):
            c1, c2, c3 = st.columns([2, 1, 1])
            metrica = c1.selectbox("Métrica observada", list(METRICAS_OBSERVAVEIS),
                                   format_func=lambda m: f"{METRICAS_OBSERVAVEIS[m]['rotulo']} ({METRICAS_OBSERVAVEIS[m]['unidade']})")
            valor = c2.number_input("Valor observado", value=0.0, step=1.0)
            data = c3.date_input("Data")
            c4, c5 = st.columns(2)
            fonte = c4.text_input("Fonte", "Apontamento de campo")
            notas = c5.text_input("Notas")
            if st.form_submit_button("Registrar observação", type="primary"):
                if valor <= 0:
                    st.error("Informe um valor positivo.")
                else:
                    repo.adicionar_observacao(oid, metrica, valor, METRICAS_OBSERVAVEIS[metrica]["unidade"], str(data), fonte, notas)
                    st.toast("Observação registrada.")
        with st.expander("Importar observações (CSV/Excel)"):
            st.download_button("Modelo observacoes.csv", modelo_csv("observacoes"), "observacoes.csv")
            arq = st.file_uploader("Arquivo de observações", type=["csv", "xlsx"])
            if arq is not None and st.button("Validar e importar observações"):
                rel = importar_arquivo(arq.getvalue(), arq.name, "observacoes")
                desconhecidas = set()
                if rel.ok:
                    for r in rel.dados.to_dict("records"):
                        if r["metrica"] not in METRICAS_OBSERVAVEIS:
                            desconhecidas.add(r["metrica"])
                            continue
                        repo.adicionar_observacao(oid, r["metrica"], r["valor"], r.get("unidade", ""), str(r.get("data", "")),
                                                  r.get("fonte", ""), r.get("notas", ""))
                    st.success(f"{len(rel.dados) - len(desconhecidas)} observação(ões) importada(s).")
                    if desconhecidas:
                        st.warning(f"Métricas desconhecidas ignoradas: {sorted(desconhecidas)}")
                else:
                    st.dataframe(rel.resumo(), hide_index=True)
        obs = repo.listar_observacoes(oid)
        if obs.empty:
            vazio("Nenhuma observação registrada para esta operação.")
        else:
            st.dataframe(obs, hide_index=True, use_container_width=True)
            rem = st.selectbox("Excluir observação", ["—"] + obs["id"].astype(str).tolist())
            if rem != "—" and st.button("Excluir"):
                repo.excluir_observacao(int(rem))
                st.rerun()

    with t2:
        res = state.resultado()
        obs = repo.listar_observacoes(oid)
        if res is None or obs.empty:
            vazio("É preciso ter uma simulação executada e ao menos uma observação registrada.")
        else:
            tol = st.slider("Tolerância (%)", 1, 50, 10)
            comp = comparar_observado(res, obs, tol)
            st.dataframe(comp, hide_index=True, use_container_width=True,
                         column_config={"erro_pct": st.column_config.NumberColumn("Erro (%)", format="%+.1f%%"),
                                        "simulado": st.column_config.NumberColumn(format="%.2f"),
                                        "observado": st.column_config.NumberColumn(format="%.2f")})
            ok = int(comp["dentro_tolerancia"].sum())
            st.caption(f"{ok} de {len(comp)} métrica(s) dentro de ±{tol}%.")
            st.divider()
            st.markdown("**Calibrar um parâmetro**")
            c1, c2 = st.columns(2)
            metricas_ok = [m for m in comp["metrica"] if m in METRICAS_OBSERVAVEIS]
            if not metricas_ok:
                return
            m = c1.selectbox("Métrica-alvo", metricas_ok, format_func=lambda x: METRICAS_OBSERVAVEIS[x]["rotulo"])
            p = c2.selectbox("Parâmetro ajustado", list(PARAMETROS_CALIBRAVEIS),
                             index=list(PARAMETROS_CALIBRAVEIS).index(METRICAS_OBSERVAVEIS[m]["parametro"]),
                             format_func=lambda x: PARAMETROS_CALIBRAVEIS[x][0])
            alvo = float(comp.set_index("metrica").loc[m, "observado"])
            if st.button("▶ Calibrar", type="primary"):
                barra = st.progress(0.0)
                st.session_state.calibracao = calibrar(cfg, m, alvo, p, progresso=lambda i, n, s: barra.progress(i / n, s))
                barra.empty()
            cal = st.session_state.get("calibracao")
            if cal is not None:
                k = st.columns(4)
                k[0].metric("Fator calibrado", num(cal.fator, 3))
                k[1].metric("Observado", num(cal.observado, 2))
                k[2].metric("Simulado antes", num(cal.simulado_antes, 2), f"{num(cal.erro_antes_pct, 1)}%", delta_color="off")
                k[3].metric("Simulado depois", num(cal.simulado_depois, 2), f"{num(cal.erro_depois_pct, 1)}%", delta_color="off")
                st.plotly_chart(charts.calibracao(cal.avaliacoes, cal.observado, METRICAS_OBSERVAVEIS[cal.metrica]["rotulo"]),
                                use_container_width=True)
                st.caption("Método: busca de seção áurea sobre um fator multiplicativo do parâmetro; cada ponto é uma simulação com a "
                           "mesma semente. A operação original é preservada; a calibrada é salva como nova operação.")
                if st.button("Salvar operação calibrada e usar como atual"):
                    nova = cal.config_calibrada
                    nid = repo.salvar_operacao(nova)
                    repo.registrar_calibracao(oid, cal.metrica, cal.parametro, cal.fator, cal.observado, cal.simulado_antes,
                                              cal.simulado_depois, nid)
                    for r in repo.listar_observacoes(oid).to_dict("records"):
                        repo.adicionar_observacao(nid, r["metrica"], r["valor"], r["unidade"], r["data"], r["fonte"], r["notas"])
                    state.definir_cfg(nova, nid)
                    st.session_state.calibracao = None
                    st.success(f"Operação '{nova.nome}' salva (id {nid}) e definida como atual.")
            hist = repo.listar_calibracoes(oid)
            if len(hist):
                with st.expander("Histórico de calibrações"):
                    st.dataframe(hist, hide_index=True, use_container_width=True)

    with t3:
        tp = tabela_parametros(cfg)
        cont = tp["origem"].value_counts()
        cols = st.columns(max(1, len(cont)))
        for c, (o, n) in zip(cols, cont.items()):
            c.metric(o.replace("_", " "), n)
        st.dataframe(tp, hide_index=True, use_container_width=True, height=420)
