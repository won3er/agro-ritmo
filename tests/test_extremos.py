"""Comportamento em situações extremas."""
import pytest

from agroritmo.analytics import calcular_kpis, identificar_gargalos, kpis_dict
from agroritmo.simulation import simular

from .conftest import controlado


def _conserva(r):
    assert r.colhido_t == pytest.approx(r.entregue_t + r.em_tanques_t + r.em_caminhoes_t, abs=1e-6)


def test_chuva_durante_todo_horizonte():
    r = simular(controlado(clima={"eventos_chuva": [{"dia": 1, "hora_inicio": 0, "duracao_h": 72}]}))
    assert not r.concluida
    assert r.colhido_t == 0
    _conserva(r)
    assert any(g.codigo == "JANELA_EXCEDIDA" for g in identificar_gargalos(r))


def test_area_grande_nao_cabe_na_janela():
    r = simular(controlado(talhoes=[{"id": "A", "area_ha": 2000, "produtividade_sc_ha": 50, "distancia_km": 30}],
                           custos={"preco_diesel_l": 5.0, "valor_saca": 100.0}))
    assert not r.concluida
    _conserva(r)
    g = {x.codigo: x for x in identificar_gargalos(r)}
    pend = r.config.producao_prevista_t - r.entregue_t
    assert g["JANELA_EXCEDIDA"].consequencia_volume_t == pytest.approx(pend)
    assert g["JANELA_EXCEDIDA"].consequencia_rs == pytest.approx(pend * 1000 / 60 * 100)


def test_recebimento_muito_lento_gera_fila():
    r = simular(controlado(cap_caminhao=10.0, frota=[{"id": "T", "quantidade": 4, "capacidade_t": 10}],
                           recebimento={"capacidade_t_h": 5}))
    _conserva(r)
    k = kpis_dict(calcular_kpis(r))
    assert k["fila_descarga_h"] > 0
    assert any(g.codigo == "FILA_DESCARGA" for g in identificar_gargalos(r))


def test_talhao_liberado_apos_horizonte():
    r = simular(controlado(talhoes=[{"id": "A", "area_ha": 10, "produtividade_sc_ha": 50, "distancia_km": 30,
                                     "disponivel_a_partir_dia": 10}]))
    assert not r.concluida
    assert r.colhido_t == 0


def test_unidade_interrompida_todo_horizonte():
    r = simular(controlado(eventos=[{"tipo": "interrupcao_recebimento", "dia": 1, "hora": 0, "duracao_h": 72}]))
    assert not r.concluida
    assert r.entregue_t == 0
    _conserva(r)
    assert r.em_caminhoes_t > 0


def test_frota_grande_e_muitos_talhoes():
    talhoes = [{"id": f"T{i}", "area_ha": 30, "produtividade_sc_ha": 60, "distancia_km": 5 + i, "x_km": i, "y_km": i % 3}
               for i in range(15)]
    r = simular(controlado(talhoes=talhoes, frota=[{"id": "T", "quantidade": 40, "capacidade_t": 30}],
                           janela={"horizonte_dias": 20}))
    assert r.concluida
    _conserva(r)


def test_falha_informada_de_colheitadeira_atrasa():
    base = simular(controlado())
    r = simular(controlado(eventos=[{"tipo": "falha_forcada", "dia": 1, "hora": 8, "duracao_h": 2, "recurso_id": "H1"}]))
    assert r.t_fim == pytest.approx(base.t_fim + 120.0)


def test_capacidade_reduzida_alonga_descarga():
    r = simular(controlado(eventos=[{"tipo": "capacidade_recebimento", "dia": 1, "hora": 0, "duracao_h": 24, "valor": 0.5}]))
    c = r.cargas.iloc[0]
    assert c["t_fim_descarga"] - c["t_inicio_descarga"] == pytest.approx(60.0)  # 30 t a 30 t/h
