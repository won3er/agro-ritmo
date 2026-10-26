"""Conversões de unidades e formatação de tempo.

Convenções internas do sistema:
- tempo do simulador em **minutos** (float), t = 0 corresponde a 00:00 do Dia 1;
- massa em **toneladas** (t);
- área em **hectares** (ha);
- distância em **quilômetros** (km);
- valores monetários em **R$**.
"""
from __future__ import annotations

MIN_POR_HORA = 60.0
MIN_POR_DIA = 1440.0


def sacas_para_toneladas(sacas: float, kg_por_saca: float) -> float:
    return sacas * kg_por_saca / 1000.0


def produtividade_t_ha(sc_ha: float, kg_por_saca: float) -> float:
    """Converte produtividade de sacas/ha para t/ha."""
    return sc_ha * kg_por_saca / 1000.0


def toneladas_para_sacas(t: float, kg_por_saca: float) -> float:
    return t * 1000.0 / kg_por_saca


def tempo_viagem_min(distancia_km: float, velocidade_km_h: float) -> float:
    return distancia_km / velocidade_km_h * MIN_POR_HORA


def dia_de(t_min: float) -> int:
    """Dia (1-based) que contém o instante t."""
    return int(t_min // MIN_POR_DIA) + 1


def formatar_relogio(t_min: float) -> str:
    """Formata o relógio da simulação como 'D3 14:05'."""
    if t_min is None:
        return "—"
    dia = int(t_min // MIN_POR_DIA) + 1
    resto = t_min - (dia - 1) * MIN_POR_DIA
    h = int(resto // 60)
    m = int(round(resto - h * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"D{dia} {h:02d}:{m:02d}"


def formatar_duracao(minutos: float) -> str:
    if minutos is None:
        return "—"
    h = minutos / 60.0
    if h < 48:
        return f"{h:,.1f} h".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{h / 24:,.1f} dias ({h:,.0f} h)".replace(",", "X").replace(".", ",").replace("X", ".")


def brl(valor: float) -> str:
    """Formata valor monetário no padrão brasileiro."""
    s = f"{valor:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def num(valor: float, casas: int = 1) -> str:
    s = f"{valor:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
