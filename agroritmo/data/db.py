"""Persistência em SQLite (biblioteca padrão — sem ORM, o esquema é pequeno e estável).

Tabelas: operacoes, execucoes, observacoes, calibracoes.
Caminho: variável de ambiente ``AGRORITMO_DB`` ou ``data/agroritmo.db`` na raiz do projeto.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd

from ..domain.models import OperationConfig
from ..logging_config import get_logger

log = get_logger(__name__)

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMA = """
CREATE TABLE IF NOT EXISTS operacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    origem TEXT NOT NULL,
    config_json TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operacao_id INTEGER REFERENCES operacoes(id) ON DELETE SET NULL,
    nome TEXT NOT NULL,
    semente INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    kpis_json TEXT NOT NULL,
    hash TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operacao_id INTEGER NOT NULL REFERENCES operacoes(id) ON DELETE CASCADE,
    metrica TEXT NOT NULL,
    valor REAL NOT NULL,
    unidade TEXT,
    data TEXT,
    fonte TEXT,
    notas TEXT,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calibracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operacao_id INTEGER REFERENCES operacoes(id) ON DELETE CASCADE,
    metrica TEXT NOT NULL,
    parametro TEXT NOT NULL,
    fator REAL NOT NULL,
    observado REAL NOT NULL,
    simulado_antes REAL,
    simulado_depois REAL,
    operacao_calibrada_id INTEGER,
    criado_em TEXT NOT NULL
);
"""


def caminho_db() -> Path:
    return Path(os.environ.get("AGRORITMO_DB", RAIZ / "data" / "agroritmo.db"))


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, caminho: Optional[Path | str] = None):
        self.caminho = Path(caminho) if caminho else caminho_db()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ------------------------------------------------------------------ operações
    def salvar_operacao(self, cfg: OperationConfig) -> int:
        js = cfg.model_dump_json()
        with self._con() as c:
            row = c.execute("SELECT id FROM operacoes WHERE nome = ?", (cfg.nome,)).fetchone()
            if row:
                c.execute("UPDATE operacoes SET config_json = ?, origem = ?, atualizado_em = ? WHERE id = ?",
                          (js, cfg.origem_dados.value, _agora(), row["id"]))
                log.info("Operação atualizada: %s (id %s)", cfg.nome, row["id"])
                return int(row["id"])
            cur = c.execute("INSERT INTO operacoes (nome, origem, config_json, criado_em, atualizado_em) VALUES (?,?,?,?,?)",
                            (cfg.nome, cfg.origem_dados.value, js, _agora(), _agora()))
            log.info("Operação criada: %s (id %s)", cfg.nome, cur.lastrowid)
            return int(cur.lastrowid)

    def listar_operacoes(self) -> pd.DataFrame:
        with self._con() as c:
            rows = c.execute("SELECT id, nome, origem, criado_em, atualizado_em FROM operacoes ORDER BY atualizado_em DESC").fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=["id", "nome", "origem", "criado_em", "atualizado_em"])

    def carregar_operacao(self, ident: int | str) -> OperationConfig:
        campo = "id" if isinstance(ident, int) else "nome"
        with self._con() as c:
            row = c.execute(f"SELECT config_json FROM operacoes WHERE {campo} = ?", (ident,)).fetchone()
        if not row:
            raise KeyError(f"Operação não encontrada: {ident}")
        return OperationConfig.model_validate_json(row["config_json"])

    def id_operacao(self, nome: str) -> Optional[int]:
        with self._con() as c:
            row = c.execute("SELECT id FROM operacoes WHERE nome = ?", (nome,)).fetchone()
        return int(row["id"]) if row else None

    def excluir_operacao(self, ident: int) -> None:
        with self._con() as c:
            c.execute("DELETE FROM operacoes WHERE id = ?", (ident,))

    # ------------------------------------------------------------------ execuções
    def registrar_execucao(self, cfg: OperationConfig, kpis: dict, hash_: str, nome: str = "Simulação",
                           operacao_id: Optional[int] = None) -> int:
        operacao_id = operacao_id or self.id_operacao(cfg.nome)
        with self._con() as c:
            cur = c.execute(
                "INSERT INTO execucoes (operacao_id, nome, semente, config_json, kpis_json, hash, criado_em) VALUES (?,?,?,?,?,?,?)",
                (operacao_id, nome, cfg.simulacao.semente, cfg.model_dump_json(), json.dumps(kpis, default=float), hash_, _agora()))
            return int(cur.lastrowid)

    def listar_execucoes(self, operacao_id: Optional[int] = None) -> pd.DataFrame:
        q = ("SELECT e.id, e.nome, o.nome AS operacao, e.semente, e.hash, e.kpis_json, e.criado_em FROM execucoes e "
             "LEFT JOIN operacoes o ON o.id = e.operacao_id")
        args: tuple = ()
        if operacao_id is not None:
            q += " WHERE e.operacao_id = ?"
            args = (operacao_id,)
        q += " ORDER BY e.id DESC"
        with self._con() as c:
            rows = [dict(r) for r in c.execute(q, args).fetchall()]
        for r in rows:
            k = json.loads(r.pop("kpis_json"))
            r["duracao_h"] = k.get("duracao_h")
            r["custo_por_t"] = k.get("custo_por_t")
            r["t_entregues"] = k.get("t_entregues")
        return pd.DataFrame(rows)

    def carregar_execucao(self, ident: int) -> tuple[OperationConfig, dict, str]:
        with self._con() as c:
            row = c.execute("SELECT config_json, kpis_json, hash FROM execucoes WHERE id = ?", (ident,)).fetchone()
        if not row:
            raise KeyError(f"Execução não encontrada: {ident}")
        return OperationConfig.model_validate_json(row["config_json"]), json.loads(row["kpis_json"]), row["hash"]

    # ------------------------------------------------------------------ observações (dados reais)
    def adicionar_observacao(self, operacao_id: int, metrica: str, valor: float, unidade: str = "", data: str = "",
                             fonte: str = "", notas: str = "") -> int:
        with self._con() as c:
            cur = c.execute(
                "INSERT INTO observacoes (operacao_id, metrica, valor, unidade, data, fonte, notas, criado_em) VALUES (?,?,?,?,?,?,?,?)",
                (operacao_id, metrica, float(valor), unidade, data, fonte, notas, _agora()))
            return int(cur.lastrowid)

    def listar_observacoes(self, operacao_id: int) -> pd.DataFrame:
        with self._con() as c:
            rows = c.execute("SELECT id, metrica, valor, unidade, data, fonte, notas, criado_em FROM observacoes "
                             "WHERE operacao_id = ? ORDER BY id", (operacao_id,)).fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=["id", "metrica", "valor", "unidade", "data", "fonte", "notas", "criado_em"])

    def excluir_observacao(self, ident: int) -> None:
        with self._con() as c:
            c.execute("DELETE FROM observacoes WHERE id = ?", (ident,))

    def registrar_calibracao(self, operacao_id: Optional[int], metrica: str, parametro: str, fator: float, observado: float,
                             antes: float, depois: float, calibrada_id: Optional[int]) -> int:
        with self._con() as c:
            cur = c.execute(
                "INSERT INTO calibracoes (operacao_id, metrica, parametro, fator, observado, simulado_antes, simulado_depois, "
                "operacao_calibrada_id, criado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                (operacao_id, metrica, parametro, fator, observado, antes, depois, calibrada_id, _agora()))
            return int(cur.lastrowid)

    def listar_calibracoes(self, operacao_id: int) -> pd.DataFrame:
        with self._con() as c:
            rows = c.execute("SELECT * FROM calibracoes WHERE operacao_id = ? ORDER BY id DESC", (operacao_id,)).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
