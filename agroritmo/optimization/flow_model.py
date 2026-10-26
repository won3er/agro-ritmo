"""Modelo analítico de fluxo em regime permanente (usado pelo otimizador de frota).

Para a colheitadeira h e um caminhão do grupo g:

* taxa efetiva de colheita (t/h), já incluindo as paradas para descarregar o tanque:
    p_h = Q_tanque / (Q_tanque / (ha/h · eficiência · t/ha) + t_descarga_tanque)
* tempo de enchimento de um caminhão:            T_ench = Q_g / p_h
* tempo de laço (sem o enchimento):              L_hg = manobra + d/v_carregado + (t_fixo + Q_g / taxa_moega) + d/v_vazio
* ciclo completo:                                C_hg = T_ench + L_hg
* vazão que um caminhão consegue escoar:         Q_g / C_hg

Limitações (explicitadas na interface): ignora filas na unidade e a variabilidade dos tempos,
usa distância média ponderada pela produção, e trata disponibilidade mecânica como fator médio.
Por isso as recomendações do modelo analítico são sempre validadas por simulação.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.models import Colheitadeira, OperationConfig, TipoCaminhao


@dataclass
class FluxoColheitadeira:
    id: str
    p_t_h: float           # taxa efetiva (t/h) com paradas de descarga do tanque
    distancia_km: float    # distância média ponderada
    t_ha: float


def distancia_media(cfg: OperationConfig, talhoes: list[str] | None = None) -> tuple[float, float]:
    kg = cfg.kg_por_saca
    ts = [t for t in cfg.talhoes if talhoes is None or t.id in talhoes]
    peso = np.array([t.area_ha * t.t_ha(kg) for t in ts])
    d = np.array([t.distancia_km for t in ts])
    area = np.array([t.area_ha for t in ts])
    if peso.sum() <= 0:
        return 0.0, 0.0
    return float((peso * d).sum() / peso.sum()), float(peso.sum() / area.sum())


def taxa_efetiva_t_h(c: Colheitadeira, t_ha: float) -> float:
    bruta = c.taxa_efetiva_ha_h * t_ha
    tempo_tanque_h = c.capacidade_tanque_t / bruta
    return c.capacidade_tanque_t / (tempo_tanque_h + c.tempo_descarga_tanque_min / 60.0)


def fluxo_colheitadeiras(cfg: OperationConfig, plano: dict[str, list[str]] | None = None) -> list[FluxoColheitadeira]:
    out = []
    for c in cfg.colheitadeiras:
        talhoes = plano.get(c.id) if plano else None
        d, tha = distancia_media(cfg, talhoes or None)
        out.append(FluxoColheitadeira(id=c.id, p_t_h=taxa_efetiva_t_h(c, tha), distancia_km=d, t_ha=tha))
    return out


def laco_min(cfg: OperationConfig, g: TipoCaminhao, d_km: float) -> float:
    r = cfg.recebimento
    descarga = r.tempo_fixo_min + g.capacidade_t / r.taxa_por_moega_t_h * 60
    return g.tempo_manobra_min + d_km / g.velocidade_carregado_km_h * 60 + descarga + d_km / g.velocidade_vazio_km_h * 60


def ciclo_min(cfg: OperationConfig, g: TipoCaminhao, f: FluxoColheitadeira) -> float:
    return g.capacidade_t / f.p_t_h * 60 + laco_min(cfg, g, f.distancia_km)


def vazao_por_caminhao_t_h(cfg: OperationConfig, g: TipoCaminhao, f: FluxoColheitadeira) -> float:
    return g.capacidade_t / ciclo_min(cfg, g, f) * 60


def caminhoes_necessarios(cfg: OperationConfig, g: TipoCaminhao, f: FluxoColheitadeira) -> float:
    """Número (fracionário) de caminhões do grupo g para a colheitadeira nunca esperar."""
    return f.p_t_h / vazao_por_caminhao_t_h(cfg, g, f)


def horas_efetivas_dia(cfg: OperationConfig) -> float:
    """Horas médias de colheita por dia (turno − manutenção) × disponibilidade média (valor esperado)."""
    j = cfg.janela
    hs = [(j.horas_colheita_dia - c.parada_programada_min_dia / 60) * c.disponibilidade_mecanica for c in cfg.colheitadeiras]
    return float(np.mean(hs))


def razao_recebimento(cfg: OperationConfig) -> float:
    """Horas de recebimento disponíveis por hora de colheita (capacidade diária ÷ demanda diária)."""
    r = cfg.recebimento
    return (r.hora_fechamento - r.hora_abertura) / cfg.janela.horas_colheita_dia
