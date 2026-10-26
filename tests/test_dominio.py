"""Validações de domínio e unidades."""
import pytest
from pydantic import ValidationError

from agroritmo.domain import CropSpec, OperationConfig, registrar_cultura
from agroritmo.domain.units import formatar_relogio, produtividade_t_ha

from .conftest import controlado


def test_conversao_unidades():
    assert produtividade_t_ha(60, 60) == pytest.approx(3.6)
    assert formatar_relogio(1440 + 14 * 60 + 5) == "D2 14:05"


def test_mtbf_derivado_da_disponibilidade():
    c = controlado(colheitadeiras=[{"id": "H1", "capacidade_campo_ha_h": 5, "capacidade_tanque_t": 10,
                                    "disponibilidade_mecanica": 0.9, "mttr_h": 2}]).colheitadeiras[0]
    assert c.mtbf_h == pytest.approx(18.0)  # A·MTTR/(1−A) = 0,9·2/0,1
    assert c.mtbf_h / (c.mtbf_h + c.mttr_h) == pytest.approx(0.9)


@pytest.mark.parametrize("over, msg", [
    ({"talhoes": [{"id": "A", "area_ha": 1, "produtividade_sc_ha": 50, "distancia_km": 1},
                  {"id": "A", "area_ha": 1, "produtividade_sc_ha": 50, "distancia_km": 1}]}, "duplicados"),
    ({"janela": {"caminhoes_inicio_h": 9}}, "jornada"),
    ({"cultura": "trigo_inexistente"}, "não registrada"),
    ({"frota": [{"id": "T", "quantidade": 0, "capacidade_t": 30}]}, "pelo menos 1"),
    ({"eventos": [{"tipo": "falha_forcada", "dia": 1, "hora": 1, "duracao_h": 1, "recurso_id": "X9"}]}, "inexistente"),
    ({"recebimento": {"hora_abertura": 20, "hora_fechamento": 6}}, "fechamento"),
])
def test_validacoes(over, msg):
    with pytest.raises((ValidationError, ValueError)) as e:
        controlado(**over)
    assert msg in str(e.value)


def test_valores_negativos_rejeitados():
    with pytest.raises(ValidationError):
        controlado(talhoes=[{"id": "A", "area_ha": -5, "produtividade_sc_ha": 50, "distancia_km": 1}])


def test_cultura_configuravel():
    registrar_cultura(CropSpec(codigo="sorgo_teste", nome="Sorgo", kg_por_saca=60, produtividade_tipica_sc_ha=(30, 150)))
    cfg = controlado(cultura="sorgo_teste")
    assert cfg.crop.nome == "Sorgo"
    cfg2 = controlado(cultura="soja", cultura_spec={"codigo": "x", "nome": "Feijão", "kg_por_saca": 60})
    assert cfg2.crop.nome == "Feijão"


def test_alertas_de_plausibilidade():
    cfg = controlado(talhoes=[{"id": "A", "area_ha": 10, "produtividade_sc_ha": 390, "distancia_km": 30}])
    assert any("fora da faixa" in a for a in cfg.alertas())


def test_serializacao_ida_e_volta(cfg_exemplo):
    assert OperationConfig.model_validate_json(cfg_exemplo.model_dump_json()) == cfg_exemplo
