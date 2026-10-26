"""Fixtures compartilhadas.

Cenário controlado (resultado calculável à mão) — ver docstring de ``cfg_controlado``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AGRORITMO_LOG_LEVEL", "WARNING")

from agroritmo.domain.defaults import exemplo_soja  # noqa: E402
from agroritmo.domain.models import OperationConfig  # noqa: E402
from agroritmo.simulation import simular  # noqa: E402


def controlado(cap_caminhao: float = 30.0, **over) -> OperationConfig:
    """Operação determinística mínima.

    * 1 talhão de 10 ha a 50 sc/ha (60 kg) = 3 t/ha → 30 t; 30 km da unidade.
    * 1 colheitadeira: 5 ha/h × eficiência 1,0 = 15 t/h; tanque 10 t (enche em 40 min); descarga do tanque 2 min.
    * 1 caminhão: 60 km/h carregado e vazio (30 min por trecho), sem manobra.
    * Unidade: 1 moega, 60 t/h, sem tempo fixo, aberta 24 h.
    * Turno de colheita 8h–18h, caminhões 6h–22h. Sem variabilidade, falhas, manutenção ou chuva.
    """
    d = {
        "nome": "Controlado", "cultura": "soja",
        "talhoes": [{"id": "A", "area_ha": 10, "produtividade_sc_ha": 50, "distancia_km": 30, "x_km": 0, "y_km": 0}],
        "colheitadeiras": [{"id": "H1", "capacidade_campo_ha_h": 5, "eficiencia_campo": 1.0, "capacidade_tanque_t": 10,
                            "tempo_descarga_tanque_min": 2, "disponibilidade_mecanica": 1.0, "parada_programada_min_dia": 0,
                            "custo_fixo_h": 100, "custo_variavel_h": 50, "consumo_l_h": 10}],
        "frota": [{"id": "T", "quantidade": 1, "capacidade_t": cap_caminhao, "velocidade_carregado_km_h": 60,
                   "velocidade_vazio_km_h": 60, "tempo_manobra_min": 0, "disponibilidade_mecanica": 1.0,
                   "custo_fixo_h": 60, "custo_variavel_km": 1, "consumo_km_l": 2}],
        "recebimento": {"n_moegas": 1, "capacidade_t_h": 60, "tempo_fixo_min": 0, "hora_abertura": 0, "hora_fechamento": 24},
        "janela": {"colheita_inicio_h": 8, "colheita_fim_h": 18, "caminhoes_inicio_h": 6, "caminhoes_fim_h": 22, "horizonte_dias": 3},
        "custos": {"preco_diesel_l": 5.0, "outros_custos": []},
        "simulacao": {"semente": 1, "variabilidade_cv": 0.0, "falhas_aleatorias": False},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k].update(v)
        else:
            d[k] = v
    return OperationConfig.model_validate(d)


@pytest.fixture
def cfg_controlado() -> OperationConfig:
    return controlado()


@pytest.fixture(scope="session")
def cfg_exemplo() -> OperationConfig:
    return exemplo_soja()


@pytest.fixture(scope="session")
def res_exemplo(cfg_exemplo):
    return simular(cfg_exemplo)


@pytest.fixture
def repo(tmp_path):
    from agroritmo.data.db import Repositorio
    return Repositorio(tmp_path / "teste.db")
