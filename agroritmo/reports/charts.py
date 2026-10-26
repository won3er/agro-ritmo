"""Gráficos estáticos (matplotlib) para o relatório PDF."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ..simulation.records import ROTULOS_ESTADO  # noqa: E402
from ..theme import CORES_ESTADO, SEQ_CENARIOS  # noqa: E402

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#8A949E", "axes.labelcolor": "#2B333B", "xtick.color": "#4A535C",
                     "ytick.color": "#4A535C", "axes.grid": True, "grid.color": "#E3E7EA", "grid.linewidth": 0.6})


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=170)
    plt.close(fig)
    return buf.getvalue()


def producao_acumulada(serie: pd.DataFrame) -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    h = serie["t_min"] / 60
    ax.plot(h, serie["colhido_acum_t"], color="#2FA866", lw=1.8, label="Colhido")
    ax.plot(h, serie["entregue_acum_t"], color="#3D7BE0", lw=1.8, label="Entregue na unidade")
    ax.fill_between(h, serie["entregue_acum_t"], serie["colhido_acum_t"], color="#F0A73A", alpha=0.25,
                    label="Em tanques/caminhões")
    ax.set_xlabel("Horas desde 00:00 do Dia 1")
    ax.set_ylabel("t acumuladas")
    ax.legend(frameon=False, loc="upper left")
    return _png(fig)


def utilizacao(util: pd.DataFrame, chave: str, estados: list[str]) -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 0.35 * len(util) + 1.0))
    esq = pd.Series(0.0, index=util.index)
    for e in estados:
        col = e + "_h"
        if col not in util:
            continue
        ax.barh(util[chave], util[col], left=esq, color=CORES_ESTADO.get(e, "#999"), label=ROTULOS_ESTADO.get(e, e), height=0.6)
        esq = esq + util[col]
    ax.set_xlabel("Horas")
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=7, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.35))
    ax.grid(axis="y", visible=False)
    return _png(fig)


def filas(serie: pd.DataFrame) -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    h = serie["t_min"] / 60
    ax.step(h, serie["n_fila_unidade"], where="post", color="#E0524D", lw=1.2, label="Caminhões na fila da unidade")
    ax.step(h, serie["n_colh_aguardando"], where="post", color="#F0A73A", lw=1.2, label="Colheitadeiras aguardando caminhão")
    ax.set_xlabel("Horas desde 00:00 do Dia 1")
    ax.set_ylabel("Quantidade")
    ax.legend(frameon=False, loc="upper right")
    return _png(fig)


def composicao_custos(resumo: pd.DataFrame) -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 0.32 * len(resumo) + 0.9))
    rot = resumo["categoria"] + " — " + resumo["componente_base"]
    ax.barh(rot, resumo["valor"], color="#38B6C4", height=0.6)
    ax.invert_yaxis()
    ax.set_xlabel("R$")
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(resumo["valor"]):
        ax.text(v, i, f" R$ {v:,.0f}".replace(",", "."), va="center", fontsize=7)
    return _png(fig)


def comparacao_cenarios(tab: pd.DataFrame) -> bytes:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 0.3 * len(tab) + 1.4), sharey=True)
    cores = [SEQ_CENARIOS[i % len(SEQ_CENARIOS)] for i in range(len(tab))]
    axes[0].barh(tab["cenario"], tab["duracao_h"], color=cores, height=0.6)
    axes[0].set_xlabel("Duração (h)")
    axes[1].barh(tab["cenario"], tab["custo_por_t"], color=cores, height=0.6)
    axes[1].set_xlabel("Custo por t (R$/t)")
    axes[0].invert_yaxis()
    for a in axes:
        a.grid(axis="y", visible=False)
    return _png(fig)
