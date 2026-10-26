"""Custos operacionais — cada linha mostra quantidade, taxa e a fórmula usada.

Modelo de custos (todas as taxas são informadas pelo usuário):

* Colheitadeira — custo fixo: horas de turno mobilizadas × R$/h (operador, depreciação, seguro).
  Incide inclusive quando a máquina espera, por isso esperas aparecem como custo real.
* Colheitadeira — custo variável: horas colhendo × R$/h (manutenção, desgaste).
* Colheitadeira — combustível: (horas colhendo + horas deslocando) × L/h × R$/L.
* Caminhão — custo fixo: horas de jornada mobilizadas × R$/h.
* Caminhão — custo variável: km rodados × R$/km.
* Caminhão — combustível: km ÷ (km/L) × R$/L.
* Recepção: t entregues × R$/t.
* Outros: por dia de operação, por tonelada ou valor fixo.
"""
from __future__ import annotations

import pandas as pd

from ..domain.units import brl, num
from ..simulation.results import SimulationResult
from .kpis import dias_operacao, horas_mobilizadas_caminhao, horas_mobilizadas_colheitadeira

COLUNAS = ["categoria", "recurso", "componente", "quantidade", "unidade", "taxa", "unidade_taxa", "valor", "formula", "tipo"]


def _linha(categoria, recurso, componente, qtd, unidade, taxa, unidade_taxa, valor=None, formula=None):
    valor = qtd * taxa if valor is None else valor
    if formula is None:
        formula = f"{num(qtd, 2)} {unidade} × {brl(taxa)}/{unidade_taxa.split('/')[-1]} = {brl(valor)}"
    return {"categoria": categoria, "recurso": recurso, "componente": componente, "quantidade": qtd, "unidade": unidade,
            "taxa": taxa, "unidade_taxa": unidade_taxa, "valor": valor, "formula": formula, "tipo": "calculado"}


def calcular_custos(res: SimulationResult) -> pd.DataFrame:
    cfg = res.config
    diesel = cfg.custos.preco_diesel_l
    linhas: list[dict] = []
    hm_c = horas_mobilizadas_colheitadeira(res)
    hm_t = horas_mobilizadas_caminhao(res)
    ch = res.colheitadeiras.set_index("colheitadeira")
    for c in cfg.colheitadeiras:
        h_col = float(ch.loc[c.id, "horas_colheita"])
        h_des = float(ch.loc[c.id, "horas_deslocamento"])
        linhas.append(_linha("Colheitadeiras", c.id, "Custo fixo (horas de turno mobilizadas)", hm_c, "h", c.custo_fixo_h, "R$/h"))
        linhas.append(_linha("Colheitadeiras", c.id, "Custo variável (horas colhendo)", h_col, "h", c.custo_variavel_h, "R$/h"))
        litros = (h_col + h_des) * c.consumo_l_h
        linhas.append(_linha("Colheitadeiras", c.id, "Combustível", litros, "L", diesel, "R$/L",
                             formula=f"({num(h_col, 2)} h colhendo + {num(h_des, 2)} h deslocando) × {num(c.consumo_l_h, 1)} L/h "
                                     f"× {brl(diesel)}/L = {brl(litros * diesel)}"))
    cm = res.caminhoes.set_index("caminhao")
    for cid, g in cfg.caminhoes_expandidos():
        km = float(cm.loc[cid, "km_carregado"] + cm.loc[cid, "km_vazio"])
        linhas.append(_linha("Caminhões", cid, "Custo fixo (horas de jornada mobilizadas)", hm_t, "h", g.custo_fixo_h, "R$/h"))
        linhas.append(_linha("Caminhões", cid, "Custo variável (km rodados)", km, "km", g.custo_variavel_km, "R$/km"))
        litros = km / g.consumo_km_l
        linhas.append(_linha("Caminhões", cid, "Combustível", litros, "L", diesel, "R$/L",
                             formula=f"{num(km, 1)} km ÷ {num(g.consumo_km_l, 2)} km/L × {brl(diesel)}/L = {brl(litros * diesel)}"))
    if cfg.recebimento.custo_recebimento_t > 0:
        linhas.append(_linha("Recepção", cfg.recebimento.nome, "Recepção por tonelada", res.entregue_t, "t",
                             cfg.recebimento.custo_recebimento_t, "R$/t"))
    dias = dias_operacao(res)
    for o in cfg.custos.outros_custos:
        if o.tipo == "por_dia":
            linhas.append(_linha("Outros", "Operação", o.nome, float(dias), "dias", o.valor, "R$/dia"))
        elif o.tipo == "por_tonelada":
            linhas.append(_linha("Outros", "Operação", o.nome, res.entregue_t, "t", o.valor, "R$/t"))
        else:
            linhas.append(_linha("Outros", "Operação", o.nome, 1.0, "un", o.valor, "R$/un",
                                 formula=f"valor fixo informado = {brl(o.valor)}"))
    return pd.DataFrame(linhas, columns=COLUNAS)


def resumo_custos(df: pd.DataFrame) -> pd.DataFrame:
    """Custos agregados por categoria e componente (para gráficos de composição)."""
    comp = df["componente"].str.replace(r" \(.*\)", "", regex=True)
    return (df.assign(componente_base=comp).groupby(["categoria", "componente_base"], as_index=False)["valor"].sum()
            .sort_values("valor", ascending=False))
