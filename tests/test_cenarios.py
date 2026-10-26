"""Cenários, comparação e sensibilidade."""
import pytest

from agroritmo.scenarios import Cenario, Modificacao, aplicar, cenarios_padrao, comparar, executar_cenario, tornado

from .conftest import controlado


def test_cenarios_com_parametros_identicos_dao_resultados_identicos(cfg_exemplo):
    comp = comparar(cfg_exemplo, [Cenario(nome="A"), Cenario(nome="B")])
    a, b = comp.resultados
    for k in ("duracao_h", "custo_total", "t_entregues", "fila_descarga_h", "espera_colh_caminhao_h"):
        assert a.media[k] == pytest.approx(b.media[k])


def test_modificacoes_aplicadas(cfg_exemplo):
    c = aplicar(cfg_exemplo, [Modificacao(tipo="caminhoes_extra", valor=2), Modificacao(tipo="colheitadeira_extra", valor=1),
                              Modificacao(tipo="capacidade_recebimento", valor=1.5), Modificacao(tipo="fator_distancia", valor=2)])
    assert c.n_caminhoes == cfg_exemplo.n_caminhoes + 2
    assert len(c.colheitadeiras) == len(cfg_exemplo.colheitadeiras) + 1
    assert c.recebimento.capacidade_t_h == pytest.approx(cfg_exemplo.recebimento.capacidade_t_h * 1.5)
    assert c.talhoes[0].distancia_km == pytest.approx(cfg_exemplo.talhoes[0].distancia_km * 2)
    assert cfg_exemplo.n_caminhoes == 6  # original intacta


def test_mais_capacidade_de_colheita_reduz_duracao(cfg_exemplo):
    base = executar_cenario(cfg_exemplo, Cenario(nome="base"))
    mais = executar_cenario(cfg_exemplo, Cenario(nome="+1", modificacoes=[Modificacao(tipo="colheitadeira_extra", valor=1)]))
    assert mais.media["duracao_h"] < base.media["duracao_h"]


def test_melhor_cenario_ignora_condicoes_externas(cfg_exemplo):
    comp = comparar(cfg_exemplo, cenarios_padrao(cfg_exemplo), objetivo="custo_por_t")
    decisao = {c.nome for c in cenarios_padrao(cfg_exemplo) if c.controlavel}
    assert comp.melhor in decisao
    tab = comp.tabela.set_index("cenario")
    assert tab.loc["Produtividade +15%", "tipo"] == "condição externa"


def test_objetivos_diferentes_podem_escolher_cenarios_diferentes(cfg_exemplo):
    cens = [Cenario(nome="Original"), Cenario(nome="+2 cam", modificacoes=[Modificacao(tipo="caminhoes_extra", valor=2)]),
            Cenario(nome="+1 colh", modificacoes=[Modificacao(tipo="colheitadeira_extra", valor=1)])]
    rapido = comparar(cfg_exemplo, cens, objetivo="duracao_h")
    barato = comparar(cfg_exemplo, cens, objetivo="custo_por_t")
    assert rapido.melhor == rapido.mais_rapido
    assert barato.melhor == barato.mais_barato


def test_replicacoes_com_intervalo_de_confianca(cfg_exemplo):
    rc = executar_cenario(cfg_exemplo, Cenario(nome="rep"), replicacoes=3)
    assert len(rc.resultados) == 3
    assert rc.ic95["duracao_h"] >= 0
    assert len({r.semente for r in rc.resultados}) == 3


def test_tornado_controlado():
    td = tornado(controlado(cap_caminhao=10.0), 0.2, ("duracao_h",), ["velocidade_caminhao", "produtividade"])
    assert set(td["parametro"]) == {"velocidade_caminhao", "produtividade"}
    v = td.set_index("parametro").loc["velocidade_caminhao"]
    assert v["valor_alto"] < v["base"] < v["valor_baixo"]  # caminhão mais rápido → menos espera → menor duração
