"""Otimizador comparado com soluções de referência pequenas (força bruta)."""
import itertools

import pytest

from agroritmo.optimization import (
    avaliar_plano,
    buscar_capacidade_recebimento,
    construir_instancia,
    dimensionar_frota,
    forca_bruta,
    plano_guloso,
    resolver_alocacao,
    resolver_sequencia,
)
from agroritmo.optimization.flow_model import fluxo_colheitadeiras, razao_recebimento, vazao_por_caminhao_t_h
from agroritmo.optimization.sequencing import InstanciaSeq

from .conftest import controlado


def _forca_bruta_alocacao(cfg, max_g, total):
    fluxo = fluxo_colheitadeiras(cfg)
    grupos = {g.id: g for g in cfg.frota}
    cap = cfg.recebimento.capacidade_t_h * min(1.0, razao_recebimento(cfg))
    chaves = [(f.id, gid) for f in fluxo for gid in grupos]
    melhor = 0.0
    for comb in itertools.product(*[range(max_g[gid] + 1) for _, gid in chaves]):
        n = dict(zip(chaves, comb))
        if sum(comb) != total or any(sum(v for (h, g), v in n.items() if g == gid) > max_g[gid] for gid in grupos):
            continue
        vaz = sum(min(f.p_t_h, sum(n[(f.id, gid)] * vazao_por_caminhao_t_h(cfg, g, f) for gid, g in grupos.items()))
                  for f in fluxo)
        melhor = max(melhor, min(vaz, cap))
    return melhor


@pytest.mark.parametrize("total", [1, 2, 3, 4])
def test_alocacao_igual_forca_bruta(total):
    cfg = controlado(
        colheitadeiras=[{"id": "H1", "capacidade_campo_ha_h": 5, "capacidade_tanque_t": 10},
                        {"id": "H2", "capacidade_campo_ha_h": 3, "capacidade_tanque_t": 8}],
        frota=[{"id": "A", "quantidade": 2, "capacidade_t": 30}, {"id": "B", "quantidade": 2, "capacidade_t": 12}],
        recebimento={"capacidade_t_h": 200})
    max_g = {"A": 2, "B": 2}
    sol = resolver_alocacao(cfg, max_g, total=total)
    ref = _forca_bruta_alocacao(cfg, max_g, total)
    assert sol.status == "ÓTIMO"
    assert sol.vazao_t_h == pytest.approx(ref, abs=0.01)  # escala de 1 kg/h


def test_alocacao_respeita_recebimento():
    cfg = controlado(frota=[{"id": "A", "quantidade": 5, "capacidade_t": 30}], recebimento={"capacidade_t_h": 6})
    sol = resolver_alocacao(cfg, {"A": 5})
    assert sol.vazao_t_h <= 6 * min(1, razao_recebimento(cfg)) + 1e-6


def _inst_pequena() -> InstanciaSeq:
    f = ["A", "B", "C", "D"]
    m = ["M1", "M2"]
    proc = {("M1", "A"): 30, ("M1", "B"): 50, ("M1", "C"): 20, ("M1", "D"): 40,
            ("M2", "A"): 45, ("M2", "B"): 35, ("M2", "C"): 25, ("M2", "D"): 60}
    pos = {"A": 0, "B": 3, "C": 7, "D": 12}
    setup = {(k, a, b): abs(pos[a] - pos[b]) * 2 for k in m for a in f for b in f if a != b}
    return InstanciaSeq(f, m, proc, setup, {"A": 0, "B": 0, "C": 40, "D": 0}, {"A": 5, "B": 1, "C": 3, "D": 4})


@pytest.mark.parametrize("alfa,beta", [(1.0, 0.1), (0.05, 1.0), (1.0, 1.0)])
def test_sequencia_igual_forca_bruta(alfa, beta):
    inst = _inst_pequena()
    status, plano, info = resolver_sequencia(inst, alfa, beta, limite_s=20)
    ref, _ = forca_bruta(inst, alfa, beta)
    assert status == "ÓTIMO"
    assert avaliar_plano(inst, plano, alfa, beta)["objetivo"] == pytest.approx(ref, abs=1e-6)
    assert avaliar_plano(inst, plano_guloso(inst), alfa, beta)["objetivo"] >= ref - 1e-6


def test_sequencia_instancia_real(cfg_exemplo):
    inst = construir_instancia(cfg_exemplo)
    status, plano, _ = resolver_sequencia(inst, 1.0, 0.1, 10)
    assert sorted(t for s in plano.values() for t in s) == sorted(t.id for t in cfg_exemplo.talhoes)
    # liberação respeitada
    av = avaliar_plano(inst, plano, 1.0, 0.1)
    for f, s in av["inicio"].items():
        assert s >= inst.liberacao[f]


def test_dimensionamento_frota(cfg_exemplo):
    r = dimensionar_frota(cfg_exemplo, max_extra_por_grupo=2, validar=True)
    assert r.status.startswith("ÓTIMO")
    tab = r.tabela
    assert tab["vazao_t_h"].is_monotonic_increasing  # mais caminhões nunca reduzem a vazão máxima
    sim = r.detalhes["simulacao"]
    assert len(sim) >= 3 and "caminhoes_simulado" in r.recomendacao
    assert r.restricoes and r.limitacoes


def test_busca_capacidade_recebimento_atende_meta():
    cfg = controlado(cap_caminhao=10.0, frota=[{"id": "T", "quantidade": 4, "capacidade_t": 10}], recebimento={"capacidade_t_h": 30})
    r = buscar_capacidade_recebimento(cfg, espera_max_min=5, iteracoes=5)
    assert r.recomendacao["fila_media_min"] <= 5 + 1e-9
    assert "HEURÍSTICO" in r.status
