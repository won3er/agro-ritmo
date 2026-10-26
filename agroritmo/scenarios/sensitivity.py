"""Análise de sensibilidade: tornado (um fator por vez) e varredura paramétrica."""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..domain.models import OperationConfig
from .compare import executar_cenario
from .modifications import Cenario, Modificacao

# nome -> (rótulo, função que cria a modificação para um fator relativo)
PARAMETROS: dict[str, tuple[str, Callable[[OperationConfig, float], Modificacao]]] = {
    "n_caminhoes": ("Quantidade de caminhões",
                    lambda c, f: Modificacao(tipo="caminhoes_total", valor=max(1, round(c.n_caminhoes * f)))),
    "distancia": ("Distância de transporte", lambda c, f: Modificacao(tipo="fator_distancia", valor=f)),
    "capacidade_recebimento": ("Capacidade de recebimento", lambda c, f: Modificacao(tipo="capacidade_recebimento", valor=f)),
    "eficiencia_campo": ("Eficiência de campo", lambda c, f: Modificacao(tipo="eficiencia_campo", valor=f)),
    "produtividade": ("Produtividade da cultura", lambda c, f: Modificacao(tipo="produtividade", valor=f)),
    "capacidade_caminhao": ("Capacidade dos caminhões", lambda c, f: Modificacao(tipo="capacidade_caminhao", valor=f)),
    "velocidade_caminhao": ("Velocidade dos caminhões", lambda c, f: Modificacao(tipo="velocidade_caminhao", valor=f)),
    "tempo_fixo_recebimento": ("Tempo fixo na unidade", lambda c, f: Modificacao(tipo="tempo_fixo_recebimento", valor=f)),
}


def tornado(cfg: OperationConfig, variacao: float = 0.2, metricas: tuple[str, ...] = ("custo_por_t", "duracao_h"),
            parametros: Optional[list[str]] = None, replicacoes: int = 1,
            progresso: Optional[Callable[[int, int, str], None]] = None) -> pd.DataFrame:
    """Varia cada parâmetro em ±variacao mantendo os demais constantes."""
    parametros = parametros or list(PARAMETROS)
    base = executar_cenario(cfg, Cenario(nome="Base"), replicacoes)
    linhas = []
    total = len(parametros) * 2
    i = 0
    for p in parametros:
        rot, fab = PARAMETROS[p]
        res = {}
        for sinal, f in (("baixo", 1 - variacao), ("alto", 1 + variacao)):
            if progresso:
                progresso(i, total, f"{rot} {sinal}")
            i += 1
            rc = executar_cenario(cfg, Cenario(nome=f"{p}_{sinal}", modificacoes=[fab(cfg, f)]), replicacoes)
            res[sinal] = rc.media
        for m in metricas:
            b = base.media.get(m)
            lo, hi = res["baixo"].get(m), res["alto"].get(m)
            linhas.append({
                "parametro": p, "rotulo": rot, "metrica": m, "base": b, "valor_baixo": lo, "valor_alto": hi,
                "delta_baixo_pct": (lo / b - 1) * 100 if b else np.nan,
                "delta_alto_pct": (hi / b - 1) * 100 if b else np.nan,
                "amplitude_pct": abs((hi - lo) / b) * 100 if b else np.nan,
                "concluida_baixo": res["baixo"].get("concluida"), "concluida_alto": res["alto"].get("concluida"),
            })
    return pd.DataFrame(linhas).sort_values(["metrica", "amplitude_pct"], ascending=[True, False]).reset_index(drop=True)


def varredura(cfg: OperationConfig, parametro: str, fatores: list[float], replicacoes: int = 1,
              progresso: Optional[Callable[[int, int, str], None]] = None) -> pd.DataFrame:
    rot, fab = PARAMETROS[parametro]
    linhas = []
    for i, f in enumerate(fatores):
        if progresso:
            progresso(i, len(fatores), f"{rot} × {f:.2f}")
        mod = fab(cfg, f)
        rc = executar_cenario(cfg, Cenario(nome=f"{f:.2f}", modificacoes=[mod]), replicacoes)
        linha = {"fator": f, "descricao": mod.descrever()}
        linha.update(rc.media)
        linhas.append(linha)
    return pd.DataFrame(linhas)
