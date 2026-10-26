"""Persistência, importação, calibração, relatórios e exportações."""
import io
import zipfile

import pandas as pd
import pytest

from agroritmo.analytics import calcular_kpis, kpis_dict
from agroritmo.data import calibrar, comparar_observado, importar_arquivo, importar_operacao_excel, modelo_excel
from agroritmo.data.calibration import tabela_parametros
from agroritmo.domain.models import OrigemDado
from agroritmo.reports import PacoteRelatorio, exportar_csv_zip, exportar_excel, gerar_pdf
from agroritmo.simulation import hash_resultado, simular

from .conftest import controlado


def test_repositorio_operacoes_e_execucoes(repo, cfg_exemplo, res_exemplo):
    oid = repo.salvar_operacao(cfg_exemplo)
    assert repo.salvar_operacao(cfg_exemplo) == oid  # upsert por nome
    assert repo.carregar_operacao(oid) == cfg_exemplo
    assert len(repo.listar_operacoes()) == 1
    eid = repo.registrar_execucao(cfg_exemplo, kpis_dict(calcular_kpis(res_exemplo)), hash_resultado(res_exemplo))
    cfg, kpis, h = repo.carregar_execucao(eid)
    assert hash_resultado(simular(cfg)) == h  # repetir com mesma configuração e semente
    assert kpis["t_entregues"] == pytest.approx(res_exemplo.entregue_t)
    repo.excluir_operacao(oid)
    assert repo.listar_operacoes().empty


def test_observacoes_e_comparacao(repo, cfg_controlado):
    oid = repo.salvar_operacao(cfg_controlado)
    repo.adicionar_observacao(oid, "tempo_viagem_carregado_min", 33)
    repo.adicionar_observacao(oid, "tempo_viagem_carregado_min", 27)
    obs = repo.listar_observacoes(oid)
    comp = comparar_observado(simular(cfg_controlado), obs).set_index("metrica")
    assert comp.loc["tempo_viagem_carregado_min", "observado"] == pytest.approx(30)
    assert comp.loc["tempo_viagem_carregado_min", "simulado"] == pytest.approx(30)
    assert bool(comp.loc["tempo_viagem_carregado_min", "dentro_tolerancia"])


def test_calibracao_reduz_erro_e_marca_proveniencia(cfg_controlado):
    cal = calibrar(cfg_controlado, "tempo_viagem_carregado_min", 45.0)  # observado: 45 min → velocidade × 2/3
    assert abs(cal.simulado_depois - 45) < abs(cal.simulado_antes - 45)
    assert cal.fator == pytest.approx(2 / 3, abs=0.02)
    tp = tabela_parametros(cal.config_calibrada).set_index("parametro")
    assert tp.loc["frota.T.velocidade_carregado_km_h", "origem"] == OrigemDado.CALIBRADO.value
    assert tp.loc["talhoes.A.area_ha", "origem"] == cfg_controlado.origem_dados.value  # demais preservados


def test_importacao_valida_colunas_unidades_e_inconsistencias():
    csv = "id;area_ha;produtividade_sc_ha;distancia_km\nA;10,5;60;12\nA;abc;60;5\nC;5;60;-3\n"
    rel = importar_arquivo(csv.encode(), "t.csv", "talhoes")
    assert not rel.ok
    msgs = " ".join(e["mensagem"] for e in rel.erros)
    assert "não numérico" in msgs and "fora do intervalo" in msgs and "duplicado" in msgs
    rel2 = importar_arquivo(b"id;area_ha\nA;10\n", "t.csv", "talhoes")
    assert any(e["coluna"] == "produtividade_sc_ha" for e in rel2.erros)
    ok = importar_arquivo("id;area_ha;produtividade_sc_ha;distancia_km\nA;10,5;60;12\n".encode(), "t.csv", "talhoes")
    assert ok.ok and ok.dados.iloc[0]["area_ha"] == pytest.approx(10.5)


def test_importacao_workbook(cfg_exemplo):
    novo, rels = importar_operacao_excel(io.BytesIO(modelo_excel()), cfg_exemplo)
    assert all(r.ok for r in rels), [r.resumo() for r in rels]
    assert novo.origem_dados == OrigemDado.IMPORTADO
    assert len(novo.talhoes) == 1 and novo.talhoes[0].id == "T01"


def test_relatorios_consistentes_com_simulacao(res_exemplo):
    p = PacoteRelatorio.montar(res_exemplo)
    xls = pd.read_excel(io.BytesIO(exportar_excel(p)), sheet_name=None)
    assert {"Resumo", "Indicadores", "Premissas", "Custos", "Gargalos", "Eventos", "Cargas"} <= set(xls)
    cg = xls["Cargas"]
    assert cg[cg.status == "entregue"]["quantidade_t"].sum() == pytest.approx(res_exemplo.entregue_t)
    ind = xls["Indicadores"].set_index("chave")
    assert ind.loc["custo_total", "valor"] == pytest.approx(p.custos["valor"].sum())
    z = zipfile.ZipFile(io.BytesIO(exportar_csv_zip(p)))
    assert "eventos.csv" in z.namelist() and "configuracao.json" in z.namelist()
    pdf = gerar_pdf(p)
    assert pdf[:4] == b"%PDF" and len(pdf) > 50_000
