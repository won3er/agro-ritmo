"""Estado da sessão Streamlit e execução (com cache) das simulações."""
from __future__ import annotations

import hashlib
from typing import Optional

import streamlit as st

from ..analytics import calcular_custos, calcular_kpis, identificar_gargalos, kpis_dict
from ..data.calibration import tabela_parametros
from ..data.db import Repositorio
from ..domain.defaults import exemplo_soja
from ..domain.models import OperationConfig, OrigemDado
from ..simulation import SimulationResult, simular


def cfg_hash(cfg: OperationConfig) -> str:
    return hashlib.sha1(cfg.model_dump_json().encode()).hexdigest()[:12]


@st.cache_data(show_spinner=False, max_entries=24)
def _simular_cache(cfg_json: str) -> SimulationResult:
    return simular(OperationConfig.model_validate_json(cfg_json))


def simular_cfg(cfg: OperationConfig) -> SimulationResult:
    return _simular_cache(cfg.model_dump_json())


@st.cache_resource(show_spinner=False)
def repositorio() -> Repositorio:
    return Repositorio()


def init() -> None:
    ss = st.session_state
    if "cfg" not in ss:
        ss.cfg = exemplo_soja()
        ss.cfg_id = None
    for k in ("res", "res_hash", "gargalos", "comparacao", "otim_frota", "otim_dist", "otim_seq", "otim_receb",
              "tornado", "varredura", "calibracao"):
        ss.setdefault(k, None)


def cfg() -> OperationConfig:
    return st.session_state.cfg


def definir_cfg(novo: OperationConfig, cfg_id: Optional[int] = None, limpar: bool = True) -> None:
    ss = st.session_state
    antigo = ss.get("cfg")
    if antigo is not None and antigo.nome == novo.nome:
        novo = marcar_proveniencia(antigo, novo)
    ss.cfg = novo
    if cfg_id is not None:
        ss.cfg_id = cfg_id
    if limpar:
        for k in ("res", "res_hash", "gargalos", "comparacao", "otim_frota", "otim_dist", "otim_seq", "otim_receb",
                  "tornado", "varredura"):
            ss[k] = None


def marcar_proveniencia(antigo: OperationConfig, novo: OperationConfig) -> OperationConfig:
    """Parâmetros alterados manualmente passam a ter origem 'usuario'."""
    a = tabela_parametros(antigo).set_index("parametro")["valor"].to_dict()
    n = tabela_parametros(novo).set_index("parametro")["valor"].to_dict()
    prov = dict(novo.proveniencia)
    mudou = False
    for k, v in n.items():
        if k in a and a[k] != v and novo.origem_de(k) != OrigemDado.USUARIO:
            prov[k] = OrigemDado.USUARIO
            mudou = True
    if not mudou:
        return novo
    d = novo.model_dump()
    d["proveniencia"] = {k: (v.value if hasattr(v, "value") else v) for k, v in prov.items()}
    return OperationConfig.model_validate(d)


def executar(cfg_: Optional[OperationConfig] = None) -> SimulationResult:
    c = cfg_ or cfg()
    res = simular_cfg(c)
    st.session_state.res = res
    st.session_state.res_hash = cfg_hash(c)
    st.session_state.gargalos = identificar_gargalos(res)
    return res


def resultado() -> Optional[SimulationResult]:
    return st.session_state.get("res")


def resultado_desatualizado() -> bool:
    return st.session_state.get("res") is not None and st.session_state.get("res_hash") != cfg_hash(cfg())


@st.cache_data(show_spinner=False, max_entries=24)
def kpis_cache(cfg_json: str) -> tuple[list, float]:
    res = _simular_cache(cfg_json)
    custos = calcular_custos(res)
    total = float(custos["valor"].sum())
    return calcular_kpis(res, total), total


def kpis_atuais() -> dict:
    res = resultado()
    if res is None:
        return {}
    kp, _ = kpis_cache(res.config.model_dump_json())
    return kpis_dict(kp)
