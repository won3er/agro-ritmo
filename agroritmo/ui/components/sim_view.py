"""Simulador visual: reprodução esquemática dos estados produzidos pelo motor de eventos discretos.

Nada é animado "por efeito": a posição e a cor de cada máquina em um instante t são obtidas do
segmento de estado registrado pelo simulador que contém t. Caminhões em viagem são interpolados
entre origem e destino proporcionalmente ao tempo decorrido do próprio segmento de viagem.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ...analytics.kpis import serie_temporal
from ...domain.units import formatar_relogio
from ...simulation.records import ROTULOS_ESTADO
from ...simulation.results import SimulationResult
from ...theme import CORES_ESTADO

EVENTOS_TEXTO = {
    "TALHAO_INICIO": "inicia colheita do talhão",
    "TALHAO_CONCLUIDO": "talhão concluído",
    "ESPERA_CAMINHAO_INICIO": "colheitadeira parada aguardando caminhão",
    "ESPERA_CAMINHAO_FIM": "caminhão chegou — colheitadeira retoma",
    "FALHA": "falha mecânica",
    "FALHA_INFORMADA": "parada por falha informada",
    "REPARO_CONCLUIDO": "reparo concluído",
    "PARADA_CLIMA": "parada por chuva/secagem",
    "SAIDA_CAMPO": "sai carregado do campo",
    "CHEGADA_UNIDADE": "chega à unidade",
    "INICIO_DESCARGA": "inicia descarga",
    "FIM_DESCARGA": "descarga concluída",
    "DESLOCAMENTO_INICIO": "desloca para outro talhão",
    "SEM_TALHAO_LIBERADO": "sem talhão liberado — aguardando",
    "COLHEITADEIRA_CONCLUIDA": "colheitadeira concluiu seus talhões",
    "COLHEITADEIRA_FIM_HORIZONTE": "janela encerrada",
    "OPERACAO_CONCLUIDA": "OPERAÇÃO CONCLUÍDA",
    "CAMINHAO_CHEGA_CAMPO": "posiciona no campo",
}


def _r(v: float) -> float:
    return round(float(v), 2)


def construir_payload(res: SimulationResult) -> dict:
    cfg = res.config
    sg = res.segmentos
    ev = res.eventos
    estados = list(CORES_ESTADO)
    idx = {e: i for i, e in enumerate(estados)}

    # posições esquemáticas dos talhões (normalizadas)
    xs = np.array([t.x_km for t in cfg.talhoes], dtype=float)
    ys = np.array([t.y_km for t in cfg.talhoes], dtype=float)
    if np.ptp(xs) < 1e-9 and np.ptp(ys) < 1e-9:
        n = len(cfg.talhoes)
        cols = math.ceil(math.sqrt(n))
        xs = np.array([i % cols for i in range(n)], dtype=float)
        ys = np.array([i // cols for i in range(n)], dtype=float)
    nx = (xs - xs.min()) / (np.ptp(xs) or 1)
    ny = (ys - ys.min()) / (np.ptp(ys) or 1)
    tha = dict(zip(res.talhoes["talhao"], res.talhoes["t_ha"]))
    campos = []
    for t, x, y in zip(cfg.talhoes, nx, ny):
        e = ev[(ev["tipo"] == "COLHEITA") & (ev["talhao"] == t.id)]
        prog = [[_r(a), round(float(b), 3)] for a, b in zip(e["t_min"], (e["qtd_t"] / tha[t.id]).cumsum())]
        campos.append({"id": t.id, "nome": t.nome, "area": t.area_ha, "x": float(x), "y": float(1 - y), "dist": t.distancia_km,
                       "prio": t.prioridade, "lib": (t.disponivel_a_partir_dia - 1) * 1440, "prog": prog})

    def segs_de(rec: str) -> list:
        d = sg[sg["recurso"] == rec].sort_values("inicio")
        return [[_r(a), _r(b), idx.get(e, 0), tl or "", o or "", de or "", round(float(c or 0), 2), h or ""]
                for a, b, e, tl, o, de, c, h in zip(d["inicio"], d["fim"], d["estado"], d["talhao"], d["origem"], d["destino"],
                                                    d["carga_t"], d["colheitadeira"])]

    # nível do tanque e carga dos caminhões a partir dos eventos
    carga_cam = dict(zip(res.cargas["carga"], res.cargas["caminhao"]))
    tanques: dict[str, list] = {c.id: [[0, 0]] for c in cfg.colheitadeiras}
    nivel = {c.id: 0.0 for c in cfg.colheitadeiras}
    cargas: dict[str, list] = {cid: [[0, 0]] for cid, _ in cfg.caminhoes_expandidos()}
    nivel_c = {cid: 0.0 for cid, _ in cfg.caminhoes_expandidos()}
    for t, tipo, rec, cg, q in zip(ev["t_min"], ev["tipo"], ev["recurso"], ev["carga"], ev["qtd_t"]):
        if tipo == "COLHEITA":
            nivel[rec] += q
            tanques[rec].append([_r(t), round(nivel[rec], 2)])
        elif tipo == "TRANSBORDO":
            nivel[rec] = max(0.0, nivel[rec] - q)
            tanques[rec].append([_r(t), round(nivel[rec], 2)])
            cam = carga_cam.get(cg)
            if cam:
                nivel_c[cam] += q
                cargas[cam].append([_r(t), round(nivel_c[cam], 2)])
        elif tipo == "FIM_DESCARGA":
            nivel_c[rec] = 0.0
            cargas[rec].append([_r(t), 0])

    colh = [{"id": c.id, "cap": c.capacidade_tanque_t, "segs": segs_de(c.id), "tanque": tanques[c.id]} for c in cfg.colheitadeiras]
    cams = [{"id": cid, "cap": g.capacidade_t, "grupo": g.id, "segs": segs_de(cid), "carga": cargas[cid]}
            for cid, g in cfg.caminhoes_expandidos()]

    serie = serie_temporal(res, 5.0)
    s = {k: [round(float(v), 2) for v in serie[c]] for k, c in [
        ("colhido", "colhido_acum_t"), ("entregue", "entregue_acum_t"), ("tanques", "em_tanques_t"),
        ("campo", "em_caminhoes_campo_t"), ("transito", "em_transito_t"), ("fila_t", "na_fila_t"),
        ("fila_n", "n_fila_unidade"), ("colh_aguard", "n_colh_aguardando"), ("cam_aguard", "n_aguardando_campo")]}
    eventos = []
    for t, tipo, rec, tl, cg, q in zip(ev["t_min"], ev["tipo"], ev["recurso"], ev["talhao"], ev["carga"], ev["qtd_t"]):
        if tipo in ("COLHEITA", "TRANSBORDO", "INICIO_DESCARGA", "CAMINHAO_CHEGA_CAMPO", "ESPERA_CAMINHAO_FIM", "DESLOCAMENTO_FIM"):
            continue
        txt = EVENTOS_TEXTO.get(tipo, tipo.lower())
        extra = []
        if tl:
            extra.append(tl)
        if cg:
            extra.append(cg)
        if q and tipo in ("SAIDA_CAMPO", "CHEGADA_UNIDADE", "FIM_DESCARGA", "TALHAO_CONCLUIDO"):
            extra.append(f"{q:.1f} t")
        eventos.append([_r(t), tipo, rec or "", txt + (" · " + " · ".join(extra) if extra else "")])
    r = cfg.recebimento
    return {
        "estados": [{"id": e, "cor": CORES_ESTADO[e], "rotulo": ROTULOS_ESTADO.get(e, e)} for e in estados],
        "campos": campos, "colheitadeiras": colh, "caminhoes": cams,
        "unidade": {"nome": r.nome, "moegas": r.n_moegas, "cap": r.capacidade_t_h, "janelas": res.janelas["unidade"]},
        "turno": res.janelas["turno_colheita"], "jornada": res.janelas["jornada_caminhoes"], "chuvas": res.janelas["chuvas"],
        "bloqueio": res.janelas["bloqueio_clima"], "serie": s, "passo": 5.0, "eventos": eventos,
        "t_inicio": _r(res.t_inicio), "t_fim": _r(res.t_fim), "area_total": cfg.area_total_ha,
        "prevista": cfg.producao_prevista_t, "concluida": res.concluida,
        "relogio_fim": formatar_relogio(res.t_fim),
    }


_TEMPLATE = (Path(__file__).parent / "sim_view.html").read_text(encoding="utf-8")


def html_simulador(res: SimulationResult, altura: int = 700) -> str:
    payload = json.dumps(construir_payload(res), separators=(",", ":"))
    return _TEMPLATE.replace("__PAYLOAD__", payload).replace("__ALTURA__", str(altura))
