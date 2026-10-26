"""Registros produzidos pela simulação: log de eventos, segmentos de estado e cargas."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Estados (cores consistentes em toda a interface: ver ui/theme.py)
ESTADOS_COLHEITADEIRA = [
    "colhendo", "descarregando", "aguardando_caminhao", "deslocando", "manutencao_programada",
    "falha", "parada_clima", "fora_turno", "ocioso", "concluida",
]
ESTADOS_CAMINHAO = [
    "aguardando_carregamento", "em_carregamento", "manobra", "carregando", "transporte_carregado", "fila_descarga",
    "fila_unidade_fechada", "descarregando", "retorno_vazio", "falha", "fora_jornada", "concluido",
]
# em_carregamento = caminhão posicionado junto à colheitadeira enquanto ela enche o tanque (parte do ciclo)
ESTADOS_PRODUTIVOS_CAMINHAO = {"em_carregamento", "manobra", "carregando", "transporte_carregado", "descarregando",
                               "retorno_vazio"}

ROTULOS_ESTADO = {
    "colhendo": "Colhendo",
    "descarregando": "Descarregando",
    "aguardando_caminhao": "Aguardando caminhão",
    "deslocando": "Deslocando entre talhões",
    "manutencao_programada": "Manutenção programada",
    "falha": "Falha / reparo",
    "parada_clima": "Parada por clima",
    "fora_turno": "Fora do turno",
    "ocioso": "Ociosa (sem talhão liberado)",
    "concluida": "Concluída",
    "aguardando_carregamento": "Aguardando carregamento (fila/máquina parada)",
    "em_carregamento": "Em carregamento (enchendo junto à máquina)",
    "manobra": "Manobra",
    "carregando": "Carregando",
    "transporte_carregado": "Transporte carregado",
    "fila_descarga": "Fila de descarga",
    "fila_unidade_fechada": "Fila (unidade fechada)",
    "retorno_vazio": "Retorno vazio",
    "fora_jornada": "Fora da jornada",
    "concluido": "Concluído",
}


@dataclass
class Segmento:
    recurso: str
    tipo: str  # 'colheitadeira' | 'caminhao'
    estado: str
    inicio: float
    fim: Optional[float] = None
    talhao: Optional[str] = None
    carga: Optional[str] = None
    origem: Optional[str] = None
    destino: Optional[str] = None
    carga_t: float = 0.0
    colheitadeira: Optional[str] = None


class StateRecorder:
    """Mantém um segmento aberto por recurso; cada mudança fecha o anterior."""

    def __init__(self, env):
        self.env = env
        self.abertos: dict[str, Segmento] = {}
        self.segmentos: list[Segmento] = []

    def set(self, recurso: str, tipo: str, estado: str, **meta: Any) -> None:
        now = self.env.now
        atual = self.abertos.get(recurso)
        if atual is not None:
            mesmo = (
                atual.estado == estado and atual.talhao == meta.get("talhao") and atual.carga == meta.get("carga")
                and atual.origem == meta.get("origem") and atual.destino == meta.get("destino")
                and atual.colheitadeira == meta.get("colheitadeira")
            )
            if mesmo:
                atual.carga_t = meta.get("carga_t", atual.carga_t)
                return
            atual.fim = now
            if atual.fim - atual.inicio > 1e-9:
                self.segmentos.append(atual)
        self.abertos[recurso] = Segmento(recurso=recurso, tipo=tipo, estado=estado, inicio=now, **meta)

    def add_closed(self, seg: Segmento) -> None:
        if seg.fim - seg.inicio > 1e-9:
            self.segmentos.append(seg)

    def close_all(self, t_end: float) -> None:
        for seg in self.abertos.values():
            seg.fim = max(t_end, seg.inicio)
            if seg.fim - seg.inicio > 1e-9:
                self.segmentos.append(seg)
        self.abertos.clear()


@dataclass
class EventLog:
    eventos: list[dict] = field(default_factory=list)

    def add(self, t: float, tipo: str, recurso: str = "", categoria: str = "", talhao: str = "",
            carga: str = "", qtd_t: float = 0.0, detalhe: str = "") -> None:
        self.eventos.append({
            "t_min": t, "tipo": tipo, "recurso": recurso, "categoria": categoria, "talhao": talhao,
            "carga": carga, "qtd_t": qtd_t, "detalhe": detalhe,
        })


@dataclass
class Carga:
    id: str
    caminhao: str
    tipo_caminhao: str
    capacidade_t: float
    quantidade_t: float = 0.0
    por_talhao: dict[str, float] = field(default_factory=dict)
    por_colheitadeira: dict[str, float] = field(default_factory=dict)
    t_inicio_carregamento: Optional[float] = None
    t_saida_campo: Optional[float] = None
    t_chegada_unidade: Optional[float] = None
    t_inicio_descarga: Optional[float] = None
    t_fim_descarga: Optional[float] = None
    talhao_origem: Optional[str] = None
    distancia_km: float = 0.0
    status: str = "no_campo"  # no_campo | em_transito | na_fila | entregue
