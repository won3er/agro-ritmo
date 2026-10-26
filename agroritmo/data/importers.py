"""Importação de dados próprios (CSV/Excel) com validação de colunas, unidades e consistência."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
from pydantic import ValidationError

from ..domain.models import Colheitadeira, OperationConfig, OrigemDado, Talhao, TipoCaminhao


@dataclass
class Coluna:
    nome: str
    tipo: type
    obrigatoria: bool
    unidade: str
    descricao: str
    minimo: Optional[float] = None
    maximo: Optional[float] = None
    exemplo: Any = None


MODELOS: dict[str, list[Coluna]] = {
    "talhoes": [
        Coluna("id", str, True, "—", "Identificador único do talhão", exemplo="T01"),
        Coluna("nome", str, False, "—", "Nome do talhão", exemplo="Sede Norte"),
        Coluna("area_ha", float, True, "ha", "Área a colher", 0.01, 20000, 150),
        Coluna("produtividade_sc_ha", float, True, "sc/ha", "Produtividade estimada", 1, 400, 62),
        Coluna("prioridade", int, False, "1–5", "1 = mais alta", 1, 5, 2),
        Coluna("distancia_km", float, True, "km", "Distância até a unidade de recebimento", 0.1, 500, 12),
        Coluna("x_km", float, False, "km", "Posição esquemática X", -500, 500, 3),
        Coluna("y_km", float, False, "km", "Posição esquemática Y", -500, 500, 7),
        Coluna("disponivel_a_partir_dia", int, False, "dia", "Primeiro dia em que pode ser colhido", 1, 365, 1),
    ],
    "colheitadeiras": [
        Coluna("id", str, True, "—", "Identificador único", exemplo="C1"),
        Coluna("nome", str, False, "—", "Nome", exemplo="Colheitadeira 1"),
        Coluna("modelo", str, False, "—", "Modelo", exemplo="—"),
        Coluna("capacidade_campo_ha_h", float, True, "ha/h", "Capacidade de campo nominal", 0.1, 30, 7.5),
        Coluna("eficiencia_campo", float, False, "0–1", "Eficiência operacional de campo", 0.05, 1, 0.75),
        Coluna("capacidade_tanque_t", float, True, "t", "Capacidade do tanque graneleiro", 0.5, 40, 11),
        Coluna("tempo_descarga_tanque_min", float, False, "min", "Tempo para esvaziar o tanque", 0.1, 30, 2.5),
        Coluna("velocidade_deslocamento_km_h", float, False, "km/h", "Velocidade entre talhões", 1, 40, 15),
        Coluna("disponibilidade_mecanica", float, False, "0–1", "Disponibilidade mecânica", 0.3, 1, 0.95),
        Coluna("mttr_h", float, False, "h", "Tempo médio de reparo", 0.1, 200, 2.5),
        Coluna("parada_programada_min_dia", float, False, "min/dia", "Manutenção diária no início do turno", 0, 600, 30),
        Coluna("custo_fixo_h", float, False, "R$/h", "Custo por hora mobilizada", 0, 1e5, 250),
        Coluna("custo_variavel_h", float, False, "R$/h", "Custo por hora colhendo", 0, 1e5, 150),
        Coluna("consumo_l_h", float, False, "L/h", "Consumo de combustível", 0, 500, 35),
    ],
    "caminhoes": [
        Coluna("id", str, True, "—", "Prefixo do grupo", exemplo="CAR"),
        Coluna("nome", str, False, "—", "Descrição do grupo", exemplo="Carreta graneleira"),
        Coluna("quantidade", int, True, "un", "Quantidade de caminhões do grupo", 0, 200, 4),
        Coluna("capacidade_t", float, True, "t", "Capacidade de carga", 1, 80, 32),
        Coluna("velocidade_carregado_km_h", float, False, "km/h", "Velocidade média carregado", 1, 100, 38),
        Coluna("velocidade_vazio_km_h", float, False, "km/h", "Velocidade média vazio", 1, 120, 50),
        Coluna("tempo_manobra_min", float, False, "min", "Posicionamento junto à colheitadeira", 0, 60, 3),
        Coluna("disponibilidade_mecanica", float, False, "0–1", "Disponibilidade mecânica", 0.3, 1, 0.97),
        Coluna("mttr_h", float, False, "h", "Tempo médio de reparo", 0.1, 200, 3),
        Coluna("custo_fixo_h", float, False, "R$/h", "Custo por hora mobilizada", 0, 1e5, 115),
        Coluna("custo_variavel_km", float, False, "R$/km", "Custo por km", 0, 1e3, 1.5),
        Coluna("consumo_km_l", float, False, "km/L", "Rendimento de combustível", 0.1, 50, 2.2),
    ],
    "observacoes": [
        Coluna("metrica", str, True, "—", "Código da métrica observada (ver aba Instruções)", exemplo="vazao_t_dia"),
        Coluna("valor", float, True, "conforme métrica", "Valor observado", exemplo=410),
        Coluna("unidade", str, False, "—", "Unidade", exemplo="t/dia"),
        Coluna("data", str, False, "AAAA-MM-DD", "Data da observação", exemplo="2026-02-15"),
        Coluna("fonte", str, False, "—", "Origem do dado (balança, telemetria...)", exemplo="Balança do armazém"),
        Coluna("notas", str, False, "—", "Observações", exemplo=""),
    ],
}

MODELOS_CLASSES = {"talhoes": Talhao, "colheitadeiras": Colheitadeira, "caminhoes": TipoCaminhao}


@dataclass
class RelatorioImportacao:
    tabela: str
    linhas_lidas: int = 0
    erros: list[dict] = field(default_factory=list)
    avisos: list[dict] = field(default_factory=list)
    dados: Optional[pd.DataFrame] = None

    @property
    def ok(self) -> bool:
        return not self.erros

    def resumo(self) -> pd.DataFrame:
        return pd.DataFrame([{"nivel": "erro", **e} for e in self.erros] + [{"nivel": "aviso", **a} for a in self.avisos],
                            columns=["nivel", "linha", "coluna", "mensagem"])


def _ler(arquivo: Any, nome: str, aba: Optional[str] = None) -> pd.DataFrame:
    nome = (nome or "").lower()
    if nome.endswith((".xlsx", ".xls")):
        return pd.read_excel(arquivo, sheet_name=aba or 0, dtype=str)
    if isinstance(arquivo, (bytes, bytearray)):
        arquivo = io.BytesIO(arquivo)
    return pd.read_csv(arquivo, sep=None, engine="python", dtype=str, encoding="utf-8-sig")


def _num(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    return float(s)


def validar_tabela(df: pd.DataFrame, tabela: str) -> RelatorioImportacao:
    spec = MODELOS[tabela]
    rel = RelatorioImportacao(tabela=tabela, linhas_lidas=len(df))
    df = df.rename(columns=lambda c: str(c).strip().lower())
    faltando = [c.nome for c in spec if c.obrigatoria and c.nome not in df.columns]
    for c in faltando:
        rel.erros.append({"linha": None, "coluna": c, "mensagem": "Coluna obrigatória ausente"})
    desconhecidas = [c for c in df.columns if c not in {s.nome for s in spec}]
    for c in desconhecidas:
        rel.avisos.append({"linha": None, "coluna": c, "mensagem": "Coluna desconhecida ignorada"})
    if faltando:
        return rel
    registros = []
    for i, row in df.iterrows():
        linha = int(i) + 2  # cabeçalho = linha 1
        if all(pd.isna(row.get(c.nome)) or str(row.get(c.nome)).strip() == "" for c in spec):
            continue
        reg: dict[str, Any] = {}
        for c in spec:
            bruto = row.get(c.nome)
            vazio = bruto is None or (isinstance(bruto, float) and pd.isna(bruto)) or str(bruto).strip() == ""
            if vazio:
                if c.obrigatoria:
                    rel.erros.append({"linha": linha, "coluna": c.nome, "mensagem": "Campo obrigatório vazio"})
                continue
            if c.tipo is str:
                reg[c.nome] = str(bruto).strip()
                continue
            try:
                v = _num(bruto)
                if c.tipo is int:
                    if abs(v - round(v)) > 1e-9:
                        raise ValueError
                    v = int(round(v))
            except (ValueError, TypeError):
                rel.erros.append({"linha": linha, "coluna": c.nome, "mensagem": f"Valor não numérico: '{bruto}' (unidade {c.unidade})"})
                continue
            if c.minimo is not None and v < c.minimo or c.maximo is not None and v > c.maximo:
                rel.erros.append({"linha": linha, "coluna": c.nome,
                                  "mensagem": f"Valor {v} fora do intervalo [{c.minimo}, {c.maximo}] {c.unidade}"})
                continue
            reg[c.nome] = v
        reg["_linha"] = linha
        registros.append(reg)
    # unicidade e validação de domínio
    if tabela in MODELOS_CLASSES:
        ids = [r.get("id") for r in registros]
        for r in registros:
            if r.get("id") and ids.count(r["id"]) > 1:
                rel.erros.append({"linha": r["_linha"], "coluna": "id", "mensagem": f"ID duplicado: {r['id']}"})
        for r in registros:
            dados = {k: v for k, v in r.items() if k != "_linha"}
            try:
                MODELOS_CLASSES[tabela].model_validate(dados)
            except ValidationError as e:
                for err in e.errors():
                    rel.erros.append({"linha": r["_linha"], "coluna": ".".join(str(x) for x in err["loc"]), "mensagem": err["msg"]})
    if tabela == "talhoes":
        for r in registros:
            if "x_km" not in r and "y_km" not in r:
                rel.avisos.append({"linha": r["_linha"], "coluna": "x_km/y_km",
                                   "mensagem": "Posição não informada: deslocamento entre talhões será considerado nulo"})
    rel.dados = pd.DataFrame(registros).drop(columns=["_linha"], errors="ignore")
    return rel


def importar_arquivo(arquivo: Any, nome_arquivo: str, tabela: str, aba: Optional[str] = None) -> RelatorioImportacao:
    try:
        df = _ler(arquivo, nome_arquivo, aba)
    except Exception as exc:  # noqa: BLE001 - mensagem amigável para o usuário
        rel = RelatorioImportacao(tabela=tabela)
        rel.erros.append({"linha": None, "coluna": None, "mensagem": f"Não foi possível ler o arquivo: {exc}"})
        return rel
    return validar_tabela(df, tabela)


def importar_operacao_excel(arquivo: Any, base: OperationConfig) -> tuple[Optional[OperationConfig], list[RelatorioImportacao]]:
    """Lê um workbook com abas talhoes / colheitadeiras / caminhoes e substitui essas listas na operação base."""
    xls = pd.ExcelFile(arquivo)
    relatorios = []
    d = base.model_dump()
    alvo = {"talhoes": "talhoes", "colheitadeiras": "colheitadeiras", "caminhoes": "frota"}
    for aba, campo in alvo.items():
        if aba not in xls.sheet_names:
            continue
        rel = validar_tabela(pd.read_excel(xls, sheet_name=aba, dtype=str), aba)
        relatorios.append(rel)
        if rel.ok and rel.dados is not None and len(rel.dados):
            d[campo] = [{k: v for k, v in r.items() if not (isinstance(v, float) and pd.isna(v))} for r in rel.dados.to_dict("records")]
    if any(not r.ok for r in relatorios) or not relatorios:
        if not relatorios:
            r = RelatorioImportacao(tabela="workbook")
            r.erros.append({"linha": None, "coluna": None, "mensagem": "Nenhuma aba reconhecida (talhoes, colheitadeiras, caminhoes)"})
            relatorios.append(r)
        return None, relatorios
    d["origem_dados"] = OrigemDado.IMPORTADO.value
    d["simulacao"]["plano_sequencia"] = {}
    d["simulacao"]["alocacao"] = {}
    d["simulacao"]["alocacao_caminhoes"] = {}
    d["simulacao"]["modo_alocacao"] = "pool"
    d["eventos"] = []
    try:
        return OperationConfig.model_validate(d), relatorios
    except ValidationError as e:
        r = RelatorioImportacao(tabela="operacao")
        for err in e.errors():
            r.erros.append({"linha": None, "coluna": ".".join(str(x) for x in err["loc"]), "mensagem": err["msg"]})
        relatorios.append(r)
        return None, relatorios


def modelo_df(tabela: str) -> pd.DataFrame:
    return pd.DataFrame([{c.nome: c.exemplo for c in MODELOS[tabela]}])


def dicionario_df(tabela: str) -> pd.DataFrame:
    return pd.DataFrame([{"coluna": c.nome, "obrigatoria": "sim" if c.obrigatoria else "não", "unidade": c.unidade,
                          "minimo": c.minimo, "maximo": c.maximo, "descricao": c.descricao} for c in MODELOS[tabela]])


def modelo_csv(tabela: str) -> bytes:
    return modelo_df(tabela).to_csv(index=False, sep=";").encode("utf-8-sig")


def modelo_excel() -> bytes:
    from .calibration import METRICAS_OBSERVAVEIS

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        instr = [{"item": "Como usar", "descricao": "Preencha as abas talhoes, colheitadeiras e caminhoes (uma linha por item). "
                                                     "Valores na primeira linha são EXEMPLOS — substitua pelos seus."},
                 {"item": "Decimais", "descricao": "Vírgula ou ponto são aceitos."}]
        instr += [{"item": f"métrica: {k}", "descricao": f"{v['rotulo']} ({v['unidade']})"} for k, v in METRICAS_OBSERVAVEIS.items()]
        pd.DataFrame(instr).to_excel(w, sheet_name="instrucoes", index=False)
        for t in ("talhoes", "colheitadeiras", "caminhoes", "observacoes"):
            modelo_df(t).to_excel(w, sheet_name=t, index=False)
            dicionario_df(t).to_excel(w, sheet_name=f"dic_{t}", index=False)
    return buf.getvalue()
