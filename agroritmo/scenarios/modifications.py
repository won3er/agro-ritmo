"""Modificações declarativas aplicadas sobre uma configuração base para gerar cenários."""
from __future__ import annotations

import copy
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..domain.models import OperationConfig

TipoMod = Literal[
    "caminhoes_extra", "caminhoes_total", "colheitadeira_extra", "capacidade_recebimento", "moegas",
    "fator_distancia", "disponibilidade", "chuva", "falha_equipamento", "produtividade", "sequencia",
    "jornada_caminhoes", "horas_colheita", "alocacao", "eficiencia_campo", "capacidade_caminhao",
    "velocidade_caminhao", "tempo_fixo_recebimento", "horario_recebimento", "composicao_frota", "semente",
]


def _hh(h: float) -> str:
    m = int(round(h * 60))
    return f"{m // 60}h{m % 60:02d}" if m % 60 else f"{m // 60}h"


class Modificacao(BaseModel):
    tipo: TipoMod
    valor: Optional[float] = None
    dia: Optional[int] = None
    hora: Optional[float] = None
    duracao_h: Optional[float] = None
    recurso_id: Optional[str] = None
    inicio_h: Optional[float] = None
    fim_h: Optional[float] = None
    ordem: Any = None  # 'reversa' | 'proximidade' | 'prioridade' | dict[colheitadeira -> [talhões]]
    alocacao: Optional[dict[str, int]] = None

    def descrever(self) -> str:
        v = self.valor
        d = {
            "caminhoes_extra": lambda: f"{'+' if (v or 0) >= 0 else ''}{int(v)} caminhão(ões)",
            "caminhoes_total": lambda: f"frota total = {int(v)} caminhões",
            "colheitadeira_extra": lambda: f"+{int(v)} colheitadeira(s)",
            "capacidade_recebimento": lambda: f"capacidade de recebimento × {v:.2f}",
            "moegas": lambda: f"{int(v)} moega(s)",
            "fator_distancia": lambda: f"distâncias × {v:.2f}",
            "disponibilidade": lambda: f"disponibilidade mecânica = {v:.0%}",
            "chuva": lambda: f"chuva no dia {self.dia} às {self.hora:.0f}h por {self.duracao_h:.0f} h",
            "falha_equipamento": lambda: f"falha de {self.recurso_id} no dia {self.dia} às {self.hora:.0f}h por {self.duracao_h:.0f} h",
            "produtividade": lambda: f"produtividade × {v:.2f}",
            "sequencia": lambda: f"sequência de talhões: {self.ordem if isinstance(self.ordem, str) else 'plano otimizado'}",
            "jornada_caminhoes": lambda: f"jornada dos caminhões {_hh(self.inicio_h)}–{_hh(self.fim_h)}",
            "horas_colheita": lambda: f"turno de colheita {'+' if v >= 0 else ''}{v:.1f} h",
            "alocacao": lambda: f"alocação dedicada {self.alocacao}",
            "eficiencia_campo": lambda: f"eficiência de campo × {v:.2f}",
            "capacidade_caminhao": lambda: f"capacidade dos caminhões × {v:.2f}",
            "velocidade_caminhao": lambda: f"velocidade dos caminhões × {v:.2f}",
            "tempo_fixo_recebimento": lambda: f"tempo fixo na unidade × {v:.2f}",
            "horario_recebimento": lambda: f"unidade aberta {_hh(self.inicio_h)}–{_hh(self.fim_h)}",
            "composicao_frota": lambda: "frota: " + ", ".join(f"{k}={v}" for k, v in (self.alocacao or {}).items()),
            "semente": lambda: f"semente {int(v)}",
        }
        return d[self.tipo]()


class Cenario(BaseModel):
    nome: str
    descricao: str = ""
    modificacoes: list[Modificacao] = Field(default_factory=list)
    controlavel: bool = Field(True, description="Decisão gerencial (True) ou condição externa / teste de estresse (False)")

    def descrever(self) -> str:
        if not self.modificacoes:
            return "Configuração original"
        return "; ".join(m.descrever() for m in self.modificacoes)


def _ajustar_frota(d: dict, total_desejado: int) -> None:
    sim = d["simulacao"]
    sim["alocacao_caminhoes"] = {}  # IDs individuais mudam com a frota
    if sum(sim.get("alocacao", {}).values()) > total_desejado:
        sim["modo_alocacao"], sim["alocacao"] = "pool", {}
    frota = d["frota"]
    atual = sum(g["quantidade"] for g in frota)
    delta = total_desejado - atual
    if delta >= 0:
        frota[0]["quantidade"] += delta
        return
    for g in reversed(frota):
        tira = min(g["quantidade"], -delta)
        g["quantidade"] -= tira
        delta += tira
        if delta == 0:
            break


def aplicar(cfg: OperationConfig, mods: list[Modificacao]) -> OperationConfig:
    d = copy.deepcopy(cfg.model_dump())
    for m in mods:
        t = m.tipo
        if t == "caminhoes_extra":
            _ajustar_frota(d, max(1, sum(g["quantidade"] for g in d["frota"]) + int(m.valor)))
        elif t == "caminhoes_total":
            _ajustar_frota(d, max(1, int(m.valor)))
        elif t == "colheitadeira_extra":
            base = d["colheitadeiras"][0]
            ids = {c["id"] for c in d["colheitadeiras"]}
            for _ in range(int(m.valor)):
                k = len(d["colheitadeiras"]) + 1
                while f"C{k}" in ids:
                    k += 1
                nova = copy.deepcopy(base)
                nova["id"], nova["nome"] = f"C{k}", f"Colheitadeira {k} (adicional)"
                ids.add(nova["id"])
                d["colheitadeiras"].append(nova)
        elif t == "capacidade_recebimento":
            d["recebimento"]["capacidade_t_h"] *= m.valor
        elif t == "moegas":
            taxa = d["recebimento"]["capacidade_t_h"] / d["recebimento"]["n_moegas"]
            d["recebimento"]["n_moegas"] = int(m.valor)
            d["recebimento"]["capacidade_t_h"] = taxa * int(m.valor)
        elif t == "fator_distancia":
            for f in d["talhoes"]:
                f["distancia_km"] *= m.valor
        elif t == "disponibilidade":
            for c in d["colheitadeiras"]:
                c["disponibilidade_mecanica"] = m.valor
            for g in d["frota"]:
                g["disponibilidade_mecanica"] = m.valor
        elif t == "chuva":
            d["clima"]["eventos_chuva"].append({"dia": m.dia, "hora_inicio": m.hora, "duracao_h": m.duracao_h})
        elif t == "falha_equipamento":
            d["eventos"].append({"tipo": "falha_forcada", "dia": m.dia, "hora": m.hora, "duracao_h": m.duracao_h,
                                 "recurso_id": m.recurso_id})
        elif t == "produtividade":
            for f in d["talhoes"]:
                f["produtividade_sc_ha"] *= m.valor
        elif t == "sequencia":
            if isinstance(m.ordem, dict):
                d["simulacao"]["regra_sequencia"] = "plano"
                d["simulacao"]["plano_sequencia"] = m.ordem
            elif m.ordem == "reversa":
                d["simulacao"]["regra_sequencia"] = "prioridade"
                for f in d["talhoes"]:
                    f["prioridade"] = 6 - f["prioridade"]
            elif m.ordem in ("proximidade", "prioridade"):
                d["simulacao"]["regra_sequencia"] = m.ordem
            else:
                raise ValueError(f"Ordem de sequência desconhecida: {m.ordem}")
        elif t == "jornada_caminhoes":
            d["janela"]["caminhoes_inicio_h"] = m.inicio_h
            d["janela"]["caminhoes_fim_h"] = m.fim_h
        elif t == "horas_colheita":
            fim = min(24.0, d["janela"]["colheita_fim_h"] + m.valor)
            d["janela"]["colheita_fim_h"] = fim
            d["janela"]["caminhoes_fim_h"] = max(d["janela"]["caminhoes_fim_h"], fim)
        elif t == "alocacao":
            d["simulacao"]["modo_alocacao"] = "dedicada"
            d["simulacao"]["alocacao"] = dict(m.alocacao or {})
            d["simulacao"]["alocacao_caminhoes"] = dict(m.ordem or {}) if isinstance(m.ordem, dict) else {}
        elif t == "composicao_frota":
            qtd = m.alocacao or {}
            for g in d["frota"]:
                if g["id"] in qtd:
                    g["quantidade"] = int(qtd[g["id"]])
            d["simulacao"]["modo_alocacao"] = "pool"
            d["simulacao"]["alocacao"] = {}
            d["simulacao"]["alocacao_caminhoes"] = {}
        elif t == "eficiencia_campo":
            for c in d["colheitadeiras"]:
                c["eficiencia_campo"] = min(1.0, c["eficiencia_campo"] * m.valor)
        elif t == "capacidade_caminhao":
            for g in d["frota"]:
                g["capacidade_t"] *= m.valor
        elif t == "velocidade_caminhao":
            for g in d["frota"]:
                g["velocidade_carregado_km_h"] *= m.valor
                g["velocidade_vazio_km_h"] *= m.valor
        elif t == "tempo_fixo_recebimento":
            d["recebimento"]["tempo_fixo_min"] *= m.valor
        elif t == "horario_recebimento":
            d["recebimento"]["hora_abertura"] = m.inicio_h
            d["recebimento"]["hora_fechamento"] = m.fim_h
        elif t == "semente":
            d["simulacao"]["semente"] = int(m.valor)
    return OperationConfig.model_validate(d)


def cenarios_padrao(cfg: OperationConfig) -> list[Cenario]:
    """Conjunto de cenários comparativos sugeridos para a operação."""
    h0 = cfg.colheitadeiras[0].id
    meio = max(1, int(cfg.janela.data_alvo_dias or 3) // 2)
    return [
        Cenario(nome="Original"),
        Cenario(nome="+1 caminhão", modificacoes=[Modificacao(tipo="caminhoes_extra", valor=1)]),
        Cenario(nome="+2 caminhões", modificacoes=[Modificacao(tipo="caminhoes_extra", valor=2)]),
        Cenario(nome="+1 colheitadeira", modificacoes=[Modificacao(tipo="colheitadeira_extra", valor=1)]),
        Cenario(nome="Recebimento +30%", modificacoes=[Modificacao(tipo="capacidade_recebimento", valor=1.3)]),
        Cenario(nome="Recebimento −30%", modificacoes=[Modificacao(tipo="capacidade_recebimento", valor=0.7)]),
        Cenario(nome="Sequência por proximidade", modificacoes=[Modificacao(tipo="sequencia", ordem="proximidade")]),
        Cenario(nome="Transporte +25% distância", controlavel=False,
                modificacoes=[Modificacao(tipo="fator_distancia", valor=1.25)]),
        Cenario(nome="Disponibilidade 85%", controlavel=False, modificacoes=[Modificacao(tipo="disponibilidade", valor=0.85)]),
        Cenario(nome="Chuva de 24 h", controlavel=False, modificacoes=[Modificacao(tipo="chuva", dia=meio, hora=10, duracao_h=24)]),
        Cenario(nome=f"Falha de {h0} (12 h)", controlavel=False,
                modificacoes=[Modificacao(tipo="falha_equipamento", recurso_id=h0, dia=2, hora=10, duracao_h=12)]),
        Cenario(nome="Produtividade +15%", controlavel=False, modificacoes=[Modificacao(tipo="produtividade", valor=1.15)]),
    ]
