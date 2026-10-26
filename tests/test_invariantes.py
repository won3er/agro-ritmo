"""Invariantes físicos e contábeis do motor de simulação."""
import json

import numpy as np
import pytest

from agroritmo.analytics import calcular_kpis, kpis_dict, utilizacao_caminhoes
from agroritmo.analytics.kpis import max_simultaneo
from agroritmo.domain.defaults import exemplo_milho, exemplo_soja
from agroritmo.scenarios import Modificacao, aplicar
from agroritmo.simulation import hash_resultado, simular

CENARIOS = {
    "soja": exemplo_soja,
    "milho": exemplo_milho,
    "soja_estressado": lambda: aplicar(exemplo_soja(), [
        Modificacao(tipo="capacidade_recebimento", valor=0.35),
        Modificacao(tipo="chuva", dia=2, hora=9, duracao_h=30),
        Modificacao(tipo="falha_equipamento", recurso_id="C1", dia=3, hora=10, duracao_h=20),
        Modificacao(tipo="falha_equipamento", recurso_id="CAR-01", dia=2, hora=10, duracao_h=10),
        Modificacao(tipo="semente", valor=7)]),
    "soja_dedicada": lambda: aplicar(exemplo_soja(), [Modificacao(tipo="alocacao", alocacao={"C1": 2, "C2": 2, "C3": 2})]),
}


@pytest.fixture(scope="module", params=list(CENARIOS))
def res(request):
    return simular(CENARIOS[request.param]())


def test_conservacao_do_volume(res):
    """colhido = entregue + em tanques + em caminhões (nada some, nada é criado)."""
    assert res.colhido_t == pytest.approx(res.entregue_t + res.em_tanques_t + res.em_caminhoes_t, abs=1e-6)
    ev = res.eventos
    assert ev[ev.tipo == "COLHEITA"]["qtd_t"].sum() == pytest.approx(res.colhido_t, abs=1e-6)
    transb = ev[ev.tipo == "TRANSBORDO"]["qtd_t"].sum()
    assert transb == pytest.approx(res.entregue_t + res.em_caminhoes_t, abs=1e-6)
    if res.concluida:
        assert res.entregue_t == pytest.approx(res.config.producao_prevista_t, rel=1e-6)


def test_sem_dupla_contabilizacao(res):
    cg = res.cargas
    assert cg["carga"].is_unique
    fim = res.eventos[res.eventos.tipo == "FIM_DESCARGA"]
    assert fim["carga"].is_unique
    assert fim["qtd_t"].sum() == pytest.approx(res.entregue_t, abs=1e-6)
    entregues = cg[cg.status == "entregue"]
    assert entregues["quantidade_t"].sum() == pytest.approx(res.entregue_t, abs=1e-6)
    assert set(entregues["carga"]) == set(fim["carga"])


def test_descarregado_nao_supera_transportado(res):
    for _, c in res.cargas.iterrows():
        assert c["quantidade_t"] <= c["capacidade_t"] + 1e-6
        origem = sum(json.loads(c["por_talhao"]).values())
        assert origem == pytest.approx(c["quantidade_t"], abs=1e-4)
        maquinas = sum(json.loads(c["por_colheitadeira"]).values())
        assert maquinas == pytest.approx(c["quantidade_t"], abs=1e-4)


def test_volume_por_talhao_bate(res):
    if not res.concluida:
        return
    por_talhao = {}
    for s in res.cargas["por_talhao"]:
        for k, v in json.loads(s).items():
            por_talhao[k] = por_talhao.get(k, 0) + v
    for _, t in res.talhoes.iterrows():
        assert por_talhao.get(t["talhao"], 0) == pytest.approx(t["t_colhidas"], abs=1e-3)
        assert t["area_colhida_ha"] == pytest.approx(t["area_ha"], abs=1e-4)


def test_recurso_nao_executa_tarefas_simultaneas(res):
    """Segmentos de estado de cada recurso não se sobrepõem."""
    for rec, g in res.segmentos.groupby("recurso"):
        g = g.sort_values("inicio")
        ini, fim = g["inicio"].to_numpy(), g["fim"].to_numpy()
        assert np.all(fim >= ini - 1e-9), rec
        assert np.all(ini[1:] >= fim[:-1] - 1e-6), rec


def test_caminhao_uma_viagem_por_vez(res):
    for cam, g in res.cargas.dropna(subset=["t_saida_campo"]).groupby("caminhao"):
        g = g.sort_values("t_saida_campo")
        sai = g["t_saida_campo"].to_numpy()
        fim = g["t_fim_descarga"].fillna(np.inf).to_numpy()
        assert np.all(sai[1:] >= fim[:-1] - 1e-6), cam


def test_capacidade_de_recebimento_respeitada(res):
    sg = res.segmentos
    desc = sg[(sg.tipo == "caminhao") & (sg.estado == "descarregando")]
    assert max_simultaneo(desc) <= res.config.recebimento.n_moegas
    # nenhuma descarga começa com a unidade fechada
    janelas = res.janelas["unidade"]
    for t in res.cargas["t_inicio_descarga"].dropna():
        assert any(a - 1e-6 <= t < b for a, b in janelas)


def test_colheita_somente_em_janela(res):
    sg = res.segmentos
    for hid, jan in res.janelas["colheitadeiras"].items():
        for a, b in zip(*sg[(sg.recurso == hid) & (sg.estado == "colhendo")][["inicio", "fim"]].to_numpy().T):
            assert any(x - 1e-6 <= a and b <= y + 1e-6 for x, y in jan), (hid, a, b)


def test_consistencia_eventos_indicadores(res):
    k = kpis_dict(calcular_kpis(res))
    assert k["t_entregues"] == pytest.approx(res.entregue_t)
    assert k["cargas"] == (res.cargas.status == "entregue").sum()
    ut = utilizacao_caminhoes(res)
    sg = res.segmentos
    assert ut["fila_descarga_h"].sum() == pytest.approx(sg[sg.estado == "fila_descarga"]["duracao_min"].sum() / 60)


def test_reprodutibilidade_mesma_semente():
    a, b = simular(exemplo_soja()), simular(exemplo_soja())
    assert hash_resultado(a) == hash_resultado(b)
    assert a.eventos.equals(b.eventos)


def test_semente_diferente_muda_resultado():
    a = simular(exemplo_soja())
    b = simular(aplicar(exemplo_soja(), [Modificacao(tipo="semente", valor=999)]))
    assert hash_resultado(a) != hash_resultado(b)
