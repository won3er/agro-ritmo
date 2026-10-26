"""Estrutura de resultados de uma simulação (DataFrames prontos para análise e exportação)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

from ..domain.models import OperationConfig
from ..domain.units import dia_de, formatar_relogio

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Simulador
    from .records import Segmento


@dataclass
class SimulationResult:
    config: OperationConfig
    eventos: pd.DataFrame
    segmentos: pd.DataFrame
    cargas: pd.DataFrame
    talhoes: pd.DataFrame
    colheitadeiras: pd.DataFrame
    caminhoes: pd.DataFrame
    t_fim: float
    t_inicio: float
    concluida: bool
    horizonte_min: float
    colhido_t: float
    entregue_t: float
    em_tanques_t: float
    em_caminhoes_t: float
    janelas: dict[str, Any] = field(default_factory=dict)
    tempo_execucao_s: float = 0.0

    @property
    def semente(self) -> int:
        return self.config.simulacao.semente

    @property
    def duracao_h(self) -> float:
        return (self.t_fim - self.t_inicio) / 60.0

    @classmethod
    def build(cls, sim: "Simulador", segs: list["Segmento"], t_ref: float, elapsed: float) -> "SimulationResult":
        cfg = sim.cfg
        ev = pd.DataFrame(sim.log.eventos, columns=["t_min", "tipo", "recurso", "categoria", "talhao", "carga", "qtd_t", "detalhe"])
        ev = ev.sort_values("t_min", kind="stable").reset_index(drop=True)
        ev.insert(1, "relogio", ev["t_min"].map(formatar_relogio))
        ev.insert(2, "dia", ev["t_min"].map(dia_de))

        sg = pd.DataFrame([s.__dict__ for s in segs],
                          columns=["recurso", "tipo", "estado", "inicio", "fim", "talhao", "carga", "origem", "destino", "carga_t",
                                   "colheitadeira"])
        sg["duracao_min"] = sg["fim"] - sg["inicio"]
        sg = sg.sort_values(["recurso", "inicio"], kind="stable").reset_index(drop=True)

        linhas = []
        for c in sim.cargas:
            linhas.append({
                "carga": c.id, "caminhao": c.caminhao, "tipo_caminhao": c.tipo_caminhao, "capacidade_t": c.capacidade_t,
                "quantidade_t": c.quantidade_t, "talhao_origem": c.talhao_origem, "distancia_km": c.distancia_km,
                "por_talhao": json.dumps({k: round(v, 4) for k, v in c.por_talhao.items()}),
                "por_colheitadeira": json.dumps({k: round(v, 4) for k, v in c.por_colheitadeira.items()}),
                "t_inicio_carregamento": c.t_inicio_carregamento, "t_saida_campo": c.t_saida_campo,
                "t_chegada_unidade": c.t_chegada_unidade, "t_inicio_descarga": c.t_inicio_descarga,
                "t_fim_descarga": c.t_fim_descarga, "status": c.status,
            })
        cg = pd.DataFrame(linhas, columns=[
            "carga", "caminhao", "tipo_caminhao", "capacidade_t", "quantidade_t", "talhao_origem", "distancia_km",
            "por_talhao", "por_colheitadeira", "t_inicio_carregamento", "t_saida_campo", "t_chegada_unidade",
            "t_inicio_descarga", "t_fim_descarga", "status"])
        if len(cg):
            cg["espera_fila_min"] = cg["t_inicio_descarga"] - cg["t_chegada_unidade"]
            cg["tempo_carregamento_min"] = cg["t_saida_campo"] - cg["t_inicio_carregamento"]
            cg["ocupacao_pct"] = cg["quantidade_t"] / cg["capacidade_t"] * 100
        else:
            cg["espera_fila_min"] = []
            cg["tempo_carregamento_min"] = []
            cg["ocupacao_pct"] = []

        tl = pd.DataFrame([{
            "talhao": f.id, "nome": f.talhao.nome, "area_ha": f.talhao.area_ha, "area_colhida_ha": f.area_colhida,
            "produtividade_sc_ha": f.talhao.produtividade_sc_ha, "t_ha": f.t_ha,
            "t_previstas": f.talhao.area_ha * f.t_ha, "t_colhidas": f.t_colhidas, "prioridade": f.talhao.prioridade,
            "distancia_km": f.talhao.distancia_km, "disponivel_a_partir_dia": f.talhao.disponivel_a_partir_dia,
            "inicio_min": f.inicio, "fim_min": f.fim,
        } for f in sim.talhoes.values()])

        ch = pd.DataFrame([{
            "colheitadeira": h.id, "nome": h.spec.nome, "horas_colheita": h.horas_colheita,
            "horas_deslocamento": h.horas_deslocamento, "km_deslocamento": h.km_deslocamento,
            "tanque_final_t": h.tanque, "concluida": h.concluida and not h.parado_horizonte,
        } for h in sim.colheitadeiras])

        cm = pd.DataFrame([{
            "caminhao": tk.id, "tipo": tk.spec.id, "capacidade_t": tk.cap, "viagens": tk.viagens,
            "km_carregado": tk.km_carregado, "km_vazio": tk.km_vazio, "carga_final_t": tk.carga_t,
            "dedicado_a": tk.dedicado_a or "",
        } for tk in sim.caminhoes])

        colhido = float(tl["t_colhidas"].sum())
        em_tanques = float(sum(h.tanque for h in sim.colheitadeiras))
        em_caminhoes = float(sum(tk.carga_t for tk in sim.caminhoes))
        colh = sg[(sg["estado"] == "colhendo")]
        t_inicio = float(colh["inicio"].min()) if len(colh) else 0.0

        cal = sim.cal
        janelas = {
            "turno_colheita": cal.turno_colheita,
            "jornada_caminhoes": cal.jornada_caminhoes.intervals,
            "unidade": cal.unidade.intervals,
            "chuvas": cal.chuvas,
            "bloqueio_clima": cal.bloqueio_clima,
            "colheitadeiras": {c.id: cal.janelas_colheitadeira(c.id).intervals for c in cfg.colheitadeiras},
        }
        return cls(
            config=cfg, eventos=ev, segmentos=sg, cargas=cg, talhoes=tl, colheitadeiras=ch, caminhoes=cm,
            t_fim=t_ref, t_inicio=t_inicio, concluida=sim.t_fim is not None, horizonte_min=sim.horizonte,
            colhido_t=colhido, entregue_t=float(sim.entregue_t), em_tanques_t=em_tanques, em_caminhoes_t=em_caminhoes,
            janelas=janelas, tempo_execucao_s=elapsed,
        )
