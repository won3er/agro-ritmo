"""Entidades e regras operacionais (configuração validada com Pydantic).

Princípios de modelagem (ver docs/MODELO.md):

* **Produtividade nominal** (``capacidade_campo_ha_h``): capacidade teórica de campo da
  colheitadeira, sem perdas de tempo.
* **Eficiência operacional de campo** (``eficiencia_campo``): fração do tempo em colheita que é
  efetivamente produtiva (manobras de cabeceira, sobreposição). É aplicada à taxa de colheita.
* **Disponibilidade mecânica** (``disponibilidade_mecanica``): NÃO é aplicada à taxa. Ela é
  convertida em tempo médio entre falhas (MTBF = A·MTTR / (1 − A)) e as falhas acontecem como
  eventos no simulador. Assim o mesmo desconto nunca é aplicado duas vezes.
* Esperas por caminhão, clima, turnos e manutenção programada surgem da simulação; não há
  "fator de aproveitamento" global aplicado sobre a taxa.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .crops import CropSpec, obter_cultura
from .units import produtividade_t_ha


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class OrigemDado(str, Enum):
    EXEMPLO = "exemplo_sintetico"
    USUARIO = "usuario"
    IMPORTADO = "importado"
    CALIBRADO = "calibrado"


class Talhao(_Base):
    id: str = Field(..., min_length=1, max_length=20)
    nome: str = ""
    area_ha: float = Field(..., gt=0, le=20000, description="Área a colher (ha)")
    produtividade_sc_ha: float = Field(..., gt=0, le=400, description="Produtividade estimada (sc/ha)")
    prioridade: int = Field(3, ge=1, le=5, description="1 = mais alta, 5 = mais baixa")
    distancia_km: float = Field(..., gt=0, le=500, description="Distância até a unidade de recebimento (km)")
    x_km: float = Field(0.0, description="Posição esquemática do talhão (km) — usada no deslocamento entre talhões")
    y_km: float = Field(0.0)
    disponivel_a_partir_dia: int = Field(1, ge=1, le=365, description="Dia a partir do qual o talhão pode ser colhido")

    def t_ha(self, kg_por_saca: float) -> float:
        return produtividade_t_ha(self.produtividade_sc_ha, kg_por_saca)


class Colheitadeira(_Base):
    id: str = Field(..., min_length=1, max_length=20)
    nome: str = ""
    modelo: str = ""
    capacidade_campo_ha_h: float = Field(..., gt=0, le=30, description="Capacidade de campo nominal/teórica (ha/h)")
    eficiencia_campo: float = Field(0.75, gt=0, le=1, description="Eficiência operacional de campo (0–1)")
    capacidade_tanque_t: float = Field(..., gt=0, le=40, description="Capacidade do tanque graneleiro (t)")
    tempo_descarga_tanque_min: float = Field(2.5, gt=0, le=30, description="Tempo para descarregar um tanque cheio no caminhão (min)")
    velocidade_deslocamento_km_h: float = Field(15.0, gt=0, le=40, description="Velocidade de deslocamento entre talhões (km/h)")
    disponibilidade_mecanica: float = Field(0.95, gt=0, le=1, description="Disponibilidade mecânica (0–1). 1 = sem falhas")
    mttr_h: float = Field(2.0, gt=0, le=200, description="Tempo médio de reparo (h)")
    parada_programada_min_dia: float = Field(30.0, ge=0, le=600, description="Manutenção/abastecimento no início de cada turno (min)")
    custo_fixo_h: float = Field(250.0, ge=0, description="Custo por hora mobilizada (operador, depreciação, seguro) R$/h")
    custo_variavel_h: float = Field(150.0, ge=0, description="Custo por hora de colheita (manutenção, desgaste) R$/h")
    consumo_l_h: float = Field(35.0, ge=0, description="Consumo de combustível em operação (L/h)")

    @property
    def taxa_efetiva_ha_h(self) -> float:
        return self.capacidade_campo_ha_h * self.eficiencia_campo

    @property
    def mtbf_h(self) -> Optional[float]:
        """MTBF em horas de operação, derivado de A = MTBF / (MTBF + MTTR). None = sem falhas."""
        if self.disponibilidade_mecanica >= 0.9999:
            return None
        a = self.disponibilidade_mecanica
        return a * self.mttr_h / (1.0 - a)


class TipoCaminhao(_Base):
    id: str = Field(..., min_length=1, max_length=20, description="Prefixo dos caminhões deste grupo")
    nome: str = "Caminhão"
    quantidade: int = Field(..., ge=0, le=200)
    capacidade_t: float = Field(..., gt=0, le=80, description="Capacidade de carga (t)")
    velocidade_carregado_km_h: float = Field(40.0, gt=0, le=100)
    velocidade_vazio_km_h: float = Field(50.0, gt=0, le=120)
    tempo_manobra_min: float = Field(3.0, ge=0, le=60, description="Posicionamento junto à colheitadeira (min)")
    disponibilidade_mecanica: float = Field(1.0, gt=0, le=1)
    mttr_h: float = Field(3.0, gt=0, le=200)
    custo_fixo_h: float = Field(120.0, ge=0, description="Custo por hora mobilizada (motorista, depreciação) R$/h")
    custo_variavel_km: float = Field(1.2, ge=0, description="Custo por km rodado (pneus, manutenção) R$/km")
    consumo_km_l: float = Field(2.5, gt=0, description="Rendimento de combustível (km/L)")

    @property
    def mtbf_h(self) -> Optional[float]:
        if self.disponibilidade_mecanica >= 0.9999:
            return None
        a = self.disponibilidade_mecanica
        return a * self.mttr_h / (1.0 - a)


class UnidadeRecebimento(_Base):
    nome: str = "Unidade de recebimento"
    n_moegas: int = Field(2, ge=1, le=20, description="Número de moegas/pontos de descarga simultâneos")
    capacidade_t_h: float = Field(..., gt=0, le=5000, description="Capacidade total de recebimento (t/h)")
    tempo_fixo_min: float = Field(8.0, ge=0, le=120, description="Pesagem, amostragem e classificação por caminhão (min)")
    hora_abertura: float = Field(6.0, ge=0, le=24)
    hora_fechamento: float = Field(22.0, ge=0, le=24)
    custo_recebimento_t: float = Field(0.0, ge=0, description="Custo de recepção por tonelada (R$/t)")

    @property
    def taxa_por_moega_t_h(self) -> float:
        return self.capacidade_t_h / self.n_moegas

    @model_validator(mode="after")
    def _horario(self):
        if self.hora_fechamento <= self.hora_abertura:
            raise ValueError("hora_fechamento deve ser maior que hora_abertura (turnos noturnos que cruzam a meia-noite não são suportados)")
        return self


class JanelaOperacao(_Base):
    colheita_inicio_h: float = Field(8.0, ge=0, le=24, description="Início do turno de colheita")
    colheita_fim_h: float = Field(19.0, ge=0, le=24, description="Fim do turno de colheita")
    caminhoes_inicio_h: float = Field(6.0, ge=0, le=24)
    caminhoes_fim_h: float = Field(22.0, ge=0, le=24)
    horizonte_dias: int = Field(30, ge=1, le=180, description="Janela máxima disponível para a operação (dias)")
    data_alvo_dias: Optional[float] = Field(None, gt=0, description="Prazo desejado para concluir (dias)")

    @property
    def horas_colheita_dia(self) -> float:
        return self.colheita_fim_h - self.colheita_inicio_h

    @property
    def horas_caminhao_dia(self) -> float:
        return self.caminhoes_fim_h - self.caminhoes_inicio_h

    @model_validator(mode="after")
    def _turnos(self):
        if self.colheita_fim_h <= self.colheita_inicio_h:
            raise ValueError("colheita_fim_h deve ser maior que colheita_inicio_h")
        if self.caminhoes_fim_h <= self.caminhoes_inicio_h:
            raise ValueError("caminhoes_fim_h deve ser maior que caminhoes_inicio_h")
        if self.caminhoes_inicio_h > self.colheita_inicio_h or self.caminhoes_fim_h < self.colheita_fim_h:
            raise ValueError("A jornada dos caminhões deve cobrir o turno de colheita (caminhões precisam estar disponíveis enquanto há colheita)")
        return self


class EventoChuva(_Base):
    dia: int = Field(..., ge=1)
    hora_inicio: float = Field(..., ge=0, lt=24)
    duracao_h: float = Field(..., gt=0, le=240)


class Clima(_Base):
    eventos_chuva: list[EventoChuva] = Field(default_factory=list)
    prob_chuva_dia: float = Field(0.0, ge=0, le=1, description="Probabilidade diária de chuva gerada aleatoriamente")
    duracao_media_chuva_h: float = Field(3.0, gt=0, le=48)
    espera_pos_chuva_h: float = Field(2.0, ge=0, le=48, description="Tempo de secagem antes de retomar a colheita (h)")


class OutroCusto(_Base):
    nome: str
    tipo: Literal["por_dia", "por_tonelada", "fixo"]
    valor: float = Field(..., ge=0)


class Custos(_Base):
    preco_diesel_l: float = Field(6.20, ge=0, description="Preço do combustível (R$/L)")
    outros_custos: list[OutroCusto] = Field(default_factory=list)
    valor_saca: float = Field(0.0, ge=0, description="Preço de referência da saca (R$/sc) — usado apenas para valorar volume em risco")


class EventoOperacional(_Base):
    """Mudanças de condição durante a operação."""
    tipo: Literal["falha_forcada", "interrupcao_recebimento", "capacidade_recebimento"]
    dia: int = Field(..., ge=1)
    hora: float = Field(..., ge=0, lt=24)
    duracao_h: float = Field(0.0, ge=0, le=500)
    recurso_id: Optional[str] = None
    valor: Optional[float] = Field(None, description="Para capacidade_recebimento: fator multiplicativo (ex.: 0,5)")

    @property
    def inicio_min(self) -> float:
        return (self.dia - 1) * 1440.0 + self.hora * 60.0

    @property
    def fim_min(self) -> float:
        return self.inicio_min + self.duracao_h * 60.0


class ParametrosSimulacao(_Base):
    semente: int = Field(42, ge=0)
    variabilidade_cv: float = Field(0.10, ge=0, le=0.6, description="Coeficiente de variação dos tempos (0 = determinístico)")
    falhas_aleatorias: bool = Field(True, description="Gerar falhas a partir da disponibilidade mecânica")
    descarregar_fim_turno: bool = Field(True, description="Colheitadeira esvazia o tanque ao fim do turno")
    modo_alocacao: Literal["pool", "dedicada"] = "pool"
    alocacao: dict[str, int] = Field(default_factory=dict, description="Caminhões dedicados por colheitadeira (modo dedicada)")
    alocacao_caminhoes: dict[str, str] = Field(default_factory=dict,
                                               description="Mapa explícito caminhão → colheitadeira (modo dedicada; tem precedência)")
    regra_sequencia: Literal["prioridade", "plano", "proximidade"] = "prioridade"
    plano_sequencia: dict[str, list[str]] = Field(default_factory=dict, description="Talhões por colheitadeira, em ordem (regra 'plano')")
    ajuda_entre_colheitadeiras: bool = Field(True, description="Colheitadeira sem talhões pendentes ajuda em talhão em andamento")


class OperationConfig(_Base):
    nome: str = Field(..., min_length=1, max_length=120)
    descricao: str = ""
    cultura: str = "soja"
    cultura_spec: Optional[CropSpec] = None
    talhoes: list[Talhao] = Field(..., min_length=1)
    colheitadeiras: list[Colheitadeira] = Field(..., min_length=1)
    frota: list[TipoCaminhao] = Field(..., min_length=1)
    recebimento: UnidadeRecebimento
    janela: JanelaOperacao = Field(default_factory=JanelaOperacao)
    clima: Clima = Field(default_factory=Clima)
    custos: Custos = Field(default_factory=Custos)
    eventos: list[EventoOperacional] = Field(default_factory=list)
    simulacao: ParametrosSimulacao = Field(default_factory=ParametrosSimulacao)
    origem_dados: OrigemDado = OrigemDado.USUARIO
    proveniencia: dict[str, OrigemDado] = Field(
        default_factory=dict,
        description="Origem de parâmetros específicos (caminho → origem); ausentes herdam origem_dados",
    )

    # ------------------------------------------------------------------ helpers
    @property
    def crop(self) -> CropSpec:
        return self.cultura_spec or obter_cultura(self.cultura)

    @property
    def kg_por_saca(self) -> float:
        return self.crop.kg_por_saca

    @property
    def n_caminhoes(self) -> int:
        return sum(g.quantidade for g in self.frota)

    @property
    def area_total_ha(self) -> float:
        return sum(t.area_ha for t in self.talhoes)

    @property
    def producao_prevista_t(self) -> float:
        return sum(t.area_ha * t.t_ha(self.kg_por_saca) for t in self.talhoes)

    def talhao(self, tid: str) -> Talhao:
        for t in self.talhoes:
            if t.id == tid:
                return t
        raise KeyError(tid)

    def caminhoes_expandidos(self) -> list[tuple[str, TipoCaminhao]]:
        """Lista (id_individual, tipo) — ex.: CAM-01, CAM-02 ..."""
        out = []
        for g in self.frota:
            for i in range(g.quantidade):
                out.append((f"{g.id}-{i + 1:02d}", g))
        return out

    # --------------------------------------------------------------- validação
    @field_validator("cultura")
    @classmethod
    def _cultura_lower(cls, v: str) -> str:
        return v.strip().lower()

    @model_validator(mode="after")
    def _consistencia(self):
        if self.cultura_spec is None:
            obter_cultura(self.cultura)  # levanta erro claro se não existir
        for nome, itens in (("talhões", self.talhoes), ("colheitadeiras", self.colheitadeiras), ("grupos de caminhões", self.frota)):
            ids = [i.id for i in itens]
            dup = {i for i in ids if ids.count(i) > 1}
            if dup:
                raise ValueError(f"IDs duplicados em {nome}: {sorted(dup)}")
        if self.n_caminhoes < 1:
            raise ValueError("A frota precisa ter pelo menos 1 caminhão")
        h_ids = {c.id for c in self.colheitadeiras}
        t_ids = {t.id for t in self.talhoes}
        cam_ids = {cid for cid, _ in self.caminhoes_expandidos()}
        if self.simulacao.alocacao_caminhoes and self.simulacao.modo_alocacao != "dedicada":
            raise ValueError("alocacao_caminhoes exige modo_alocacao = 'dedicada'")
        for hid in self.simulacao.alocacao:
            if hid not in h_ids:
                raise ValueError(f"Alocação referencia colheitadeira inexistente: {hid}")
        for cid, hid in self.simulacao.alocacao_caminhoes.items():
            if cid not in cam_ids or hid not in h_ids:
                raise ValueError(f"Alocação explícita inválida: {cid} → {hid}")
        if self.simulacao.modo_alocacao == "dedicada" and self.simulacao.alocacao:
            if sum(self.simulacao.alocacao.values()) > self.n_caminhoes:
                raise ValueError("A alocação dedicada usa mais caminhões do que a frota possui")
        for hid, seq in self.simulacao.plano_sequencia.items():
            if hid not in h_ids:
                raise ValueError(f"Plano de sequência referencia colheitadeira inexistente: {hid}")
            for tid in seq:
                if tid not in t_ids:
                    raise ValueError(f"Plano de sequência referencia talhão inexistente: {tid}")
        for ev in self.eventos:
            if ev.tipo == "falha_forcada":
                if ev.recurso_id not in h_ids | cam_ids:
                    raise ValueError(f"Evento de falha referencia recurso inexistente: {ev.recurso_id}")
                if ev.duracao_h <= 0:
                    raise ValueError("Evento de falha precisa de duração > 0")
            if ev.tipo == "capacidade_recebimento" and (ev.valor is None or ev.valor <= 0):
                raise ValueError("Evento de capacidade_recebimento precisa de valor (fator) > 0")
        if self.recebimento.hora_abertura > self.janela.caminhoes_inicio_h + 24:  # pragma: no cover - defensivo
            raise ValueError("Horário da unidade inválido")
        return self

    def alertas(self) -> list[str]:
        """Alertas de plausibilidade (não bloqueiam a simulação)."""
        out: list[str] = []
        lo, hi = self.crop.produtividade_tipica_sc_ha
        for t in self.talhoes:
            if not lo <= t.produtividade_sc_ha <= hi:
                out.append(f"Talhão {t.id}: produtividade {t.produtividade_sc_ha} sc/ha fora da faixa típica de {self.crop.nome} ({lo}–{hi}).")
        for c in self.colheitadeiras:
            if c.eficiencia_campo < 0.5:
                out.append(f"Colheitadeira {c.id}: eficiência de campo {c.eficiencia_campo:.0%} é baixa.")
        if self.recebimento.hora_fechamento < self.janela.colheita_fim_h:
            out.append("A unidade fecha antes do fim do turno de colheita: cargas do fim do dia aguardarão até a reabertura.")
        if self.janela.horizonte_dias * 1440 < 1440:
            out.append("Horizonte muito curto.")
        return out

    def origem_de(self, caminho: str) -> OrigemDado:
        return self.proveniencia.get(caminho, self.origem_dados)
