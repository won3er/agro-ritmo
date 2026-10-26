"""Aplicação Streamlit: navegação e barra lateral."""
from __future__ import annotations

import streamlit as st

from ..domain.units import formatar_duracao, num
from . import state, widgets
from .pages import calibracao, cenarios, gargalos, inicio, metodologia, operacao, otimizacao, painel, relatorios, simulacao


def main() -> None:
    st.set_page_config(page_title="AgroRitmo", page_icon="🌾", layout="wide", initial_sidebar_state="expanded")
    state.init()
    widgets.css()
    paginas = {
        "": [st.Page(inicio.render, title="Início e demonstração", icon="🏁", url_path="inicio", default=True)],
        "Operação": [
            st.Page(operacao.render, title="Configurar operação", icon="⚙️", url_path="operacao"),
            st.Page(simulacao.render, title="Simulação", icon="▶️", url_path="simulacao"),
        ],
        "Análise": [
            st.Page(painel.render, title="Painel executivo", icon="📊", url_path="painel"),
            st.Page(gargalos.render, title="Gargalos", icon="🚧", url_path="gargalos"),
        ],
        "Decisão": [
            st.Page(cenarios.render, title="Cenários e sensibilidade", icon="🧭", url_path="cenarios"),
            st.Page(otimizacao.render, title="Otimização", icon="🎯", url_path="otimizacao"),
        ],
        "Dados": [
            st.Page(calibracao.render, title="Dados reais e calibração", icon="🔬", url_path="calibracao"),
            st.Page(relatorios.render, title="Relatórios e exportação", icon="📄", url_path="relatorios"),
            st.Page(metodologia.render, title="Metodologia", icon="📘", url_path="metodologia"),
        ],
    }
    pg = st.navigation(paginas, expanded=True)
    flash = st.session_state.pop("flash", None)
    if flash:
        st.toast(flash, icon="✅")
    with st.sidebar:
        cfg = state.cfg()
        st.markdown("### 🌾 AgroRitmo")
        st.caption("Simulação e otimização de colheita e transporte de grãos")
        st.markdown(f"**Operação atual**  \n{cfg.nome}")
        st.caption(f"{cfg.crop.nome} · {num(cfg.area_total_ha, 0)} ha · {len(cfg.colheitadeiras)} colheitadeira(s) · "
                   f"{cfg.n_caminhoes} caminhão(ões) · origem: {cfg.origem_dados.value.replace('_', ' ')}")
        res = state.resultado()
        if res is not None:
            k = state.kpis_atuais()
            st.markdown("**Última simulação**")
            st.caption(f"{'✅ concluída' if res.concluida else '⚠️ não concluiu na janela'} · {formatar_duracao(res.duracao_h * 60)}  \n"
                       f"{num(res.entregue_t, 0)} t entregues · R$ {num(k.get('custo_por_t') or 0, 2)}/t")
            if state.resultado_desatualizado():
                st.warning("Configuração alterada após a simulação.", icon="⚠️")
        else:
            st.caption("Nenhuma simulação executada.")
    pg.run()
