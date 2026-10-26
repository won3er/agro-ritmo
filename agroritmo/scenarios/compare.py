"""Execução e comparação de cenários (com replicações e números aleatórios comuns)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..analytics.costs import calcular_custos
from ..analytics.kpis import calcular_kpis, kpis_dict
from ..domain.models import OperationConfig
from ..logging_config import get_logger
from ..simulation import SimulationResult, simular
from .modifications import Cenario, Modificacao, aplicar

log = get_logger(__name__)

METRICAS_COMPARACAO = [
    ("duracao_h", "Duração (h)", "min"),
    ("dias_operacao", "Dias de operação", "min"),
    ("t_entregues", "t entregues", "max"),
    ("pct_area", "Área concluída (%)", "max"),
    ("custo_total", "Custo total (R$)", "min"),
    ("custo_por_t", "Custo por t (R$/t)", "min"),
    ("util_colheitadeiras", "Utilização colheitadeiras (%)", "max"),
    ("util_caminhoes", "Utilização caminhões (%)", "max"),
    ("espera_colh_caminhao_h", "Colheitadeiras aguardando caminhão (h)", "min"),
    ("caminhao_aguardando_h", "Caminhões aguardando carregamento (h)", "min"),
    ("fila_descarga_h", "Fila de descarga (h)", "min"),
    ("fila_max", "Fila máxima (caminhões)", "min"),
    ("fila_media_min", "Espera média por carga (min)", "min"),
    ("concluida", "Concluída na janela", "max"),
]

OBJETIVOS = {
    "custo_por_t": "Menor custo por tonelada (entre cenários que concluem a colheita)",
    "custo_total": "Menor custo total (entre cenários que concluem a colheita)",
    "duracao_h": "Menor duração (entre cenários que concluem a colheita)",
    "t_entregues": "Maior volume entregue dentro da janela",
    "prazo_custo": "Menor custo por tonelada entre os que cumprem o prazo desejado",
}

# valores t de Student bicaudal 95% (gl = n − 1)
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        15: 2.131, 20: 2.086, 30: 2.042}


def t95(gl: int) -> float:
    if gl <= 0:
        return float("nan")
    for k in sorted(_T95):
        if gl <= k:
            return _T95[k]
    return 1.96


@dataclass
class ResultadoCenario:
    cenario: Cenario
    config: OperationConfig
    resultados: list[SimulationResult]
    kpis: list[dict]
    media: dict = field(default_factory=dict)
    desvio: dict = field(default_factory=dict)
    ic95: dict = field(default_factory=dict)

    @property
    def nome(self) -> str:
        return self.cenario.nome

    @property
    def principal(self) -> SimulationResult:
        return self.resultados[0]


def executar_cenario(base: OperationConfig, cenario: Cenario, replicacoes: int = 1,
                     semente_base: Optional[int] = None) -> ResultadoCenario:
    cfg = aplicar(base, cenario.modificacoes)
    semente_base = cfg.simulacao.semente if semente_base is None else semente_base
    resultados, kp = [], []
    for i in range(replicacoes):
        c = aplicar(cfg, [Modificacao(tipo="semente", valor=semente_base + i)])
        r = simular(c)
        custos = float(calcular_custos(r)["valor"].sum())
        resultados.append(r)
        kp.append(kpis_dict(calcular_kpis(r, custos)))
    rc = ResultadoCenario(cenario=cenario, config=cfg, resultados=resultados, kpis=kp)
    df = pd.DataFrame(kp)
    for col in df.columns:
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if vals.empty:
            continue
        rc.media[col] = float(vals.mean())
        rc.desvio[col] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
        rc.ic95[col] = t95(len(vals) - 1) * rc.desvio[col] / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
    return rc


@dataclass
class Comparacao:
    resultados: list[ResultadoCenario]
    objetivo: str
    tabela: pd.DataFrame
    melhor: Optional[str]
    justificativa: str
    mais_rapido: Optional[str]
    mais_barato: Optional[str]


def _escolher(resultados: list[ResultadoCenario], objetivo: str, prazo_dias: Optional[float]) -> tuple[Optional[str], str]:
    # apenas cenários de decisão concorrem; condições externas (chuva, produtividade...) são testes de estresse
    decisao = [r for r in resultados if r.cenario.controlavel]
    resultados = decisao or resultados
    conc = [r for r in resultados if r.media.get("concluida", 0) >= 0.999]
    if objetivo == "t_entregues":
        best = max(resultados, key=lambda r: (r.media.get("t_entregues", 0), -r.media.get("custo_por_t", 1e18)))
        return best.nome, f"Maior volume entregue: {best.media['t_entregues']:.1f} t."
    if objetivo == "prazo_custo":
        if not prazo_dias:
            return _escolher(resultados, "custo_por_t", None)
        ok = [r for r in conc if r.media.get("duracao_h", 1e18) / 24 <= prazo_dias + 1e-9]
        if not ok:
            return None, f"Nenhum cenário concluiu dentro do prazo de {prazo_dias:.0f} dias."
        best = min(ok, key=lambda r: r.media["custo_por_t"])
        return best.nome, f"Menor custo/t entre {len(ok)} cenário(s) que concluem em até {prazo_dias:.0f} dias."
    if not conc:
        best = max(resultados, key=lambda r: r.media.get("t_entregues", 0))
        return best.nome, "Nenhum cenário concluiu a colheita na janela; escolhido o de maior volume entregue."
    chave = {"custo_por_t": "custo_por_t", "custo_total": "custo_total", "duracao_h": "duracao_h"}[objetivo]
    best = min(conc, key=lambda r: r.media[chave])
    return best.nome, f"Melhor valor de '{chave}' entre {len(conc)} cenário(s) que concluem a colheita."


def comparar(base: OperationConfig, cenarios: list[Cenario], replicacoes: int = 1, objetivo: str = "custo_por_t",
             progresso: Optional[Callable[[int, int, str], None]] = None) -> Comparacao:
    resultados = []
    for i, c in enumerate(cenarios):
        if progresso:
            progresso(i, len(cenarios), c.nome)
        resultados.append(executar_cenario(base, c, replicacoes))
    linhas = []
    for r in resultados:
        linha = {"cenario": r.nome, "tipo": "decisão" if r.cenario.controlavel else "condição externa",
                 "modificacoes": r.cenario.descrever()}
        for chave, rotulo, _ in METRICAS_COMPARACAO:
            linha[chave] = r.media.get(chave)
            if replicacoes > 1:
                linha[chave + "_ic95"] = r.ic95.get(chave)
        linhas.append(linha)
    tabela = pd.DataFrame(linhas)
    base_row = tabela.iloc[0]
    for chave in ("duracao_h", "custo_total", "custo_por_t"):
        if base_row[chave]:
            tabela[f"delta_{chave}_pct"] = (tabela[chave] / base_row[chave] - 1) * 100
    melhor, just = _escolher(resultados, objetivo, base.janela.data_alvo_dias)
    conc = [r for r in resultados if r.media.get("concluida", 0) >= 0.999 and r.cenario.controlavel]
    rapido = min(conc, key=lambda r: r.media["duracao_h"]).nome if conc else None
    barato = min(conc, key=lambda r: r.media["custo_por_t"]).nome if conc else None
    if rapido and barato and rapido != barato:
        just += (f" Observação: o cenário mais rápido ('{rapido}') não é o de menor custo por tonelada ('{barato}') — "
                 "reduzir o tempo exige recursos adicionais cujo custo pode superar o ganho.")
    return Comparacao(resultados=resultados, objetivo=objetivo, tabela=tabela, melhor=melhor, justificativa=just,
                      mais_rapido=rapido, mais_barato=barato)
