"""Cenários controlados com resultado calculado manualmente."""
import pytest

from agroritmo.analytics import calcular_custos, calcular_kpis, identificar_gargalos, kpis_dict
from agroritmo.simulation import simular

from .conftest import controlado


def test_linha_do_tempo_calculada_a_mao(cfg_controlado):
    # 06:00 caminhão parte; 06:30 chega ao campo. 08:00 colheita começa.
    # 3 tanques de 10 t (40 min cada) + 3 descargas de 2 min → caminhão cheio (30 t) às 10:06.
    # Viagem 30 min → 10:36; descarga 30 t a 60 t/h = 30 min → 11:06 (666 min).
    r = simular(cfg_controlado)
    assert r.concluida
    assert r.t_inicio == pytest.approx(480.0)
    assert r.t_fim == pytest.approx(666.0)
    assert r.entregue_t == pytest.approx(30.0)
    assert len(r.cargas) == 1
    c = r.cargas.iloc[0]
    assert c["t_saida_campo"] == pytest.approx(606.0)
    assert c["t_chegada_unidade"] == pytest.approx(636.0)
    assert c["t_inicio_descarga"] == pytest.approx(636.0)
    assert c["quantidade_t"] == pytest.approx(30.0)
    k = kpis_dict(calcular_kpis(r))
    assert k["espera_colh_caminhao_h"] == pytest.approx(0.0)
    assert k["duracao_h"] == pytest.approx(3.1)
    assert k["prod_colheita_t_h"] == pytest.approx(15.0)


def test_custos_calculados_a_mao(cfg_controlado):
    # Colheitadeira: fixo 3,1 h × 100 = 310; variável 2 h × 50 = 100; diesel 2 h × 10 L × 5 = 100.
    # Caminhão: fixo (06:00→11:06 = 5,1 h) × 60 = 306; 60 km × 1 = 60; 60 km ÷ 2 km/L × 5 = 150.
    r = simular(cfg_controlado)
    c = calcular_custos(r)
    v = c.set_index(["recurso", "componente"])["valor"]
    assert v[("H1", "Custo fixo (horas de turno mobilizadas)")] == pytest.approx(310.0)
    assert v[("H1", "Custo variável (horas colhendo)")] == pytest.approx(100.0)
    assert v[("H1", "Combustível")] == pytest.approx(100.0)
    assert v[("T-01", "Custo fixo (horas de jornada mobilizadas)")] == pytest.approx(306.0)
    assert v[("T-01", "Custo variável (km rodados)")] == pytest.approx(60.0)
    assert v[("T-01", "Combustível")] == pytest.approx(150.0)
    assert c["valor"].sum() == pytest.approx(1026.0)
    assert kpis_dict(calcular_kpis(r))["custo_por_t"] == pytest.approx(1026.0 / 30.0)
    assert all(c["formula"].str.len() > 0)


def test_espera_por_caminhao_calculada_a_mao():
    # Caminhão de 10 t: cada carga exige ida (30) + descarga (10) + volta (30) = 70 min, enquanto o tanque enche em 40 min.
    # 2º e 3º tanques aguardam 30 min cada → 60 min de espera. Fim: 11:46 = 706 min.
    r = simular(controlado(cap_caminhao=10.0))
    assert r.concluida
    assert r.t_fim == pytest.approx(706.0)
    assert len(r.cargas) == 3
    k = kpis_dict(calcular_kpis(r))
    assert k["espera_colh_caminhao_h"] == pytest.approx(1.0)
    g = {x.codigo: x for x in identificar_gargalos(r)}
    assert "COLH_AGUARDA_CAMINHAO" in g
    assert g["COLH_AGUARDA_CAMINHAO"].duracao_h == pytest.approx(1.0)
    assert g["COLH_AGUARDA_CAMINHAO"].frequencia == 2
    assert g["COLH_AGUARDA_CAMINHAO"].consequencia_rs == pytest.approx(100.0)  # 1 h × R$ 100/h
    assert "1,0 h × R$ 100,00/h" in g["COLH_AGUARDA_CAMINHAO"].formula_rs


def test_eficiencia_e_disponibilidade_nao_sao_descontadas_duas_vezes():
    # Eficiência 0,5 dobra o tempo colhendo; disponibilidade < 1 não altera a taxa (só gera falhas).
    r1 = simular(controlado(colheitadeiras=[{"id": "H1", "capacidade_campo_ha_h": 5, "eficiencia_campo": 0.5,
                                              "capacidade_tanque_t": 10, "tempo_descarga_tanque_min": 2,
                                              "disponibilidade_mecanica": 1.0, "parada_programada_min_dia": 0}]))
    assert r1.colheitadeiras.iloc[0]["horas_colheita"] == pytest.approx(4.0)
    r2 = simular(controlado(colheitadeiras=[{"id": "H1", "capacidade_campo_ha_h": 5, "eficiencia_campo": 1.0,
                                              "capacidade_tanque_t": 10, "tempo_descarga_tanque_min": 2,
                                              "disponibilidade_mecanica": 0.5, "mttr_h": 1, "parada_programada_min_dia": 0}],
                            simulacao={"falhas_aleatorias": True}))
    # A = 0,5 e MTTR = 1 h → MTBF = 1 h (determinístico com CV = 0): falhas ao completar 1 h e 2 h colhendo,
    # cada uma com 1 h de reparo. A taxa continua intacta (2 h colhendo); a disponibilidade aparece só como falha.
    assert r2.colheitadeiras.iloc[0]["horas_colheita"] == pytest.approx(2.0)
    sg = r2.segmentos
    assert sg[(sg["recurso"] == "H1") & (sg["estado"] == "falha")]["duracao_min"].sum() == pytest.approx(120.0)
    assert r2.t_fim == pytest.approx(666.0 + 120.0)
    # disponibilidade observada = colhendo ÷ (colhendo + falha) = 2 / (2 + 2) = A
    assert 2.0 / (2.0 + 2.0) == pytest.approx(r2.config.colheitadeiras[0].disponibilidade_mecanica)


def test_manutencao_programada_e_turno():
    r = simular(controlado(colheitadeiras=[{"id": "H1", "capacidade_campo_ha_h": 5, "eficiencia_campo": 1.0,
                                             "capacidade_tanque_t": 10, "tempo_descarga_tanque_min": 2,
                                             "disponibilidade_mecanica": 1.0, "parada_programada_min_dia": 30}]))
    assert r.t_inicio == pytest.approx(510.0)  # 08:00 + 30 min de manutenção
    sg = r.segmentos
    m = sg[(sg["recurso"] == "H1") & (sg["estado"] == "manutencao_programada")]
    assert m["duracao_min"].sum() == pytest.approx(30.0)


def test_chuva_bloqueia_colheita():
    # chuva 08:00–09:00 + 1 h de secagem → colheita só começa às 10:00
    r = simular(controlado(clima={"eventos_chuva": [{"dia": 1, "hora_inicio": 8, "duracao_h": 1}], "espera_pos_chuva_h": 1}))
    assert r.t_inicio == pytest.approx(600.0)
    sg = r.segmentos
    assert sg[(sg["recurso"] == "H1") & (sg["estado"] == "parada_clima")]["duracao_min"].sum() == pytest.approx(120.0)
