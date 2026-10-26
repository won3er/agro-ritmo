"""Exportação de resultados para Excel e CSV (zip)."""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from .. import __version__
from ..analytics import (
    calcular_custos,
    calcular_kpis,
    gargalos_df,
    identificar_gargalos,
    kpis_df,
    serie_temporal,
    utilizacao_caminhoes,
    utilizacao_colheitadeiras,
)
from ..analytics.bottlenecks import Gargalo
from ..data.calibration import tabela_parametros
from ..domain.units import formatar_relogio
from ..simulation import SimulationResult, hash_resultado

ROTULO_TIPO = {"medido": "Medido na simulação", "calculado": "Calculado", "informado": "Informado", "estimado": "Estimado"}


@dataclass
class PacoteRelatorio:
    """Tudo o que um relatório precisa — calculado uma vez e reutilizado em Excel, CSV e PDF."""
    res: SimulationResult
    kpis: pd.DataFrame
    custos: pd.DataFrame
    gargalos: list[Gargalo]
    serie: pd.DataFrame
    util_colheitadeiras: pd.DataFrame
    util_caminhoes: pd.DataFrame
    hash: str
    comparacao: Optional[pd.DataFrame] = None
    otimizacao: dict = field(default_factory=dict)
    gerado_em: str = field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M"))

    @classmethod
    def montar(cls, res: SimulationResult, gargalos: Optional[list[Gargalo]] = None,
               comparacao: Optional[pd.DataFrame] = None, otimizacao: Optional[dict] = None) -> "PacoteRelatorio":
        custos = calcular_custos(res)
        kp = calcular_kpis(res, float(custos["valor"].sum()))
        return cls(res=res, kpis=kpis_df(kp), custos=custos, gargalos=gargalos if gargalos is not None else identificar_gargalos(res),
                   serie=serie_temporal(res, 15.0), util_colheitadeiras=utilizacao_colheitadeiras(res),
                   util_caminhoes=utilizacao_caminhoes(res), hash=hash_resultado(res), comparacao=comparacao,
                   otimizacao=otimizacao or {})


def _tabelas(p: PacoteRelatorio) -> dict[str, pd.DataFrame]:
    res = p.res
    cfg = res.config
    resumo = pd.DataFrame([
        {"campo": "Operação", "valor": cfg.nome},
        {"campo": "Cultura", "valor": cfg.crop.nome},
        {"campo": "Origem dos dados", "valor": cfg.origem_dados.value},
        {"campo": "Semente aleatória", "valor": cfg.simulacao.semente},
        {"campo": "Hash do resultado (reprodutibilidade)", "valor": p.hash},
        {"campo": "Versão do AgroRitmo", "valor": __version__},
        {"campo": "Gerado em", "valor": p.gerado_em},
        {"campo": "Concluída na janela", "valor": "sim" if res.concluida else "não"},
        {"campo": "Início da colheita", "valor": formatar_relogio(res.t_inicio)},
        {"campo": "Fim da operação", "valor": formatar_relogio(res.t_fim)},
    ])
    k = p.kpis.copy()
    k["tipo"] = k["tipo"].map(ROTULO_TIPO)
    ev = res.eventos.copy()
    sg = res.segmentos.copy()
    sg.insert(4, "inicio_relogio", sg["inicio"].map(formatar_relogio))
    sg.insert(6, "fim_relogio", sg["fim"].map(formatar_relogio))
    cg = res.cargas.copy()
    for c in ("t_inicio_carregamento", "t_saida_campo", "t_chegada_unidade", "t_inicio_descarga", "t_fim_descarga"):
        cg[c.replace("t_", "rel_", 1)] = cg[c].map(lambda v: formatar_relogio(v) if pd.notna(v) else "")
    out = {
        "Resumo": resumo,
        "Indicadores": k,
        "Premissas": tabela_parametros(cfg),
        "Custos": p.custos,
        "Gargalos": gargalos_df(p.gargalos),
        "Utilizacao_colheitadeiras": p.util_colheitadeiras,
        "Utilizacao_caminhoes": p.util_caminhoes,
        "Talhoes": res.talhoes,
        "Cargas": cg,
        "Eventos": ev,
        "Estados": sg,
        "Serie_temporal": p.serie,
        "Configuracao_JSON": pd.DataFrame([{"config_json": cfg.model_dump_json(indent=1)}]),
    }
    if p.comparacao is not None and len(p.comparacao):
        out["Cenarios"] = p.comparacao
    for nome, df in p.otimizacao.items():
        if isinstance(df, pd.DataFrame):
            out[f"Otim_{nome}"[:31]] = df
    return out


def exportar_excel(p: PacoteRelatorio) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nome, df in _tabelas(p).items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
            ws = w.sheets[nome[:31]]
            for i, col in enumerate(df.columns, start=1):
                largura = min(60, max(10, len(str(col)) + 2,
                                      int(df[col].astype(str).str.len().quantile(0.9)) + 2 if len(df) else 10))
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = largura
            ws.freeze_panes = "A2"
    return buf.getvalue()


def exportar_csv_zip(p: PacoteRelatorio) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, df in _tabelas(p).items():
            z.writestr(f"{nome.lower()}.csv", df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
        z.writestr("configuracao.json", p.res.config.model_dump_json(indent=2))
        z.writestr("LEIA-ME.txt", (
            "AgroRitmo — exportação de resultados\n"
            f"Operação: {p.res.config.nome}\nSemente: {p.res.config.simulacao.semente}\nHash: {p.hash}\n"
            "CSV com separador ';' e decimal ','. Tempos em minutos desde 00:00 do Dia 1 (colunas t_*).\n"
            "Para reproduzir: importe configuracao.json no AgroRitmo e simule com a mesma semente.\n").encode("utf-8"))
    return buf.getvalue()


def exportar_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def config_json(p: PacoteRelatorio) -> bytes:
    return json.dumps(json.loads(p.res.config.model_dump_json()), indent=2, ensure_ascii=False).encode("utf-8")
