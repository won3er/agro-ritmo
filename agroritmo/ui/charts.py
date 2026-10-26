"""Gráficos interativos (Plotly) da interface."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ..simulation.records import ROTULOS_ESTADO
from ..simulation.results import SimulationResult
from ..theme import CORES_ESTADO, MARCA, SEQ_CENARIOS

LAYOUT = dict(
    template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=MARCA["texto"]),
    margin=dict(l=10, r=10, t=36, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
    hoverlabel=dict(bgcolor=MARCA["painel"]),
)
EIXO = dict(gridcolor="#1f2a31", zerolinecolor="#2a3640")


def _fig(fig: go.Figure, titulo: str = "", altura: int = 320) -> go.Figure:
    fig.update_layout(**LAYOUT, title=dict(text=titulo, font=dict(size=14)), height=altura)
    fig.update_xaxes(**EIXO)
    fig.update_yaxes(**EIXO)
    return fig


def _eixo_tempo(serie: pd.DataFrame) -> pd.Series:
    return serie["t_min"] / 1440 + 1  # dia decimal (1.5 = Dia 1, 12:00)


def producao(serie: pd.DataFrame) -> go.Figure:
    x = _eixo_tempo(serie)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=serie["colhido_acum_t"], name="Colhido", line=dict(color=CORES_ESTADO["colhendo"], width=2)))
    fig.add_trace(go.Scatter(x=x, y=serie["entregue_acum_t"], name="Entregue na unidade", line=dict(color=MARCA["azul"], width=2),
                             fill="tonexty", fillcolor="rgba(240,167,58,0.18)"))
    fig.update_xaxes(title="Dia da operação")
    fig.update_yaxes(title="t acumuladas")
    return _fig(fig, "Evolução da produção (área âmbar = grãos em tanques/caminhões)")


def volumes_em_processo(serie: pd.DataFrame) -> go.Figure:
    x = _eixo_tempo(serie)
    fig = go.Figure()
    for col, nome, cor in [("em_tanques_t", "Em tanques", CORES_ESTADO["colhendo"]),
                           ("em_caminhoes_campo_t", "Em caminhões no campo", CORES_ESTADO["em_carregamento"]),
                           ("em_transito_t", "Em trânsito", CORES_ESTADO["transporte_carregado"]),
                           ("na_fila_t", "Na fila da unidade", CORES_ESTADO["fila_descarga"]),
                           ("em_descarga_t", "Descarregando", CORES_ESTADO["descarregando"])]:
        fig.add_trace(go.Scatter(x=x, y=serie[col], name=nome, stackgroup="v", line=dict(width=0.5, color=cor)))
    fig.update_xaxes(title="Dia da operação")
    fig.update_yaxes(title="t")
    return _fig(fig, "Volume aguardando transporte e descarga")


def filas(serie: pd.DataFrame) -> go.Figure:
    x = _eixo_tempo(serie)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=serie["n_fila_unidade"], name="Caminhões na fila da unidade", line=dict(shape="hv", color=CORES_ESTADO["fila_descarga"])))
    fig.add_trace(go.Scatter(x=x, y=serie["n_aguardando_campo"], name="Caminhões aguardando no campo", line=dict(shape="hv", color=CORES_ESTADO["aguardando_carregamento"])))
    fig.add_trace(go.Scatter(x=x, y=serie["n_colh_aguardando"], name="Colheitadeiras aguardando caminhão", line=dict(shape="hv", color=CORES_ESTADO["aguardando_caminhao"], width=2)))
    fig.update_xaxes(title="Dia da operação")
    fig.update_yaxes(title="Quantidade", rangemode="tozero")
    return _fig(fig, "Filas e esperas ao longo do tempo")


def utilizacao(util: pd.DataFrame, chave: str, estados: list[str], titulo: str) -> go.Figure:
    fig = go.Figure()
    for e in estados:
        col = e + "_h"
        if col in util and util[col].sum() > 0:
            fig.add_trace(go.Bar(y=util[chave], x=util[col], name=ROTULOS_ESTADO.get(e, e), orientation="h",
                                 marker_color=CORES_ESTADO.get(e, "#888"),
                                 hovertemplate="%{y}: %{x:.1f} h<extra>" + ROTULOS_ESTADO.get(e, e) + "</extra>"))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="Horas")
    return _fig(fig, titulo, altura=max(220, 60 + 34 * len(util)))


def gantt(res: SimulationResult, tipo: str | None = None, dia: int | None = None) -> go.Figure:
    sg = res.segmentos.copy()
    if tipo:
        sg = sg[sg["tipo"] == tipo]
    sg = sg[~sg["estado"].isin(["concluida", "concluido"])]
    if dia:
        a, b = (dia - 1) * 1440, dia * 1440
        sg = sg[(sg["fim"] > a) & (sg["inicio"] < b)].copy()
        sg["inicio"] = sg["inicio"].clip(lower=a)
        sg["fim"] = sg["fim"].clip(upper=b)
    base = pd.Timestamp("2000-01-01")
    sg["Início"] = base + pd.to_timedelta(sg["inicio"], unit="m")
    sg["Fim"] = base + pd.to_timedelta(sg["fim"], unit="m")
    sg["Estado"] = sg["estado"].map(ROTULOS_ESTADO).fillna(sg["estado"])
    sg["detalhe"] = sg["talhao"].fillna("") + " " + sg["carga"].fillna("")
    cores = {ROTULOS_ESTADO.get(k, k): v for k, v in CORES_ESTADO.items()}
    fig = px.timeline(sg, x_start="Início", x_end="Fim", y="recurso", color="Estado", color_discrete_map=cores,
                      hover_data={"detalhe": True, "Início": False, "Fim": False})
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(tickformat="D%d %H:%M" if False else "%d/%H:%M", title="dia/hora (dia 01 = Dia 1)")
    return _fig(fig, "Linha do tempo de estados por recurso", altura=max(260, 80 + 26 * sg["recurso"].nunique()))


def custos(resumo: pd.DataFrame) -> go.Figure:
    df = resumo.copy()
    df["rotulo"] = df["categoria"] + " · " + df["componente_base"]
    fig = px.bar(df, x="valor", y="rotulo", orientation="h", color="categoria",
                 color_discrete_sequence=[MARCA["ciano"], MARCA["verde"], MARCA["ambar"], "#9273C9"])
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(title="R$")
    fig.update_traces(hovertemplate="%{y}: R$ %{x:,.2f}<extra></extra>")
    return _fig(fig, "Composição dos custos", altura=max(260, 60 + 30 * len(df)))


def ciclo(cc: pd.DataFrame) -> go.Figure:
    cores = [CORES_ESTADO.get(e, "#888") for e in cc["estado"]]
    fig = go.Figure(go.Bar(x=cc["min_por_carga"], y=cc["etapa"], orientation="h", marker_color=cores,
                           hovertemplate="%{y}: %{x:.1f} min/carga<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="minutos por carga entregue")
    return _fig(fig, "Composição média do ciclo do caminhão", altura=300)


def chegadas(cph: pd.DataFrame) -> go.Figure:
    x = cph["hora"] / 24 + 1
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=cph["t_chegada"], name="t chegando por hora", marker_color=MARCA["azul"]))
    fig.add_trace(go.Scatter(x=x, y=cph["capacidade_t_h"], name="Capacidade de recebimento (t/h)",
                             line=dict(color=MARCA["vermelho"], dash="dash")))
    fig.update_xaxes(title="Dia da operação")
    fig.update_yaxes(title="t/h")
    return _fig(fig, "Chegadas à unidade × capacidade")


def comparacao(tab: pd.DataFrame, metrica: str, rotulo: str, melhor: str | None = None) -> go.Figure:
    cores = [MARCA["verde"] if c == melhor else (SEQ_CENARIOS[1] if t == "decisão" else "#5A636E")
             for c, t in zip(tab["cenario"], tab.get("tipo", ["decisão"] * len(tab)))]
    err = tab.get(metrica + "_ic95")
    fig = go.Figure(go.Bar(x=tab[metrica], y=tab["cenario"], orientation="h", marker_color=cores,
                           error_x=dict(type="data", array=err, visible=err is not None),
                           hovertemplate="%{y}: %{x:,.2f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title=rotulo)
    return _fig(fig, rotulo, altura=max(260, 60 + 28 * len(tab)))


def fronteira(tab: pd.DataFrame, melhor: str | None = None) -> go.Figure:
    df = tab.copy()
    df["tipo"] = df.get("tipo", "decisão")
    fig = px.scatter(df, x="duracao_h", y="custo_por_t", text="cenario", color="tipo",
                     color_discrete_map={"decisão": MARCA["azul"], "condição externa": "#6F8396"})
    fig.update_traces(textposition="top center", marker=dict(size=11))
    if melhor is not None and melhor in set(df["cenario"]):
        r = df[df["cenario"] == melhor].iloc[0]
        fig.add_trace(go.Scatter(x=[r["duracao_h"]], y=[r["custo_por_t"]], mode="markers", name="Melhor (objetivo)",
                                 marker=dict(size=20, color="rgba(0,0,0,0)", line=dict(color=MARCA["verde"], width=3))))
    fig.update_xaxes(title="Duração (h) — menor é melhor")
    fig.update_yaxes(title="Custo por t (R$/t) — menor é melhor")
    return _fig(fig, "Tempo × custo: menor tempo não implica menor custo", altura=420)


def tornado(df: pd.DataFrame, metrica: str, rotulo: str) -> go.Figure:
    d = df[df["metrica"] == metrica].sort_values("amplitude_pct")
    fig = go.Figure()
    fig.add_trace(go.Bar(y=d["rotulo"], x=d["delta_baixo_pct"], name="Parâmetro −", orientation="h", marker_color=MARCA["azul"]))
    fig.add_trace(go.Bar(y=d["rotulo"], x=d["delta_alto_pct"], name="Parâmetro +", orientation="h", marker_color=MARCA["ambar"]))
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title=f"Variação de {rotulo} (%) em relação à base")
    return _fig(fig, f"Sensibilidade — {rotulo}", altura=max(280, 60 + 34 * len(d)))


def varredura(df: pd.DataFrame, rotulo: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["descricao"], y=df["duracao_h"], name="Duração (h)", line=dict(color=MARCA["azul"]), yaxis="y"))
    fig.add_trace(go.Scatter(x=df["descricao"], y=df["custo_por_t"], name="Custo por t (R$/t)", line=dict(color=MARCA["ambar"]),
                             yaxis="y2"))
    fig.update_layout(yaxis=dict(title="Duração (h)"), yaxis2=dict(title="R$/t", overlaying="y", side="right", showgrid=False))
    return _fig(fig, f"Varredura — {rotulo}", altura=360)


def frota(tab: pd.DataFrame, sim: pd.DataFrame | None) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=tab["caminhoes"], y=tab["custo_por_t_estimado"], name="Custo/t estimado (modelo analítico)",
                             mode="lines+markers", line=dict(color=MARCA["ambar"], dash="dot")))
    if sim is not None and len(sim):
        fig.add_trace(go.Scatter(x=sim["caminhoes"], y=sim["custo_por_t"], name="Custo/t simulado", mode="lines+markers",
                                 line=dict(color=MARCA["verde"], width=3)))
    fig.add_trace(go.Bar(x=tab["caminhoes"], y=tab["dias_estimados"], name="Dias estimados", yaxis="y2",
                         marker_color="rgba(61,123,224,0.35)"))
    fig.update_layout(yaxis=dict(title="R$/t"), yaxis2=dict(title="dias", overlaying="y", side="right", showgrid=False))
    fig.update_xaxes(title="Caminhões na frota", dtick=1)
    return _fig(fig, "Tamanho da frota × custo por tonelada × duração", altura=380)


def calibracao(av: pd.DataFrame, observado: float, rotulo: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=av["fator"], y=av["simulado"], mode="markers+lines", name="Simulado", line=dict(color=MARCA["azul"])))
    fig.add_hline(y=observado, line=dict(color=MARCA["verde"], dash="dash"), annotation_text="Observado")
    fig.update_xaxes(title="Fator aplicado ao parâmetro")
    fig.update_yaxes(title=rotulo)
    return _fig(fig, "Busca de calibração (seção áurea)", altura=320)
