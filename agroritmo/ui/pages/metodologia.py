"""Metodologia (renderiza docs/MODELO.md)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ..widgets import cabecalho

DOC = Path(__file__).resolve().parents[3] / "docs" / "MODELO.md"


def render() -> None:
    cabecalho("Metodologia", "Como o AgroRitmo modela, calcula e otimiza — e o que ele não faz.")
    if DOC.exists():
        st.markdown(DOC.read_text(encoding="utf-8"))
    else:
        st.warning("docs/MODELO.md não encontrado.")
