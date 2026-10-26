"""Operações de EXEMPLO (cenários sintéticos).

ATENÇÃO: todos os valores abaixo são exemplos ilustrativos para demonstração do sistema.
Não são médias oficiais do setor nem representam uma fazenda real. Substitua pelos dados
da sua operação ou calibre a partir de observações (módulo de calibração).
"""
from __future__ import annotations

from .models import (
    Clima,
    Colheitadeira,
    Custos,
    EventoChuva,
    JanelaOperacao,
    OperationConfig,
    OrigemDado,
    OutroCusto,
    ParametrosSimulacao,
    Talhao,
    TipoCaminhao,
    UnidadeRecebimento,
)

AVISO_EXEMPLO = (
    "Cenário sintético de exemplo: valores ilustrativos, não são médias oficiais do setor "
    "nem dados de uma fazenda real."
)


def exemplo_soja() -> OperationConfig:
    return OperationConfig(
        nome="Exemplo — Colheita de soja (sintético)",
        descricao=AVISO_EXEMPLO,
        cultura="soja",
        talhoes=[
            Talhao(id="T01", nome="Sede Norte", area_ha=180, produtividade_sc_ha=64, prioridade=1, distancia_km=9, x_km=2, y_km=8),
            Talhao(id="T02", nome="Baixada", area_ha=220, produtividade_sc_ha=58, prioridade=2, distancia_km=14, x_km=6, y_km=11),
            Talhao(id="T03", nome="Espigão", area_ha=160, produtividade_sc_ha=70, prioridade=1, distancia_km=12, x_km=9, y_km=5),
            Talhao(id="T04", nome="Retiro", area_ha=240, produtividade_sc_ha=61, prioridade=3, distancia_km=22, x_km=15, y_km=12),
            Talhao(id="T05", nome="Cabeceira", area_ha=200, produtividade_sc_ha=55, prioridade=4, distancia_km=26, x_km=18, y_km=4),
            Talhao(id="T06", nome="Pivô Leste", area_ha=120, produtividade_sc_ha=72, prioridade=2, distancia_km=17, x_km=12, y_km=0,
                   disponivel_a_partir_dia=4),
        ],
        colheitadeiras=[
            Colheitadeira(id="C1", nome="Colheitadeira 1", modelo="Classe VII (exemplo)", capacidade_campo_ha_h=7.5,
                          eficiencia_campo=0.75, capacidade_tanque_t=11.0, tempo_descarga_tanque_min=2.5,
                          disponibilidade_mecanica=0.95, mttr_h=2.5),
            Colheitadeira(id="C2", nome="Colheitadeira 2", modelo="Classe VII (exemplo)", capacidade_campo_ha_h=7.5,
                          eficiencia_campo=0.75, capacidade_tanque_t=11.0, tempo_descarga_tanque_min=2.5,
                          disponibilidade_mecanica=0.95, mttr_h=2.5),
            Colheitadeira(id="C3", nome="Colheitadeira 3", modelo="Classe VI (exemplo)", capacidade_campo_ha_h=6.0,
                          eficiencia_campo=0.70, capacidade_tanque_t=9.0, tempo_descarga_tanque_min=2.2,
                          disponibilidade_mecanica=0.90, mttr_h=3.0, custo_fixo_h=210, custo_variavel_h=160, consumo_l_h=32),
        ],
        frota=[
            TipoCaminhao(id="CAR", nome="Carreta graneleira", quantidade=4, capacidade_t=32, velocidade_carregado_km_h=38,
                         velocidade_vazio_km_h=50, tempo_manobra_min=3, disponibilidade_mecanica=0.97, mttr_h=3,
                         custo_fixo_h=115, custo_variavel_km=1.5, consumo_km_l=2.2),
            TipoCaminhao(id="TRK", nome="Caminhão truck", quantidade=2, capacidade_t=15, velocidade_carregado_km_h=42,
                         velocidade_vazio_km_h=55, tempo_manobra_min=2, disponibilidade_mecanica=0.97, mttr_h=2,
                         custo_fixo_h=85, custo_variavel_km=1.0, consumo_km_l=3.2),
        ],
        recebimento=UnidadeRecebimento(nome="Armazém (exemplo)", n_moegas=2, capacidade_t_h=120, tempo_fixo_min=10,
                                       hora_abertura=6, hora_fechamento=22, custo_recebimento_t=0.0),
        janela=JanelaOperacao(colheita_inicio_h=8, colheita_fim_h=19, caminhoes_inicio_h=6, caminhoes_fim_h=22,
                              horizonte_dias=25, data_alvo_dias=12),
        clima=Clima(eventos_chuva=[EventoChuva(dia=3, hora_inicio=13, duracao_h=4)], prob_chuva_dia=0.0,
                    espera_pos_chuva_h=2),
        custos=Custos(preco_diesel_l=6.10, valor_saca=120.0, outros_custos=[
            OutroCusto(nome="Equipe de apoio e supervisão", tipo="por_dia", valor=950.0),
            OutroCusto(nome="Mobilização de equipamentos", tipo="fixo", valor=4500.0),
        ]),
        simulacao=ParametrosSimulacao(semente=42, variabilidade_cv=0.10),
        origem_dados=OrigemDado.EXEMPLO,
    )


def exemplo_milho() -> OperationConfig:
    cfg = exemplo_soja().model_dump()
    cfg["nome"] = "Exemplo — Colheita de milho safrinha (sintético)"
    cfg["cultura"] = "milho"
    prod = {"T01": 125, "T02": 110, "T03": 135, "T04": 118, "T05": 100, "T06": 140}
    for t in cfg["talhoes"]:
        t["produtividade_sc_ha"] = prod[t["id"]]
    for c in cfg["colheitadeiras"]:
        c["capacidade_campo_ha_h"] = round(c["capacidade_campo_ha_h"] * 0.8, 2)
    cfg["frota"][0]["quantidade"] = 6
    cfg["recebimento"]["capacidade_t_h"] = 180
    return OperationConfig.model_validate(cfg)


EXEMPLOS = {
    "Soja — 6 talhões, 3 colheitadeiras, 6 caminhões": exemplo_soja,
    "Milho safrinha — 6 talhões, 3 colheitadeiras, 8 caminhões": exemplo_milho,
}
