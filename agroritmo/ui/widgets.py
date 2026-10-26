"""Componentes visuais reutilizáveis (CSS, cartões de KPI com origem do dado, estados vazios)."""
from __future__ import annotations

import html
from typing import Optional

import streamlit as st

from ..domain.models import OrigemDado
from ..domain.units import brl, num
from ..theme import CORES_SEVERIDADE, CORES_TIPO_DADO, MARCA, ROTULO_TIPO_DADO

CSS = f"""
<style>
:root {{ --ar-verde:{MARCA['verde']}; --ar-borda:{MARCA['borda']}; --ar-painel:{MARCA['painel']}; --ar-suave:{MARCA['texto_suave']}; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.ar-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; border-bottom:1px solid var(--ar-borda);
            padding-bottom:.55rem; margin-bottom:1rem; flex-wrap:wrap; }}
.ar-head h1 {{ font-size:1.55rem; margin:0; padding:0; }}
.ar-head .ar-sub {{ color:var(--ar-suave); font-size:.88rem; margin-top:.15rem; }}
.ar-kpi {{ background:var(--ar-painel); border:1px solid var(--ar-borda); border-radius:8px; padding:.65rem .8rem .55rem;
           height:100%; min-height:92px; position:relative; }}
.ar-kpi .lbl {{ color:var(--ar-suave); font-size:.74rem; text-transform:uppercase; letter-spacing:.04em; line-height:1.15; }}
.ar-kpi .val {{ font-size:1.42rem; font-weight:650; margin-top:.2rem; font-variant-numeric: tabular-nums; }}
.ar-kpi .uni {{ font-size:.8rem; color:var(--ar-suave); margin-left:.2rem; font-weight:400; }}
.ar-kpi .det {{ font-size:.72rem; color:var(--ar-suave); margin-top:.1rem; }}
.ar-badge {{ display:inline-block; font-size:.6rem; font-weight:700; letter-spacing:.06em; padding:1px 6px; border-radius:3px;
             border:1px solid; margin-left:.25rem; vertical-align:middle; }}
.ar-kpi .ar-badge {{ position:absolute; top:.55rem; right:.6rem; }}
.ar-sev {{ display:inline-block; font-size:.66rem; font-weight:700; padding:2px 8px; border-radius:10px; color:#0E1316; }}
.ar-banner {{ border:1px solid #6b5418; background:rgba(240,167,58,.09); color:#F3D9A4; padding:.5rem .8rem; border-radius:6px;
              font-size:.86rem; margin-bottom:.8rem; }}
.ar-ok {{ border:1px solid #1f6b43; background:rgba(47,168,102,.09); color:#BFE7CF; padding:.5rem .8rem; border-radius:6px;
          font-size:.86rem; margin-bottom:.8rem; }}
.ar-vazio {{ border:1px dashed var(--ar-borda); border-radius:8px; padding:1.4rem; text-align:center; color:var(--ar-suave); }}
.ar-formula {{ font-family: ui-monospace, Consolas, monospace; font-size:.8rem; color:#BFD3DF; background:#10171c;
               border:1px solid var(--ar-borda); border-radius:5px; padding:.4rem .55rem; margin:.25rem 0 .4rem; }}
.ar-step {{ border:1px solid var(--ar-borda); border-radius:8px; padding:.7rem .85rem; background:var(--ar-painel); height:100%; }}
.ar-step .n {{ color:var(--ar-verde); font-weight:700; font-size:.78rem; letter-spacing:.06em; }}
.ar-step .t {{ font-weight:600; margin:.15rem 0 .2rem; }}
.ar-step .d {{ color:var(--ar-suave); font-size:.82rem; }}
div[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
</style>
"""


def md(s: str) -> str:
    """Escapa '$' (o Markdown do Streamlit interpreta pares de $ como LaTeX)."""
    return s.replace("$", "\\$")


def _h(s: str) -> str:
    return html.escape(s).replace("$", "&#36;")


def css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(tipo: str) -> str:
    cor = CORES_TIPO_DADO.get(tipo, "#999")
    return f'<span class="ar-badge" style="color:{cor};border-color:{cor}">{ROTULO_TIPO_DADO.get(tipo, tipo.upper())}</span>'


def cabecalho(titulo: str, subtitulo: str = "") -> None:
    st.markdown(f'<div class="ar-head"><div><h1>{html.escape(titulo)}</h1>'
                f'<div class="ar-sub">{html.escape(subtitulo)}</div></div></div>', unsafe_allow_html=True)


def kpi(rotulo: str, valor: Optional[float], unidade: str = "", tipo: str = "medido", detalhe: str = "", casas: int = 1,
        moeda: bool = False) -> None:
    if valor is None:
        txt = "—"
    elif moeda:
        txt = brl(valor)
    else:
        txt = num(valor, casas)
    st.markdown(
        f'<div class="ar-kpi" title="{_h(detalhe)}">{badge(tipo)}<div class="lbl">{_h(rotulo)}</div>'
        f'<div class="val">{_h(txt)}<span class="uni">{_h(unidade)}</span></div>'
        f'<div class="det">{_h(detalhe)}</div></div>', unsafe_allow_html=True)


def severidade(sev: str) -> str:
    rot = {"alta": "ALTA", "media": "MÉDIA", "baixa": "BAIXA"}[sev]
    return f'<span class="ar-sev" style="background:{CORES_SEVERIDADE[sev]}">{rot}</span>'


def vazio(msg: str) -> None:
    st.markdown(f'<div class="ar-vazio">{html.escape(msg)}</div>', unsafe_allow_html=True)


def banner_origem(cfg) -> None:
    if cfg.origem_dados == OrigemDado.EXEMPLO:
        st.markdown('<div class="ar-banner">⚠ <b>Cenário sintético de exemplo.</b> Os parâmetros são ilustrativos — não são médias '
                    'oficiais do setor nem dados de uma fazenda real. Edite a operação, importe seus dados ou calibre com '
                    'observações antes de usar os resultados para decisões.</div>', unsafe_allow_html=True)
    elif cfg.origem_dados == OrigemDado.CALIBRADO or any(v == OrigemDado.CALIBRADO for v in cfg.proveniencia.values()):
        st.markdown('<div class="ar-ok">Parte dos parâmetros desta operação foi calibrada a partir de observações reais. '
                    'Valide com observações independentes antes de generalizar.</div>', unsafe_allow_html=True)


def formula(txt: str) -> None:
    st.markdown(f'<div class="ar-formula">{_h(txt)}</div>', unsafe_allow_html=True)


def exigir_resultado() -> bool:
    from . import state

    if state.resultado() is None:
        vazio("Nenhuma simulação executada ainda. Vá em ▶ Simulação e execute a operação atual.")
        if st.button("Executar simulação agora", type="primary"):
            with st.spinner("Simulando..."):
                state.executar()
            st.rerun()
        return False
    if state.resultado_desatualizado():
        st.warning("A configuração da operação mudou desde a última simulação. Os números abaixo referem-se à execução anterior.")
        if st.button("Simular novamente com a configuração atual"):
            with st.spinner("Simulando..."):
                state.executar()
            st.rerun()
    return True
