"""Registro configurável de culturas agrícolas.

Novas culturas podem ser adicionadas ao registro (``registrar_cultura``) ou
informadas diretamente na configuração da operação (``OperationConfig.cultura_spec``)
sem alterar o motor de simulação: o motor trabalha apenas com t/ha.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CropSpec(BaseModel):
    codigo: str
    nome: str
    kg_por_saca: float = Field(60.0, gt=0, description="Massa de uma saca (kg)")
    umidade_referencia_pct: float = Field(14.0, ge=0, le=40)
    produtividade_tipica_sc_ha: tuple[float, float] = Field(
        (20.0, 120.0), description="Faixa usada apenas para alertas de plausibilidade"
    )


_REGISTRO: dict[str, CropSpec] = {
    "soja": CropSpec(codigo="soja", nome="Soja", kg_por_saca=60.0, umidade_referencia_pct=14.0,
                     produtividade_tipica_sc_ha=(25.0, 100.0)),
    "milho": CropSpec(codigo="milho", nome="Milho", kg_por_saca=60.0, umidade_referencia_pct=14.0,
                      produtividade_tipica_sc_ha=(40.0, 250.0)),
}


def registrar_cultura(spec: CropSpec) -> None:
    _REGISTRO[spec.codigo] = spec


def obter_cultura(codigo: str) -> CropSpec:
    try:
        return _REGISTRO[codigo]
    except KeyError as exc:
        raise ValueError(f"Cultura '{codigo}' não registrada. Disponíveis: {sorted(_REGISTRO)}") from exc


def culturas_disponiveis() -> list[str]:
    return sorted(_REGISTRO)
