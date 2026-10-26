"""Sequenciamento de talhões entre colheitadeiras (OR-Tools CP-SAT com restrições de circuito).

Decide qual colheitadeira colhe cada talhão e em que ordem, minimizando
    α · Σ peso_prioridade(f) · término(f)  +  β · makespan
sujeito a:
* cada talhão colhido por exatamente uma colheitadeira (sem divisão no plano);
* sequência em cada máquina (AddCircuit) com tempos de deslocamento entre talhões;
* início ≥ liberação do talhão (dia de disponibilidade convertido em horas efetivas de colheita);
* duração = área ÷ (capacidade nominal × eficiência) + paradas para descarregar o tanque.

O tempo do modelo é medido em **horas efetivas de colheita** (noites, chuva e esperas por caminhão
não entram). O plano resultante é executado no simulador (regra 'plano') para medir o efeito real.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from ortools.sat.python import cp_model

from ..domain.models import OperationConfig
from ..simulation.engine import FATOR_SINUOSIDADE
from .flow_model import horas_efetivas_dia
from .fleet import STATUS_PT, ResultadoOtimizacao

PESO_PRIORIDADE = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}
OBJETIVOS_SEQ = {
    "prioridade": (1.0, 0.1, "Concluir primeiro os talhões prioritários (Σ peso × término) com leve peso no makespan"),
    "makespan": (0.05, 1.0, "Terminar toda a colheita o mais cedo possível (makespan)"),
    "equilibrado": (1.0, 1.0, "Equilíbrio entre prioridade e tempo total"),
}


@dataclass
class InstanciaSeq:
    talhoes: list[str]
    maquinas: list[str]
    proc: dict[tuple[str, str], int]       # (máquina, talhão) -> min
    setup: dict[tuple[str, str, str], int]  # (máquina, de, para) -> min
    liberacao: dict[str, int]
    peso: dict[str, int]


def construir_instancia(cfg: OperationConfig) -> InstanciaSeq:
    kg = cfg.kg_por_saca
    h_dia = horas_efetivas_dia(cfg)
    proc, setup = {}, {}
    for c in cfg.colheitadeiras:
        for t in cfg.talhoes:
            t_total = t.area_ha * t.t_ha(kg)
            horas = t.area_ha / c.taxa_efetiva_ha_h
            horas += math.ceil(t_total / c.capacidade_tanque_t) * c.tempo_descarga_tanque_min / 60
            proc[(c.id, t.id)] = max(1, int(round(horas * 60)))
            for u in cfg.talhoes:
                if u.id != t.id:
                    d = math.hypot(t.x_km - u.x_km, t.y_km - u.y_km) * FATOR_SINUOSIDADE
                    setup[(c.id, t.id, u.id)] = int(round(d / c.velocidade_deslocamento_km_h * 60))
    lib = {t.id: int(round((t.disponivel_a_partir_dia - 1) * h_dia * 60)) for t in cfg.talhoes}
    return InstanciaSeq([t.id for t in cfg.talhoes], [c.id for c in cfg.colheitadeiras], proc, setup, lib,
                        {t.id: PESO_PRIORIDADE[t.prioridade] for t in cfg.talhoes})


def avaliar_plano(inst: InstanciaSeq, plano: dict[str, list[str]], alfa: float, beta: float) -> dict:
    """Calcula términos e objetivo de um plano (mesma função usada pelo CP-SAT e pela força bruta)."""
    termino, inicio = {}, {}
    for m, seq in plano.items():
        t = 0
        ant = None
        for f in seq:
            s = t + (inst.setup[(m, ant, f)] if ant else 0)
            s = max(s, inst.liberacao[f])
            inicio[f] = s
            t = s + inst.proc[(m, f)]
            termino[f] = t
            ant = f
    ponderado = sum(inst.peso[f] * termino[f] for f in termino)
    makespan = max(termino.values()) if termino else 0
    return {"inicio": inicio, "termino": termino, "ponderado": ponderado, "makespan": makespan,
            "objetivo": alfa * ponderado + beta * makespan}


def _escala(alfa: float, beta: float) -> tuple[int, int]:
    return int(round(alfa * 100)), int(round(beta * 100))


def resolver_sequencia(inst: InstanciaSeq, alfa: float, beta: float, limite_s: float = 10.0) -> tuple[str, dict, dict]:
    m = cp_model.CpModel()
    H = sum(max(inst.proc[(k, f)] for k in inst.maquinas) for f in inst.talhoes) + \
        sum(max(inst.setup.values(), default=0) for _ in inst.talhoes) + max(inst.liberacao.values(), default=0)
    ini = {f: m.NewIntVar(0, H, f"s_{f}") for f in inst.talhoes}
    fim = {f: m.NewIntVar(0, H, f"e_{f}") for f in inst.talhoes}
    pres = {(k, f): m.NewBoolVar(f"p_{k}_{f}") for k in inst.maquinas for f in inst.talhoes}
    for f in inst.talhoes:
        m.AddExactlyOne(pres[(k, f)] for k in inst.maquinas)
        m.Add(ini[f] >= inst.liberacao[f])
        for k in inst.maquinas:
            m.Add(fim[f] == ini[f] + inst.proc[(k, f)]).OnlyEnforceIf(pres[(k, f)])
    for k in inst.maquinas:
        arcos = []
        idx = {f: i + 1 for i, f in enumerate(inst.talhoes)}
        vazio = m.NewBoolVar(f"vazio_{k}")
        arcos.append((0, 0, vazio))  # máquina sem talhões
        for f in inst.talhoes:
            arcos.append((idx[f], idx[f], pres[(k, f)].Not()))
            a0 = m.NewBoolVar(f"a_{k}_0_{f}")
            a1 = m.NewBoolVar(f"a_{k}_{f}_0")
            arcos.append((0, idx[f], a0))
            arcos.append((idx[f], 0, a1))
            m.AddImplication(a0, pres[(k, f)])
            m.AddImplication(a1, pres[(k, f)])
            m.AddImplication(vazio, pres[(k, f)].Not())
            for g in inst.talhoes:
                if g == f:
                    continue
                a = m.NewBoolVar(f"a_{k}_{f}_{g}")
                arcos.append((idx[f], idx[g], a))
                m.AddImplication(a, pres[(k, f)])
                m.AddImplication(a, pres[(k, g)])
                m.Add(ini[g] >= fim[f] + inst.setup[(k, f, g)]).OnlyEnforceIf(a)
        m.AddCircuit(arcos)
    mk = m.NewIntVar(0, H, "makespan")
    for f in inst.talhoes:
        m.Add(mk >= fim[f])
    a_i, b_i = _escala(alfa, beta)
    m.Minimize(a_i * sum(inst.peso[f] * fim[f] for f in inst.talhoes) + b_i * mk)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = limite_s
    s.parameters.num_workers = 8
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return STATUS_PT.get(st, str(st)), {}, {}
    plano = {}
    for k in inst.maquinas:
        fs = [f for f in inst.talhoes if s.Value(pres[(k, f)])]
        plano[k] = sorted(fs, key=lambda f: s.Value(ini[f]))
    info = {"objetivo": s.ObjectiveValue() / 100, "limite_inferior": s.BestObjectiveBound() / 100,
            "tempo_s": s.WallTime(), "status_bruto": st}
    info["gap_pct"] = (abs(info["objetivo"] - info["limite_inferior"]) / max(abs(info["objetivo"]), 1e-9)) * 100
    return STATUS_PT[st], plano, info


def plano_guloso(inst: InstanciaSeq) -> dict[str, list[str]]:
    """Heurística de referência: lista por prioridade, próxima máquina livre (regra padrão do simulador)."""
    ordem = sorted(inst.talhoes, key=lambda f: (-inst.peso[f], f))
    livre = {k: 0 for k in inst.maquinas}
    ultimo = {k: None for k in inst.maquinas}
    plano = {k: [] for k in inst.maquinas}
    for f in ordem:
        k = min(inst.maquinas, key=lambda k: (max(livre[k] + (inst.setup[(k, ultimo[k], f)] if ultimo[k] else 0),
                                                   inst.liberacao[f]), k))
        s = max(livre[k] + (inst.setup[(k, ultimo[k], f)] if ultimo[k] else 0), inst.liberacao[f])
        livre[k] = s + inst.proc[(k, f)]
        ultimo[k] = f
        plano[k].append(f)
    return plano


def forca_bruta(inst: InstanciaSeq, alfa: float, beta: float) -> tuple[float, dict]:
    """Referência exata para instâncias pequenas (usada nos testes)."""
    melhor, melhor_plano = math.inf, {}
    n = len(inst.talhoes)
    for atrib in itertools.product(inst.maquinas, repeat=n):
        grupos = {k: [f for f, a in zip(inst.talhoes, atrib) if a == k] for k in inst.maquinas}
        for perms in itertools.product(*[list(itertools.permutations(grupos[k])) for k in inst.maquinas]):
            plano = {k: list(p) for k, p in zip(inst.maquinas, perms)}
            v = avaliar_plano(inst, plano, alfa, beta)["objetivo"]
            if v < melhor - 1e-9:
                melhor, melhor_plano = v, plano
    return melhor, melhor_plano


def otimizar_sequencia(cfg: OperationConfig, objetivo: str = "prioridade", limite_s: float = 10.0, validar: bool = True,
                       replicacoes: int = 1) -> ResultadoOtimizacao:
    from ..scenarios.compare import executar_cenario
    from ..scenarios.modifications import Cenario, Modificacao

    alfa, beta, desc = OBJETIVOS_SEQ[objetivo]
    inst = construir_instancia(cfg)
    status, plano, info = resolver_sequencia(inst, alfa, beta, limite_s)
    gul = plano_guloso(inst)
    av_g = avaliar_plano(inst, gul, alfa, beta)
    linhas = []
    av = avaliar_plano(inst, plano, alfa, beta) if plano else None
    for k, seq in (plano or {}).items():
        for i, f in enumerate(seq):
            linhas.append({"colheitadeira": k, "ordem": i + 1, "talhao": f, "prioridade": cfg.talhao(f).prioridade,
                           "inicio_h_efetivas": av["inicio"][f] / 60, "termino_h_efetivas": av["termino"][f] / 60,
                           "duracao_h": inst.proc[(k, f)] / 60})
    tab = pd.DataFrame(linhas)
    rec = {"plano": plano, "objetivo": av["objetivo"] if av else None, "objetivo_guloso": av_g["objetivo"],
           "makespan_h": av["makespan"] / 60 if av else None, "makespan_guloso_h": av_g["makespan"] / 60,
           "melhoria_pct": (1 - av["objetivo"] / av_g["objetivo"]) * 100 if av and av_g["objetivo"] else None,
           "plano_guloso": gul}
    det = {"cpsat": info}
    if validar and plano:
        base = executar_cenario(cfg, Cenario(nome="Regra atual do simulador"), replicacoes)
        otm = executar_cenario(cfg, Cenario(nome="Plano CP-SAT", modificacoes=[Modificacao(tipo="sequencia", ordem=plano)]),
                               replicacoes)
        det["simulacao"] = pd.DataFrame([{"cenario": x.nome, **{k: x.media.get(k) for k in (
            "duracao_h", "custo_por_t", "espera_colh_caminhao_h", "concluida")}} for x in (base, otm)])
        # término simulado por prioridade (tempo médio ponderado de conclusão dos talhões)
        for nome, rc in (("base", base), ("otimizado", otm)):
            tl = rc.principal.talhoes
            w = tl["prioridade"].map(PESO_PRIORIDADE)
            det[f"termino_ponderado_h_{nome}"] = float((w * tl["fim_min"].fillna(rc.principal.t_fim)).sum() / w.sum() / 60)
    status_txt = {"ÓTIMO": "ÓTIMO (prova de otimalidade do CP-SAT para o modelo de sequenciamento)",
                  "VIÁVEL (otimalidade não provada)": f"VIÁVEL — melhor solução encontrada em {limite_s:.0f}s "
                                                     f"(gap {info.get('gap_pct', 0):.1f}% para o limite inferior)"}.get(status, status)
    return ResultadoOtimizacao(
        metodo=f"CP-SAT (OR-Tools) com AddCircuit por colheitadeira — objetivo: {desc}",
        status=status_txt, tabela=tab, recomendacao=rec, detalhes=det,
        restricoes=["Cada talhão atribuído a exatamente uma colheitadeira", "Sequência por máquina com tempo de deslocamento",
                    "Início ≥ liberação do talhão (dia → horas efetivas)", "Duração = área ÷ taxa efetiva + descargas do tanque"],
        limitacoes=["Tempo em horas efetivas de colheita: não considera noites, chuva nem espera por caminhões.",
                    "No simulador, uma colheitadeira que termina seu plano pode ajudar em outro talhão (se habilitado).",
                    "O efeito real é medido na validação por simulação."],
    )
