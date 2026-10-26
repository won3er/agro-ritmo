"""Referências às páginas para st.page_link / st.switch_page (identificadas pelo url_path)."""
from __future__ import annotations

import streamlit as st


def pagina(nome: str):
    from .pages import calibracao, cenarios, gargalos, metodologia, operacao, otimizacao, painel, relatorios, simulacao

    mods = {"operacao": operacao, "simulacao": simulacao, "painel": painel, "gargalos": gargalos, "cenarios": cenarios,
            "otimizacao": otimizacao, "calibracao": calibracao, "relatorios": relatorios, "metodologia": metodologia}
    return st.Page(mods[nome].render, url_path=nome)
