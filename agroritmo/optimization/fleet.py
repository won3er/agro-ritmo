"""Dimensionamento e distribuição da frota de caminhões (OR-Tools CP-SAT + validação por simulação).

Método
------
1. Para cada tamanho de frota K (1..K_max), um modelo CP-SAT escolhe quantos caminhões de cada
   grupo atendem cada colheitadeira para **maximizar a vazão colhida** (t/h), sujeito a:
   - caminhões disponíveis por grupo;
   - vazão de cada colheitadeira ≤ sua taxa efetiva de colheita;
   - vazão de cada colheitadeira ≤ Σ caminhões alocados × (capacidade ÷ ciclo);
   - Σ vazões ≤ capacidade diária de recebimento (convertida para horas de colheita).
   Em seguida, com a vazão máxima fixada, minimiza o custo horário da frota (lexicográfico).
2. Cada K é resolvido até a otimalidade (status OPTIMAL do CP-SAT); como todos os K do intervalo
   são enumerados, a escolha final é **ótima para o modelo analítico** dentro do intervalo.
3. O modelo analítico não representa filas, variabilidade nem falhas discretas. Por isso os
   melhores candidatos são re-avaliados no simulador de eventos discretos (mesma semente),
   e a recomendação final usa o resultado simulado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd
from ortools.sat.python import cp_model

from ..domain.models import OperationConfig
from ..logging_config import get_logger
from .flow_model import (
    FluxoColheitadeira,
    fluxo_colheitadeiras,
    horas_efetivas_dia,
    razao_recebimento,
    taxa_efetiva_t_h,
    vazao_por_caminhao_t_h,
)

log = get_logger(__name__)
ESCALA = 1000  # kg/h → inteiros

STATUS_PT = {
    cp_model.OPTIMAL: "ÓTIMO",
    cp_model.FEASIBLE: "VIÁVEL (otimalidade não provada)",
    cp_model.INFEASIBLE: "INVIÁVEL",
    cp_model.MODEL_INVALID: "MODELO INVÁLIDO",
    cp_model.UNKNOWN: "DESCONHECIDO (limite de tempo)",
}


@dataclass
class ResultadoOtimizacao:
    metodo: str
    status: str
    restricoes: list[str]
    limitacoes: list[str]
    tabela: pd.DataFrame
    recomendacao: dict = field(default_factory=dict)
    detalhes: dict = field(default_factory=dict)


@dataclass
class SolucaoAlocacao:
    status: str
    vazao_t_h: float
    n: dict[tuple[str, str], int]          # (colheitadeira, grupo) -> caminhões
    r: dict[str, float]                     # vazão por colheitadeira (t/h)
    custo_frota_h: float


def resolver_alocacao(cfg: OperationConfig, max_por_grupo: dict[str, int], total: Optional[int] = None,
                      usar_todos: bool = False, fluxo: Optional[list[FluxoColheitadeira]] = None,
                      limite_s: float = 5.0) -> SolucaoAlocacao:
    """Maximiza a vazão colhida e, em seguida, minimiza o custo horário da frota."""
    fluxo = fluxo or fluxo_colheitadeiras(cfg)
    grupos = {g.id: g for g in cfg.frota}
    cap_receb = cfg.recebimento.capacidade_t_h * min(1.0, razao_recebimento(cfg))

    def construir():
        m = cp_model.CpModel()
        n = {(f.id, gid): m.NewIntVar(0, max_por_grupo.get(gid, 0), f"n_{f.id}_{gid}") for f in fluxo for gid in grupos}
        r = {f.id: m.NewIntVar(0, int(round(f.p_t_h * ESCALA)), f"r_{f.id}") for f in fluxo}
        for gid in grupos:
            soma = sum(n[(f.id, gid)] for f in fluxo)
            if usar_todos:
                m.Add(soma == max_por_grupo.get(gid, 0))
            else:
                m.Add(soma <= max_por_grupo.get(gid, 0))
        if total is not None:
            m.Add(sum(n.values()) == total)
        for f in fluxo:
            m.Add(r[f.id] <= sum(n[(f.id, gid)] * int(round(vazao_por_caminhao_t_h(cfg, g, f) * ESCALA))
                                 for gid, g in grupos.items()))
        m.Add(sum(r.values()) <= int(round(cap_receb * ESCALA)))
        return m, n, r

    # fase 1: vazão máxima
    m, n, r = construir()
    m.Maximize(sum(r.values()))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = limite_s
    s.parameters.num_workers = 4
    st1 = s.Solve(m)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolucaoAlocacao(STATUS_PT.get(st1, str(st1)), 0.0, {}, {}, 0.0)
    r_max = int(s.ObjectiveValue())
    # fase 2: menor custo de frota mantendo a vazão máxima
    m, n, r = construir()
    m.Add(sum(r.values()) >= r_max)
    m.Minimize(sum(n[(f.id, gid)] * int(round(g.custo_fixo_h * 100)) for f in fluxo for gid, g in grupos.items()))
    s2 = cp_model.CpSolver()
    s2.parameters.max_time_in_seconds = limite_s
    s2.parameters.num_workers = 4
    st2 = s2.Solve(m)
    status = cp_model.OPTIMAL if (st1 == cp_model.OPTIMAL and st2 == cp_model.OPTIMAL) else cp_model.FEASIBLE
    n_sol = {k: int(s2.Value(v)) for k, v in n.items()}
    r_sol = {k: s2.Value(v) / ESCALA for k, v in r.items()}
    custo = sum(n_sol[(f.id, gid)] * g.custo_fixo_h for f in fluxo for gid, g in grupos.items())
    return SolucaoAlocacao(STATUS_PT[status], sum(r_sol.values()), n_sol, r_sol, custo)


def estimar_custo(cfg: OperationConfig, sol: SolucaoAlocacao, fluxo: list[FluxoColheitadeira]) -> dict:
    """Custo estimado pelo modelo analítico (mesmas taxas do módulo de custos)."""
    T = cfg.producao_prevista_t
    if sol.vazao_t_h <= 0:
        return {"dias": math.inf, "custo_total": math.inf, "custo_por_t": math.inf}
    j = cfg.janela
    diesel = cfg.custos.preco_diesel_l
    h_ef = horas_efetivas_dia(cfg)
    horas_sistema = T / sol.vazao_t_h
    dias = horas_sistema / h_ef
    grupos = {g.id: g for g in cfg.frota}
    c_colh_fixo = sum(c.custo_fixo_h for c in cfg.colheitadeiras) * j.horas_colheita_dia * dias
    c_colh_var = 0.0
    specs = {c.id: c for c in cfg.colheitadeiras}
    for f in fluxo:
        c = specs[f.id]
        t_h = T * sol.r.get(f.id, 0.0) / sol.vazao_t_h
        horas = t_h / (c.taxa_efetiva_ha_h * f.t_ha)
        c_colh_var += horas * (c.custo_variavel_h + c.consumo_l_h * diesel)
    n_g = {gid: sum(v for (h, g), v in sol.n.items() if g == gid) for gid in grupos}
    c_cam_fixo = sum(n_g[gid] * grupos[gid].custo_fixo_h for gid in grupos) * j.horas_caminhao_dia * dias
    c_cam_km = 0.0
    for (hid, gid), v in sol.n.items():
        if v <= 0:
            continue
        f = next(x for x in fluxo if x.id == hid)
        g = grupos[gid]
        vaz = v * vazao_por_caminhao_t_h(cfg, g, f)
        tot_h = sum(nv * vazao_por_caminhao_t_h(cfg, grupos[gg], f) for (hh, gg), nv in sol.n.items() if hh == hid) or 1
        t_g = T * sol.r.get(hid, 0) / sol.vazao_t_h * vaz / tot_h
        km = t_g / g.capacidade_t * 2 * f.distancia_km
        c_cam_km += km * (g.custo_variavel_km + diesel / g.consumo_km_l)
    outros = 0.0
    for o in cfg.custos.outros_custos:
        outros += o.valor * (math.ceil(dias) if o.tipo == "por_dia" else T if o.tipo == "por_tonelada" else 1)
    receb = cfg.recebimento.custo_recebimento_t * T
    total = c_colh_fixo + c_colh_var + c_cam_fixo + c_cam_km + outros + receb
    return {"dias": dias, "horas_colheita_sistema": horas_sistema, "custo_colheitadeiras": c_colh_fixo + c_colh_var,
            "custo_caminhoes": c_cam_fixo + c_cam_km, "custo_outros": outros + receb, "custo_total": total,
            "custo_por_t": total / T, "composicao": n_g}


def dimensionar_frota(cfg: OperationConfig, max_extra_por_grupo: int = 6, objetivo: str = "custo_por_t",
                      validar: bool = True, replicacoes: int = 1,
                      progresso: Optional[Callable[[int, int, str], None]] = None) -> ResultadoOtimizacao:
    from ..scenarios.compare import executar_cenario
    from ..scenarios.modifications import Cenario, Modificacao

    fluxo = fluxo_colheitadeiras(cfg)
    max_g = {g.id: g.quantidade + max_extra_por_grupo for g in cfg.frota}
    k_max = sum(max_g.values())
    linhas, sols = [], {}
    for k in range(1, k_max + 1):
        sol = resolver_alocacao(cfg, max_g, total=k, fluxo=fluxo)
        if sol.vazao_t_h <= 0:
            continue
        est = estimar_custo(cfg, sol, fluxo)
        sols[k] = (sol, est)
        linhas.append({"caminhoes": k, "composicao": ", ".join(f"{g}={v}" for g, v in est["composicao"].items() if v),
                       "vazao_t_h": sol.vazao_t_h, "dias_estimados": est["dias"], "custo_total_estimado": est["custo_total"],
                       "custo_por_t_estimado": est["custo_por_t"], "status_cpsat": sol.status,
                       "dentro_janela": est["dias"] <= cfg.janela.horizonte_dias,
                       "dentro_prazo": (est["dias"] <= cfg.janela.data_alvo_dias) if cfg.janela.data_alvo_dias else None})
    tab = pd.DataFrame(linhas)
    if tab.empty:
        return ResultadoOtimizacao("CP-SAT", "INVIÁVEL", [], [], tab)
    # vazão máxima possível (colheita ou recebimento limitam): K a partir do qual nada melhora
    vmax = tab["vazao_t_h"].max()
    k_sat = int(tab[tab["vazao_t_h"] >= vmax - 1e-6]["caminhoes"].min())
    candidatos = tab[tab["dentro_janela"]]
    if objetivo == "prazo_custo" and cfg.janela.data_alvo_dias:
        candidatos = candidatos[candidatos["dentro_prazo"] == True]  # noqa: E712
    if candidatos.empty:
        candidatos = tab
    if objetivo == "duracao_h":
        k_ot = int(candidatos.sort_values(["dias_estimados", "custo_por_t_estimado"]).iloc[0]["caminhoes"])
    else:
        k_ot = int(candidatos.sort_values(["custo_por_t_estimado", "dias_estimados"]).iloc[0]["caminhoes"])
    todos_otimos = all(s.status == "ÓTIMO" for s, _ in sols.values())

    rec = {"caminhoes_analitico": k_ot, "composicao_analitico": sols[k_ot][1]["composicao"], "saturacao_k": k_sat,
           "vazao_max_t_h": vmax, "atual": cfg.n_caminhoes}
    sim_tab = pd.DataFrame()
    if validar:
        ks = sorted({max(1, k_ot - 2), max(1, k_ot - 1), k_ot, min(k_max, k_ot + 1), min(k_max, k_ot + 2), cfg.n_caminhoes})
        sim_l = []
        for i, k in enumerate(ks):
            if progresso:
                progresso(i, len(ks), f"Simulando frota com {k} caminhões")
            comp = sols[k][1]["composicao"] if k in sols else None
            if k == cfg.n_caminhoes:
                mods = []
                nome = f"{k} caminhões (atual)"
            else:
                mods = [Modificacao(tipo="composicao_frota", alocacao=comp)]
                nome = f"{k} caminhões"
            rc = executar_cenario(cfg, Cenario(nome=nome, modificacoes=mods), replicacoes)
            sim_l.append({"caminhoes": k, "cenario": nome, "composicao": ", ".join(f"{g}={v}" for g, v in (comp or {}).items() if v)
                          if k != cfg.n_caminhoes else ", ".join(f"{g.id}={g.quantidade}" for g in cfg.frota),
                          "duracao_h": rc.media.get("duracao_h"), "custo_total": rc.media.get("custo_total"),
                          "custo_por_t": rc.media.get("custo_por_t"), "concluida": rc.media.get("concluida"),
                          "espera_colh_caminhao_h": rc.media.get("espera_colh_caminhao_h"),
                          "fila_descarga_h": rc.media.get("fila_descarga_h"), "util_caminhoes": rc.media.get("util_caminhoes")})
        sim_tab = pd.DataFrame(sim_l)
        ok = sim_tab[sim_tab["concluida"] >= 0.999]
        if objetivo == "prazo_custo" and cfg.janela.data_alvo_dias:
            ok = ok[ok["duracao_h"] / 24 <= cfg.janela.data_alvo_dias]
        if not ok.empty:
            chave = "duracao_h" if objetivo == "duracao_h" else "custo_por_t"
            best = ok.sort_values([chave]).iloc[0]
            rec.update({"caminhoes_simulado": int(best["caminhoes"]), "custo_por_t_simulado": float(best["custo_por_t"]),
                        "duracao_h_simulada": float(best["duracao_h"]), "composicao_simulado": best["composicao"]})
    restricoes = [
        "Caminhões disponíveis por grupo (atual + até %d extras por grupo)" % max_extra_por_grupo,
        "Vazão de cada colheitadeira ≤ taxa efetiva de colheita (inclui paradas para descarregar o tanque)",
        "Vazão de cada colheitadeira ≤ Σ caminhões alocados × capacidade ÷ ciclo (enchimento + manobra + ida + descarga + volta)",
        "Σ vazões ≤ capacidade de recebimento × (horas da unidade ÷ horas de colheita), limitada a 1",
        "Janela operacional: dias estimados ≤ horizonte disponível" + (" e ≤ prazo desejado" if objetivo == "prazo_custo" else ""),
    ]
    limitacoes = [
        "Modelo analítico em regime permanente: não representa filas na unidade, variabilidade dos tempos nem falhas discretas.",
        "Distância de transporte = média ponderada pela produção dos talhões.",
        "Disponibilidade mecânica entra como fator médio nas horas efetivas/dia (somente neste modelo analítico).",
        "Por isso os candidatos foram re-simulados; a recomendação final usa o resultado simulado (estimativa sujeita à semente).",
    ]
    status = ("ÓTIMO para o modelo analítico (todos os K enumerados resolvidos com prova de otimalidade)" if todos_otimos
              else "VIÁVEL — ao menos um subproblema atingiu o limite de tempo sem prova de otimalidade")
    return ResultadoOtimizacao(
        metodo="CP-SAT (OR-Tools) sobre modelo de fluxo + enumeração do tamanho da frota + validação por simulação",
        status=status, restricoes=restricoes, limitacoes=limitacoes, tabela=tab, recomendacao=rec,
        detalhes={"simulacao": sim_tab, "fluxo": pd.DataFrame([f.__dict__ for f in fluxo])},
    )


def distribuir_frota_atual(cfg: OperationConfig, validar: bool = True, replicacoes: int = 1) -> ResultadoOtimizacao:
    """Distribuição ótima (modelo analítico) dos caminhões existentes entre as colheitadeiras."""
    from ..scenarios.compare import executar_cenario
    from ..scenarios.modifications import Cenario, Modificacao

    fluxo = fluxo_colheitadeiras(cfg)
    max_g = {g.id: g.quantidade for g in cfg.frota}
    sol = resolver_alocacao(cfg, max_g, usar_todos=True, fluxo=fluxo)
    linhas = []
    mapa: dict[str, str] = {}
    disponiveis = {g.id: [cid for cid, gg in cfg.caminhoes_expandidos() if gg.id == g.id] for g in cfg.frota}
    for f in fluxo:
        for g in cfg.frota:
            v = sol.n.get((f.id, g.id), 0)
            nec = f.p_t_h / vazao_por_caminhao_t_h(cfg, g, f)
            linhas.append({"colheitadeira": f.id, "grupo": g.id, "caminhoes": v, "taxa_colheita_t_h": f.p_t_h,
                           "vazao_por_caminhao_t_h": vazao_por_caminhao_t_h(cfg, g, f),
                           "necessarios_so_deste_grupo": nec, "vazao_atendida_t_h": sol.r.get(f.id, 0.0)})
            for _ in range(v):
                if disponiveis[g.id]:
                    mapa[disponiveis[g.id].pop(0)] = f.id
    tab = pd.DataFrame(linhas)
    rec = {"alocacao": {f.id: sum(sol.n.get((f.id, g.id), 0) for g in cfg.frota) for f in fluxo},
           "mapa_caminhoes": mapa, "vazao_t_h": sol.vazao_t_h}
    det = {}
    if validar:
        pool = executar_cenario(cfg, Cenario(nome="Despacho dinâmico (pool)"), replicacoes)
        ded = executar_cenario(cfg, Cenario(nome="Alocação dedicada otimizada", modificacoes=[
            Modificacao(tipo="alocacao", alocacao=rec["alocacao"], ordem=mapa)]), replicacoes)
        det["simulacao"] = pd.DataFrame([{"cenario": x.nome, **{k: x.media.get(k) for k in (
            "duracao_h", "custo_por_t", "espera_colh_caminhao_h", "caminhao_aguardando_h", "fila_descarga_h", "concluida")}}
            for x in (pool, ded)])
    return ResultadoOtimizacao(
        metodo="CP-SAT (OR-Tools): maximização lexicográfica da vazão e minimização do custo horário da frota",
        status=sol.status, tabela=tab, recomendacao=rec, detalhes=det,
        restricoes=["Todos os caminhões existentes são alocados", "Vazão ≤ taxa de colheita e ≤ capacidade de escoamento",
                    "Σ vazões ≤ capacidade de recebimento ajustada"],
        limitacoes=["Alocação fixa ignora a possibilidade de redistribuir caminhões ao longo do dia; o despacho dinâmico "
                    "do simulador pode superar a alocação fixa — compare na tabela de validação."],
    )


def capacidade_recebimento_necessaria(cfg: OperationConfig) -> dict:
    """Capacidade de recebimento que não limita a colheita (modelo analítico)."""
    fluxo = fluxo_colheitadeiras(cfg)
    demanda = sum(f.p_t_h for f in fluxo)
    razao = razao_recebimento(cfg)
    return {"demanda_pico_t_h": demanda, "capacidade_minima_diaria_t_h": demanda / max(razao, 1e-9),
            "capacidade_atual_t_h": cfg.recebimento.capacidade_t_h,
            "taxas": {f.id: f.p_t_h for f in fluxo},
            "formula": "Σ taxas efetivas das colheitadeiras ÷ (horas da unidade ÷ horas de colheita)"}


__all__ = ["ResultadoOtimizacao", "SolucaoAlocacao", "capacidade_recebimento_necessaria", "dimensionar_frota",
           "distribuir_frota_atual", "estimar_custo", "resolver_alocacao", "taxa_efetiva_t_h"]
