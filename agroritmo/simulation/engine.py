"""Motor de simulação de eventos discretos (SimPy) da colheita e transporte de grãos.

Fluxo representado
------------------
talhão → colheitadeira (tanque) → transbordo para caminhão no campo → transporte carregado →
fila na unidade (moegas = recurso com capacidade) → descarga → retorno vazio → ...

Garantias estruturais (verificadas pelos testes)
-----------------------------------------------
* Cada tonelada colhida está, em qualquer instante, em exatamente um lugar: tanque de uma
  colheitadeira, caminhão (no campo, em trânsito ou na fila) ou entregue na unidade.
* Uma carga recebe um único ID e é contabilizada como entregue uma única vez (no fim da descarga).
* Um caminhão é um processo sequencial: não executa duas viagens ao mesmo tempo.
* Nenhum caminhão recebe mais que sua capacidade; nenhuma moega atende mais de um caminhão por vez.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import simpy

from ..domain.models import Colheitadeira, OperationConfig, Talhao, TipoCaminhao
from ..domain.units import MIN_POR_DIA
from ..logging_config import get_logger
from .calendar import Calendario, Janelas, merge, subtract
from .records import Carga, EventLog, Segmento, StateRecorder
from .results import SimulationResult

log = get_logger(__name__)

FATOR_SINUOSIDADE = 1.3  # distância por estrada ≈ 1,3 × distância em linha reta entre talhões
EPS_T = 1e-6   # t
EPS_A = 1e-7   # ha
UNIDADE = "UNIDADE"


# ---------------------------------------------------------------------------- aleatoriedade
class Aleatorio:
    """Fluxos aleatórios independentes por chave (números aleatórios comuns entre cenários).

    Cada recurso tem seu próprio gerador derivado de (semente, chave). Adicionar um caminhão
    não altera a sequência aleatória dos demais, o que torna a comparação de cenários mais justa.
    """

    def __init__(self, semente: int, cv: float):
        self.semente = semente
        self.cv = cv
        self._g: dict[str, np.random.Generator] = {}

    def gen(self, chave: str) -> np.random.Generator:
        if chave not in self._g:
            ss = np.random.SeedSequence([self.semente, zlib.crc32(chave.encode())])
            self._g[chave] = np.random.default_rng(ss)
        return self._g[chave]

    def fator(self, chave: str) -> float:
        """Fator multiplicativo lognormal com média 1 e CV configurado."""
        if self.cv <= 0:
            return 1.0
        s2 = math.log(1 + self.cv ** 2)
        return float(self.gen(chave).lognormal(-s2 / 2, math.sqrt(s2)))

    def ttf_h(self, chave: str, mtbf_h: Optional[float]) -> Optional[float]:
        if mtbf_h is None:
            return None
        if self.cv <= 0:
            return mtbf_h
        return float(self.gen(chave).exponential(mtbf_h))

    def reparo_h(self, chave: str, mttr_h: float) -> float:
        if self.cv <= 0:
            return mttr_h
        s2 = math.log(1 + 0.5 ** 2)
        return float(mttr_h * self.gen(chave).lognormal(-s2 / 2, math.sqrt(s2)))


# ---------------------------------------------------------------------------- agentes
@dataclass(eq=False)
class EstadoTalhao:
    talhao: Talhao
    t_ha: float
    area_livre: float
    disponivel_min: float
    area_colhida: float = 0.0
    t_colhidas: float = 0.0
    inicio: Optional[float] = None
    fim: Optional[float] = None
    atribuido: bool = False
    trabalhadores: set = field(default_factory=set)

    @property
    def id(self) -> str:
        return self.talhao.id


@dataclass(eq=False)
class AgenteColheitadeira:
    spec: Colheitadeira
    plano: list[str]
    tanque: float = 0.0
    tanque_por_talhao: dict[str, float] = field(default_factory=dict)
    talhao: Optional[EstadoTalhao] = None
    fila: deque = field(default_factory=deque)
    ev_caminhao: Optional[simpy.Event] = None
    esperando: bool = False
    ocioso: bool = False
    concluida: bool = False
    parado_horizonte: bool = False
    transferindo: bool = False
    a_caminho: int = 0
    a_caminho_cap: float = 0.0
    ttf_h: Optional[float] = None
    horas_colheita: float = 0.0
    horas_deslocamento: float = 0.0
    km_deslocamento: float = 0.0

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def taxa_ha_min(self) -> float:
        return self.spec.taxa_efetiva_ha_h / 60.0

    @property
    def taxa_t_h(self) -> float:
        t_ha = self.talhao.t_ha if self.talhao else 3.0
        return self.spec.taxa_efetiva_ha_h * t_ha


@dataclass(eq=False)
class AgenteCaminhao:
    id: str
    spec: TipoCaminhao
    carga_t: float = 0.0
    carga: Optional[Carga] = None
    pos: Optional[EstadoTalhao] = None  # None = unidade de recebimento
    ev_saida: Optional[simpy.Event] = None
    dedicado_a: Optional[str] = None
    ttf_h: Optional[float] = None
    falhas_forcadas: list = field(default_factory=list)
    km_carregado: float = 0.0
    km_vazio: float = 0.0
    viagens: int = 0

    @property
    def cap(self) -> float:
        return self.spec.capacidade_t


# ---------------------------------------------------------------------------- simulador
class Simulador:
    def __init__(self, cfg: OperationConfig):
        self.cfg = cfg
        self.env = simpy.Environment()
        self.rng = Aleatorio(cfg.simulacao.semente, cfg.simulacao.variabilidade_cv)
        self.cal = Calendario(cfg, self.rng.gen("clima"))
        self.horizonte = self.cal.horizonte_min
        self.log = EventLog()
        self.st = StateRecorder(self.env)
        self.cargas: list[Carga] = []
        self._n_carga = 0
        self.entregue_t = 0.0
        self.t_fim: Optional[float] = None
        self.moegas = simpy.Resource(self.env, capacity=cfg.recebimento.n_moegas)
        self._ev_pronta = self.env.event()

        kg = cfg.kg_por_saca
        self.talhoes: dict[str, EstadoTalhao] = {
            t.id: EstadoTalhao(talhao=t, t_ha=t.t_ha(kg), area_livre=t.area_ha,
                               disponivel_min=(t.disponivel_a_partir_dia - 1) * MIN_POR_DIA)
            for t in cfg.talhoes
        }
        plano = cfg.simulacao.plano_sequencia if cfg.simulacao.regra_sequencia == "plano" else {}
        self.colheitadeiras = [AgenteColheitadeira(spec=c, plano=list(plano.get(c.id, []))) for c in cfg.colheitadeiras]
        for h in self.colheitadeiras:
            h.ttf_h = self.rng.ttf_h(f"falha:{h.id}", h.spec.mtbf_h) if cfg.simulacao.falhas_aleatorias else None
        self.caminhoes = [AgenteCaminhao(id=cid, spec=g) for cid, g in cfg.caminhoes_expandidos()]
        for tk in self.caminhoes:
            tk.ttf_h = self.rng.ttf_h(f"falha:{tk.id}", tk.spec.mtbf_h) if cfg.simulacao.falhas_aleatorias else None
            tk.falhas_forcadas = sorted(self.cal.falhas_forcadas.get(tk.id, []))
        if cfg.simulacao.modo_alocacao == "dedicada" and cfg.simulacao.alocacao_caminhoes:
            for tk in self.caminhoes:
                tk.dedicado_a = cfg.simulacao.alocacao_caminhoes.get(tk.id)
        elif cfg.simulacao.modo_alocacao == "dedicada":
            livres = iter(self.caminhoes)
            for hid, n in cfg.simulacao.alocacao.items():
                for _ in range(n):
                    tk = next(livres, None)
                    if tk is not None:
                        tk.dedicado_a = hid

    # ------------------------------------------------------------------ utilidades
    def _dist(self, a: Optional[EstadoTalhao], b: Optional[EstadoTalhao]) -> float:
        if a is b:
            return 0.0
        if a is None:
            return b.talhao.distancia_km
        if b is None:
            return a.talhao.distancia_km
        dx = a.talhao.x_km - b.talhao.x_km
        dy = a.talhao.y_km - b.talhao.y_km
        return math.hypot(dx, dy) * FATOR_SINUOSIDADE

    @staticmethod
    def _nome(pos: Optional[EstadoTalhao]) -> str:
        return UNIDADE if pos is None else pos.id

    def _nova_carga(self, tk: AgenteCaminhao) -> Carga:
        self._n_carga += 1
        c = Carga(id=f"L{self._n_carga:05d}", caminhao=tk.id, tipo_caminhao=tk.spec.id, capacidade_t=tk.cap,
                  t_inicio_carregamento=self.env.now)
        self.cargas.append(c)
        return c

    def _verificar_fim(self) -> None:
        if self.t_fim is not None:
            return
        if all(h.concluida for h in self.colheitadeiras) and all(tk.carga_t <= EPS_T for tk in self.caminhoes):
            area_rest = sum(f.talhao.area_ha - f.area_colhida for f in self.talhoes.values())
            if area_rest <= 1e-4:
                self.t_fim = self.env.now
                self.log.add(self.env.now, "OPERACAO_CONCLUIDA", categoria="operacao",
                             detalhe=f"{self.entregue_t:.1f} t entregues")

    def _sinalizar_pronta(self) -> None:
        if not self._ev_pronta.triggered:
            self._ev_pronta.succeed()
        self._ev_pronta = self.env.event()

    # ------------------------------------------------------------------ escolha de talhão
    def _disponiveis(self) -> list[EstadoTalhao]:
        now = self.env.now
        return [f for f in self.talhoes.values() if f.area_livre > EPS_A and f.disponivel_min <= now + 1e-9]

    def _proximo_talhao(self, h: AgenteColheitadeira) -> Optional[EstadoTalhao]:
        regra = self.cfg.simulacao.regra_sequencia
        disp = self._disponiveis()
        livres = [f for f in disp if not f.atribuido]
        escolhido = None
        if regra == "plano":
            while h.plano:
                tid = h.plano[0]
                f = self.talhoes[tid]
                if f.area_livre <= EPS_A:
                    h.plano.pop(0)
                    continue
                if f.disponivel_min <= self.env.now + 1e-9:
                    h.plano.pop(0)
                    escolhido = f
                break
            if escolhido is None and not h.plano:
                planejados = {t for c in self.colheitadeiras for t in c.plano}
                livres = [f for f in livres if f.id not in planejados]
                if livres:
                    escolhido = min(livres, key=lambda f: (f.talhao.prioridade, self._dist(h.talhao, f)))
            elif escolhido is None:
                return None  # próximo talhão do plano ainda não liberado — aguarda
        elif livres:
            if regra == "proximidade" and h.talhao is not None:
                escolhido = min(livres, key=lambda f: (self._dist(h.talhao, f), f.talhao.prioridade))
            else:
                escolhido = min(livres, key=lambda f: (f.talhao.prioridade, self._dist(h.talhao, f), f.id))
        if escolhido is None and self.cfg.simulacao.ajuda_entre_colheitadeiras and (regra != "plano" or not h.plano):
            em_andamento = [f for f in disp if f.atribuido]
            if em_andamento:
                escolhido = max(em_andamento, key=lambda f: (f.area_livre, -self._dist(h.talhao, f)))
        if escolhido is not None:
            escolhido.atribuido = True
        return escolhido

    def _proxima_liberacao(self, h: AgenteColheitadeira) -> Optional[float]:
        now = self.env.now
        if self.cfg.simulacao.regra_sequencia == "plano" and h.plano:
            return max(now, self.talhoes[h.plano[0]].disponivel_min)
        futuros = [f.disponivel_min for f in self.talhoes.values()
                   if f.area_livre > EPS_A and f.disponivel_min > now + 1e-9 and not f.atribuido]
        return min(futuros) if futuros else None

    # ------------------------------------------------------------------ colheitadeira
    def _proc_colheitadeira(self, h: AgenteColheitadeira):
        env = self.env
        while True:
            f = self._proximo_talhao(h)
            if f is None:
                t_lib = self._proxima_liberacao(h)
                if t_lib is None or t_lib >= self.horizonte:
                    break
                if h.tanque > EPS_T:
                    yield from self._descarregar_tanque(h, flush=True)
                h.ocioso = True
                self.st.set(h.id, "colheitadeira", "ocioso", talhao=h.talhao.id if h.talhao else None)
                self.log.add(env.now, "SEM_TALHAO_LIBERADO", h.id, "colheitadeira")
                if t_lib > env.now:
                    yield env.timeout(t_lib - env.now)
                h.ocioso = False
                continue
            if h.talhao is not f:
                yield from self._deslocar(h, f)
            yield from self._colher_talhao(h, f)
            if h.parado_horizonte:
                break
        if h.tanque > EPS_T and not h.parado_horizonte:
            yield from self._descarregar_tanque(h, flush=True)
        h.concluida = True
        self.st.set(h.id, "colheitadeira", "concluida", talhao=h.talhao.id if h.talhao else None)
        self.log.add(env.now, "COLHEITADEIRA_CONCLUIDA" if not h.parado_horizonte else "COLHEITADEIRA_FIM_HORIZONTE",
                     h.id, "colheitadeira")
        self._liberar_fila(h)
        self._sinalizar_pronta()
        self._verificar_fim()

    def _deslocar(self, h: AgenteColheitadeira, f: EstadoTalhao):
        env = self.env
        if h.talhao is None:
            h.talhao = f
            self._sinalizar_pronta()
            return
        dist = self._dist(h.talhao, f)
        dur = dist / h.spec.velocidade_deslocamento_km_h * 60 * self.rng.fator(f"desloc:{h.id}")
        self.st.set(h.id, "colheitadeira", "deslocando", origem=h.talhao.id, destino=f.id)
        self.log.add(env.now, "DESLOCAMENTO_INICIO", h.id, "colheitadeira", f.id, detalhe=f"{h.talhao.id} → {f.id} ({dist:.1f} km)")
        yield env.timeout(dur)
        h.horas_deslocamento += dur / 60
        h.km_deslocamento += dist
        h.talhao = f
        for tk in h.fila:  # caminhões que aguardavam junto à máquina a acompanham
            tk.pos = f
        self.log.add(env.now, "DESLOCAMENTO_FIM", h.id, "colheitadeira", f.id)

    def _em_turno(self, t: float) -> bool:
        return any(a - 1e-9 <= t < b - 1e-9 for a, b in self.cal.turno_colheita)

    def _fim_do_turno(self, t: float) -> Optional[float]:
        for a, b in self.cal.turno_colheita:
            if a - 1e-9 <= t < b - 1e-9:
                return b
        return None

    def _colher_talhao(self, h: AgenteColheitadeira, f: EstadoTalhao):
        env = self.env
        jan: Janelas = self.cal.janelas_colheitadeira(h.id)
        f.trabalhadores.add(h.id)
        if f.inicio is None:
            f.inicio = env.now
            self.log.add(env.now, "TALHAO_INICIO", h.id, "talhao", f.id)
        while f.area_livre > EPS_A:
            now = env.now
            if now >= self.horizonte - 1e-9:
                h.parado_horizonte = True
                break
            w_end = jan.window_end(now)
            if w_end is None:
                if h.tanque > EPS_T and self.cfg.simulacao.descarregar_fim_turno and not self._em_turno(now):
                    yield from self._descarregar_tanque(h, flush=True)
                    continue
                nxt = jan.next_open(now)
                alvo = self.horizonte if nxt is None else min(nxt, self.horizonte)
                fim_turno = self._fim_do_turno(now)
                if fim_turno is not None and fim_turno < alvo:
                    alvo = fim_turno  # reavalia no fim do turno (esvaziar tanque)
                yield from self._esperar_classificado(h, alvo, f)
                if nxt is None or nxt >= self.horizonte:
                    if env.now >= self.horizonte - 1e-9:
                        h.parado_horizonte = True
                        break
                continue
            espaco = h.spec.capacidade_tanque_t - h.tanque
            if espaco <= EPS_T:
                yield from self._descarregar_tanque(h)
                continue
            area = min(espaco / f.t_ha, f.area_livre)
            f.area_livre -= area
            dur = area / h.taxa_ha_min
            lim = min(w_end, self.horizonte) - now
            if h.ttf_h is not None:
                lim = min(lim, h.ttf_h * 60)
            fatia = min(dur, lim)
            a = area * (fatia / dur) if dur > 0 else area
            f.area_livre += area - a
            if f.area_livre < EPS_A:
                a += max(f.area_livre, 0.0)
                f.area_livre = 0.0
            self.st.set(h.id, "colheitadeira", "colhendo", talhao=f.id)
            yield env.timeout(fatia)
            t = a * f.t_ha
            h.tanque += t
            h.tanque_por_talhao[f.id] = h.tanque_por_talhao.get(f.id, 0.0) + t
            f.area_colhida += a
            f.t_colhidas += t
            h.horas_colheita += fatia / 60
            self.log.add(env.now, "COLHEITA", h.id, "colheitadeira", f.id, qtd_t=t, detalhe=f"{a:.3f} ha")
            if h.ttf_h is not None:
                h.ttf_h -= fatia / 60
                if h.ttf_h <= 1e-9:
                    yield from self._falha_colheitadeira(h)
            if h.tanque >= h.spec.capacidade_tanque_t - EPS_T:
                yield from self._descarregar_tanque(h)
            if f.fim is None and f.area_colhida >= f.talhao.area_ha - 1e-5:
                f.fim = env.now
                self.log.add(env.now, "TALHAO_CONCLUIDO", h.id, "talhao", f.id, qtd_t=f.t_colhidas)
        f.trabalhadores.discard(h.id)

    def _esperar_classificado(self, h: AgenteColheitadeira, t_alvo: float, f: EstadoTalhao):
        env = self.env
        for a, b, rot in self.cal.classificar_parada_colheitadeira(h.id, env.now, t_alvo):
            self.st.set(h.id, "colheitadeira", rot, talhao=f.id)
            if rot in ("falha", "parada_clima"):
                self.log.add(env.now, "PARADA_CLIMA" if rot == "parada_clima" else "FALHA_INFORMADA", h.id,
                             "colheitadeira", f.id, detalhe=f"{(b - a) / 60:.1f} h")
            yield env.timeout(b - a)

    def _falha_colheitadeira(self, h: AgenteColheitadeira):
        env = self.env
        dur = self.rng.reparo_h(f"reparo:{h.id}", h.spec.mttr_h) * 60
        self.st.set(h.id, "colheitadeira", "falha", talhao=h.talhao.id if h.talhao else None)
        self.log.add(env.now, "FALHA", h.id, "colheitadeira", h.talhao.id if h.talhao else "",
                     detalhe=f"reparo estimado {dur / 60:.1f} h")
        yield env.timeout(dur)
        self.log.add(env.now, "REPARO_CONCLUIDO", h.id, "colheitadeira")
        h.ttf_h = self.rng.ttf_h(f"falha:{h.id}", h.spec.mtbf_h)

    def _descarregar_tanque(self, h: AgenteColheitadeira, flush: bool = False):
        env = self.env
        while h.tanque > EPS_T:
            if not h.fila:
                h.esperando = True
                t0 = env.now
                self.st.set(h.id, "colheitadeira", "aguardando_caminhao", talhao=h.talhao.id)
                self.log.add(t0, "ESPERA_CAMINHAO_INICIO", h.id, "colheitadeira", h.talhao.id, qtd_t=h.tanque)
                h.ev_caminhao = env.event()
                yield h.ev_caminhao
                h.esperando = False
                self.log.add(env.now, "ESPERA_CAMINHAO_FIM", h.id, "colheitadeira", h.talhao.id,
                             detalhe=f"{env.now - t0:.1f} min")
                continue
            tk: AgenteCaminhao = h.fila[0]
            qtd = min(h.tanque, tk.cap - tk.carga_t)
            if tk.carga is None:
                tk.carga = self._nova_carga(tk)
                tk.carga.talhao_origem = h.talhao.id
            dur = h.spec.tempo_descarga_tanque_min * qtd / h.spec.capacidade_tanque_t * self.rng.fator(f"transbordo:{h.id}")
            self.st.set(h.id, "colheitadeira", "descarregando", talhao=h.talhao.id, carga=tk.carga.id)
            self.st.set(tk.id, "caminhao", "carregando", talhao=h.talhao.id, carga=tk.carga.id, carga_t=tk.carga_t,
                        colheitadeira=h.id)
            h.transferindo = True
            yield env.timeout(dur)
            h.transferindo = False
            frac = qtd / h.tanque
            for tid in list(h.tanque_por_talhao):
                parte = h.tanque_por_talhao[tid] * frac
                h.tanque_por_talhao[tid] -= parte
                tk.carga.por_talhao[tid] = tk.carga.por_talhao.get(tid, 0.0) + parte
                if h.tanque_por_talhao[tid] <= EPS_T * 1e-3:
                    del h.tanque_por_talhao[tid]
            tk.carga.por_colheitadeira[h.id] = tk.carga.por_colheitadeira.get(h.id, 0.0) + qtd
            h.tanque -= qtd
            if h.tanque < EPS_T:
                h.tanque = 0.0
                h.tanque_por_talhao.clear()
            tk.carga_t += qtd
            tk.carga.quantidade_t = tk.carga_t
            self.log.add(env.now, "TRANSBORDO", h.id, "colheitadeira", h.talhao.id, tk.carga.id, qtd,
                         detalhe=f"para {tk.id} ({tk.carga_t:.1f}/{tk.cap:.0f} t)")
            if tk.cap - tk.carga_t <= EPS_T:
                h.fila.popleft()
                tk.ev_saida.succeed()
            self._atualizar_fila(h)
        if flush:
            for tk in list(h.fila):
                if tk.carga_t > EPS_T:
                    h.fila.remove(tk)
                    tk.ev_saida.succeed()
            self._atualizar_fila(h)

    def _atualizar_fila(self, h: AgenteColheitadeira) -> None:
        """1º da fila: em carregamento (enchendo junto à máquina); demais: aguardando."""
        for i, tk in enumerate(h.fila):
            if i == 0 and h.transferindo:
                continue
            self.st.set(tk.id, "caminhao", "em_carregamento" if i == 0 else "aguardando_carregamento",
                        talhao=h.talhao.id, carga=tk.carga.id if tk.carga else None, carga_t=tk.carga_t, colheitadeira=h.id)

    def _liberar_fila(self, h: AgenteColheitadeira) -> None:
        while h.fila:
            tk = h.fila.popleft()
            if not tk.ev_saida.triggered:
                tk.ev_saida.succeed()

    # ------------------------------------------------------------------ caminhões
    def _atribuir(self, tk: AgenteCaminhao) -> Optional[AgenteColheitadeira]:
        ativos = [h for h in self.colheitadeiras if not h.concluida and h.talhao is not None]
        if tk.dedicado_a:
            for h in ativos:
                if h.id == tk.dedicado_a:
                    return h
        if not ativos:
            return None

        def chave(h: AgenteColheitadeira):
            # Despacho por menor folga: tempo até a colheitadeira ficar sem espaço para descarregar
            # (tanque + caminhões junto a ela + caminhões a caminho) menos o tempo de viagem até ela.
            espaco = (h.spec.capacidade_tanque_t - h.tanque + sum(t.cap - t.carga_t for t in h.fila) + h.a_caminho_cap)
            cobertura_min = espaco / max(h.taxa_t_h, 1e-6) * 60
            viagem_min = self._dist(tk.pos, h.talhao) / tk.spec.velocidade_vazio_km_h * 60
            return (1 if h.ocioso else 0, cobertura_min - viagem_min, h.id)

        return min(ativos, key=chave)

    def _verificar_falha_caminhao(self, tk: AgenteCaminhao):
        env = self.env
        while tk.falhas_forcadas and tk.falhas_forcadas[0][0] <= env.now + 1e-9:
            a, b = tk.falhas_forcadas.pop(0)
            dur = b - a  # entra em vigor ao fim do ciclo em andamento e dura o tempo informado
            self.st.set(tk.id, "caminhao", "falha")
            self.log.add(env.now, "FALHA", tk.id, "caminhao", detalhe=f"falha informada — {dur / 60:.1f} h")
            yield env.timeout(dur)
            self.log.add(env.now, "REPARO_CONCLUIDO", tk.id, "caminhao")
        if tk.ttf_h is not None and tk.ttf_h <= 0:
            dur = self.rng.reparo_h(f"reparo:{tk.id}", tk.spec.mttr_h) * 60
            self.st.set(tk.id, "caminhao", "falha")
            self.log.add(env.now, "FALHA", tk.id, "caminhao", detalhe=f"reparo estimado {dur / 60:.1f} h")
            yield env.timeout(dur)
            self.log.add(env.now, "REPARO_CONCLUIDO", tk.id, "caminhao")
            tk.ttf_h = self.rng.ttf_h(f"falha:{tk.id}", tk.spec.mtbf_h)

    def _viajar(self, tk: AgenteCaminhao, destino: Optional[EstadoTalhao], carregado: bool, estado: str):
        dist = self._dist(tk.pos, destino)
        if dist <= 0:
            tk.pos = destino
            return
        vel = tk.spec.velocidade_carregado_km_h if carregado else tk.spec.velocidade_vazio_km_h
        dur = dist / vel * 60 * self.rng.fator(f"viagem:{tk.id}")
        self.st.set(tk.id, "caminhao", estado, origem=self._nome(tk.pos), destino=self._nome(destino),
                    carga=tk.carga.id if tk.carga else None, carga_t=tk.carga_t,
                    talhao=destino.id if destino is not None else (tk.pos.id if tk.pos else None))
        yield self.env.timeout(dur)
        if carregado:
            tk.km_carregado += dist
        else:
            tk.km_vazio += dist
        if tk.ttf_h is not None:
            tk.ttf_h -= dur / 60
        tk.pos = destino

    def _proc_caminhao(self, tk: AgenteCaminhao):
        env = self.env
        jornada = self.cal.jornada_caminhoes
        while env.now < self.horizonte:
            nxt = jornada.next_open(env.now)
            if nxt is None or nxt >= self.horizonte:
                break
            if nxt > env.now:
                self.st.set(tk.id, "caminhao", "fora_jornada")
                yield env.timeout(nxt - env.now)
                continue
            yield from self._verificar_falha_caminhao(tk)
            h = self._atribuir(tk)
            if h is None:
                if all(c.concluida for c in self.colheitadeiras):
                    break
                self.st.set(tk.id, "caminhao", "fora_jornada" if tk.pos is None else "aguardando_carregamento",
                            talhao=tk.pos.id if tk.pos else None)
                yield self._ev_pronta
                continue
            # ---- deslocamento vazio até a colheitadeira (segue a máquina se ela mudar de talhão)
            h.a_caminho += 1
            h.a_caminho_cap += tk.cap
            while not h.concluida and tk.pos is not h.talhao:
                yield from self._viajar(tk, h.talhao, carregado=False, estado="retorno_vazio")
            if h.concluida:
                h.a_caminho -= 1
                h.a_caminho_cap -= tk.cap
                continue
            self.st.set(tk.id, "caminhao", "manobra", talhao=h.talhao.id, colheitadeira=h.id)
            yield env.timeout(tk.spec.tempo_manobra_min * self.rng.fator(f"manobra:{tk.id}"))
            h.a_caminho -= 1
            h.a_caminho_cap -= tk.cap
            if h.concluida:
                continue
            tk.pos = h.talhao
            tk.ev_saida = env.event()
            h.fila.append(tk)
            self._atualizar_fila(h)
            self.log.add(env.now, "CAMINHAO_CHEGA_CAMPO", tk.id, "caminhao", h.talhao.id, detalhe=f"atende {h.id}")
            if h.esperando and h.ev_caminhao is not None and not h.ev_caminhao.triggered:
                h.ev_caminhao.succeed()
            yield tk.ev_saida
            if tk.carga_t <= EPS_T:
                continue  # liberado vazio (colheitadeira concluiu)
            # ---- transporte carregado
            carga = tk.carga
            origem = tk.pos
            carga.t_saida_campo = env.now
            carga.status = "em_transito"
            carga.talhao_origem = origem.id
            carga.distancia_km = origem.talhao.distancia_km
            self.log.add(env.now, "SAIDA_CAMPO", tk.id, "caminhao", origem.id, carga.id, tk.carga_t)
            yield from self._viajar(tk, None, carregado=True, estado="transporte_carregado")
            carga.t_chegada_unidade = env.now
            carga.status = "na_fila"
            self.log.add(env.now, "CHEGADA_UNIDADE", tk.id, "caminhao", origem.id, carga.id, tk.carga_t,
                         detalhe=f"fila: {len(self.moegas.queue)} na espera, {self.moegas.count} descarregando")
            self.st.set(tk.id, "caminhao", "fila_descarga", carga=carga.id, carga_t=tk.carga_t)
            req = self.moegas.request()
            yield req
            nxt = self.cal.unidade.next_open(env.now)
            if nxt is None or nxt >= self.horizonte:
                yield env.timeout(max(self.horizonte - env.now, 0))
                self.moegas.release(req)
                break
            if nxt > env.now:
                yield env.timeout(nxt - env.now)
            taxa = self.cfg.recebimento.taxa_por_moega_t_h * self.cal.fator_capacidade(env.now)
            servico = (self.cfg.recebimento.tempo_fixo_min + tk.carga_t / taxa * 60) * self.rng.fator(f"descarga:{tk.id}")
            carga.t_inicio_descarga = env.now
            self.st.set(tk.id, "caminhao", "descarregando", carga=carga.id, carga_t=tk.carga_t)
            self.log.add(env.now, "INICIO_DESCARGA", tk.id, "caminhao", origem.id, carga.id, tk.carga_t)
            yield env.timeout(servico)
            self.moegas.release(req)
            carga.t_fim_descarga = env.now
            carga.status = "entregue"
            carga.quantidade_t = tk.carga_t
            self.entregue_t += tk.carga_t
            tk.viagens += 1
            self.log.add(env.now, "FIM_DESCARGA", tk.id, "caminhao", origem.id, carga.id, tk.carga_t)
            tk.carga_t = 0.0
            tk.carga = None
            self._verificar_fim()
        self.st.set(tk.id, "caminhao", "concluido")

    # ------------------------------------------------------------------ execução
    def executar(self) -> SimulationResult:
        t0 = time.perf_counter()
        env = self.env
        for h in self.colheitadeiras:
            env.process(self._proc_colheitadeira(h))
        for tk in self.caminhoes:
            env.process(self._proc_caminhao(tk))
        env.run(until=self.horizonte)
        t_ref = self.t_fim if self.t_fim is not None else min(env.now, self.horizonte)
        self.st.close_all(env.now)
        segs = self._pos_processar_segmentos(self.st.segmentos, t_ref)
        res = SimulationResult.build(self, segs, t_ref, time.perf_counter() - t0)
        log.info("Simulação '%s' (semente %s): %s, %.1f t entregues em %.1f h — %d eventos, %.2fs",
                 self.cfg.nome, self.cfg.simulacao.semente, "concluída" if res.concluida else "INCOMPLETA",
                 res.entregue_t, t_ref / 60, len(self.log.eventos), res.tempo_execucao_s)
        return res

    def _pos_processar_segmentos(self, segs: list[Segmento], t_ref: float) -> list[Segmento]:
        """Recorta no fim da operação e reclassifica esperas fora de jornada/horário da unidade."""
        jornada = self.cal.jornada_caminhoes.intervals
        unidade = self.cal.unidade.intervals

        def dividir(seg: Segmento, janelas: list, estado_fora: str) -> list[Segmento]:
            iv = [(seg.inicio, seg.fim)]
            fora = subtract(iv, janelas)
            dentro = subtract(iv, fora)
            partes = [(a, b, seg.estado) for a, b in dentro] + [(a, b, estado_fora) for a, b in fora]
            return [Segmento(**{**seg.__dict__, "inicio": a, "fim": b, "estado": e}) for a, b, e in sorted(partes)]

        out: list[Segmento] = []
        for s in segs:
            if s.inicio >= t_ref - 1e-9:
                continue
            base = Segmento(**{**s.__dict__, "fim": min(s.fim, t_ref)})
            if s.tipo != "caminhao":
                out.append(base)
                continue
            etapa = [base]
            if s.estado == "em_carregamento" and s.colheitadeira:
                # só é "enchendo" enquanto a colheitadeira está dentro da sua janela de trabalho
                etapa = dividir(base, self.cal.janelas_colheitadeira(s.colheitadeira).intervals, "aguardando_carregamento")
            final: list[Segmento] = []
            for p in etapa:
                if p.estado == "aguardando_carregamento":
                    final.extend(dividir(p, jornada, "fora_jornada"))
                elif p.estado == "fila_descarga":
                    final.extend(dividir(p, unidade, "fila_unidade_fechada"))
                else:
                    final.append(p)
            out.extend(final)
        return out


def simular(cfg: OperationConfig) -> SimulationResult:
    """Executa uma simulação completa e retorna os resultados."""
    return Simulador(cfg).executar()


def hash_resultado(res: SimulationResult) -> str:
    payload = json.dumps(
        [[round(c["t_fim_descarga"] or -1, 6), round(c["quantidade_t"], 6), c["caminhao"]] for c in res.cargas.to_dict("records")],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
