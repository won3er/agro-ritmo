"""Capacidade de recebimento: busca por simulação (heurística de bisseção sobre a capacidade)."""
from __future__ import annotations

from typing import Callable, Optional

import pandas as pd

from ..domain.models import OperationConfig
from .fleet import ResultadoOtimizacao, capacidade_recebimento_necessaria


def buscar_capacidade_recebimento(cfg: OperationConfig, espera_max_min: float = 10.0, fator_min: float = 0.4,
                                  fator_max: float = 2.5, iteracoes: int = 7, replicacoes: int = 1,
                                  progresso: Optional[Callable[[int, int, str], None]] = None) -> ResultadoOtimizacao:
    """Menor capacidade (t/h) cuja espera média por carga na unidade ≤ ``espera_max_min``.

    Bisseção sobre o fator de capacidade, avaliando cada ponto no simulador. Assume que a espera
    diminui com a capacidade (monotonicidade aproximada sob a mesma semente) — por isso o resultado
    é heurístico e acompanhado da tabela de todos os pontos avaliados.
    """
    from ..scenarios.compare import executar_cenario
    from ..scenarios.modifications import Cenario, Modificacao

    pontos = []

    def avaliar(f: float) -> dict:
        rc = executar_cenario(cfg, Cenario(nome=f"{f:.2f}", modificacoes=[Modificacao(tipo="capacidade_recebimento", valor=f)]),
                              replicacoes)
        p = {"fator": f, "capacidade_t_h": cfg.recebimento.capacidade_t_h * f, **{k: rc.media.get(k) for k in (
            "fila_media_min", "fila_descarga_h", "fila_max", "duracao_h", "custo_por_t", "util_recepcao", "concluida")}}
        pontos.append(p)
        return p

    lo, hi = fator_min, fator_max
    p_hi = avaliar(hi)
    if p_hi["fila_media_min"] > espera_max_min:
        status = "HEURÍSTICO — meta não atingida nem com a capacidade máxima avaliada"
        alvo = p_hi
    else:
        p_lo = avaliar(lo)
        if p_lo["fila_media_min"] <= espera_max_min:
            alvo = p_lo
        else:
            alvo = p_hi
            for i in range(iteracoes):
                if progresso:
                    progresso(i, iteracoes, "Bisseção da capacidade de recebimento")
                mid = (lo + hi) / 2
                p = avaliar(mid)
                if p["fila_media_min"] <= espera_max_min:
                    hi, alvo = mid, p
                else:
                    lo = mid
        status = "HEURÍSTICO (bisseção sobre simulação) — precisão de ±%.0f t/h" % ((hi - lo) * cfg.recebimento.capacidade_t_h / 2)
    tab = pd.DataFrame(pontos).sort_values("capacidade_t_h").reset_index(drop=True)
    analitico = capacidade_recebimento_necessaria(cfg)
    return ResultadoOtimizacao(
        metodo="Bisseção sobre o fator de capacidade, avaliando cada ponto no simulador de eventos discretos",
        status=status, tabela=tab,
        recomendacao={"capacidade_t_h": alvo["capacidade_t_h"], "fila_media_min": alvo["fila_media_min"],
                      "meta_espera_min": espera_max_min, **analitico},
        restricoes=[f"Espera média por carga na unidade ≤ {espera_max_min:.0f} min", "Número de moegas mantido",
                    "Demais parâmetros da operação inalterados"],
        limitacoes=["A espera é estimada com a semente configurada; use replicações para reduzir a variância.",
                    "Assume monotonicidade aproximada entre capacidade e espera."],
    )
