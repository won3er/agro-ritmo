"""Janelas de trabalho: turnos, chuva, manutenção programada, falhas forçadas e horário da unidade.

Todas as janelas são listas ordenadas de intervalos ``(inicio_min, fim_min)`` disjuntos.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from ..domain.models import OperationConfig
from ..domain.units import MIN_POR_DIA

Intervalo = tuple[float, float]
EPS = 1e-9


def merge(intervals: list[Intervalo]) -> list[Intervalo]:
    out: list[list[float]] = []
    for a, b in sorted(i for i in intervals if i[1] - i[0] > EPS):
        if out and a <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def subtract(base: list[Intervalo], blocks: list[Intervalo]) -> list[Intervalo]:
    blocks = merge(blocks)
    out: list[Intervalo] = []
    for a, b in base:
        cur = a
        for c, d in blocks:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
            if cur >= b:
                break
        if b - cur > EPS:
            out.append((cur, b))
    return out


def daily(start_h: float, end_h: float, days: int, offset_min: float = 0.0) -> list[Intervalo]:
    return merge([(d * MIN_POR_DIA + start_h * 60 + offset_min, d * MIN_POR_DIA + end_h * 60) for d in range(days)])


def total(intervals: list[Intervalo], t0: float = 0.0, t1: float = float("inf")) -> float:
    s = 0.0
    for a, b in intervals:
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo:
            s += hi - lo
    return s


@dataclass
class Janelas:
    intervals: list[Intervalo]
    _starts: list[float] = field(init=False, repr=False)

    def __post_init__(self):
        self.intervals = merge(self.intervals)
        self._starts = [a for a, _ in self.intervals]

    def window_end(self, t: float):
        """Fim da janela que contém t (None se t está fora de janela)."""
        i = bisect.bisect_right(self._starts, t + EPS) - 1
        if i >= 0:
            a, b = self.intervals[i]
            if a - EPS <= t < b - EPS:
                return b
        return None

    def next_open(self, t: float):
        """t se estiver dentro de uma janela; caso contrário, início da próxima (None se não houver)."""
        if self.window_end(t) is not None:
            return t
        i = bisect.bisect_right(self._starts, t + EPS)
        if i < len(self.intervals):
            return self.intervals[i][0]
        return None

    def total(self, t0: float = 0.0, t1: float = float("inf")) -> float:
        return total(self.intervals, t0, t1)


class Calendario:
    """Constrói as janelas da operação a partir da configuração."""

    def __init__(self, cfg: OperationConfig, rng_clima: np.random.Generator):
        self.cfg = cfg
        j = cfg.janela
        self.horizonte_min = j.horizonte_dias * MIN_POR_DIA
        dias = j.horizonte_dias

        # --- chuva (informada + aleatória) -> bloqueio da colheita incluindo secagem
        self.chuvas: list[Intervalo] = []
        for ev in cfg.clima.eventos_chuva:
            a = (ev.dia - 1) * MIN_POR_DIA + ev.hora_inicio * 60
            self.chuvas.append((a, a + ev.duracao_h * 60))
        if cfg.clima.prob_chuva_dia > 0:
            for d in range(dias):
                if rng_clima.random() < cfg.clima.prob_chuva_dia:
                    h0 = rng_clima.uniform(0, 24)
                    dur = max(0.5, rng_clima.exponential(cfg.clima.duracao_media_chuva_h))
                    a = d * MIN_POR_DIA + h0 * 60
                    self.chuvas.append((a, a + dur * 60))
        self.chuvas = merge(self.chuvas)
        espera = cfg.clima.espera_pos_chuva_h * 60
        self.bloqueio_clima = merge([(a, b + espera) for a, b in self.chuvas])

        # --- turnos
        self.turno_colheita = daily(j.colheita_inicio_h, j.colheita_fim_h, dias)
        self.jornada_caminhoes = Janelas(daily(j.caminhoes_inicio_h, j.caminhoes_fim_h, dias))

        # --- unidade de recebimento (horário menos interrupções)
        r = cfg.recebimento
        interrupcoes = [(e.inicio_min, e.fim_min) for e in cfg.eventos if e.tipo == "interrupcao_recebimento"]
        self.interrupcoes_unidade = merge(interrupcoes)
        self.unidade = Janelas(subtract(daily(r.hora_abertura, r.hora_fechamento, dias), interrupcoes))

        # --- mudanças de capacidade da unidade (fator multiplicativo por período)
        self.fatores_capacidade = sorted(
            (e.inicio_min, e.fim_min if e.duracao_h > 0 else float("inf"), e.valor)
            for e in cfg.eventos if e.tipo == "capacidade_recebimento"
        )

        # --- falhas forçadas por recurso
        self.falhas_forcadas: dict[str, list[Intervalo]] = {}
        for e in cfg.eventos:
            if e.tipo == "falha_forcada":
                self.falhas_forcadas.setdefault(e.recurso_id, []).append((e.inicio_min, e.fim_min))

        self._janelas_colh: dict[str, Janelas] = {}
        self._manut: dict[str, list[Intervalo]] = {}
        for c in cfg.colheitadeiras:
            manut = [(a, min(b, a + c.parada_programada_min_dia)) for a, b in self.turno_colheita]
            self._manut[c.id] = manut
            base = subtract(self.turno_colheita, manut)
            bloqueios = self.bloqueio_clima + self.falhas_forcadas.get(c.id, [])
            self._janelas_colh[c.id] = Janelas(subtract(base, bloqueios))

    def janelas_colheitadeira(self, hid: str) -> Janelas:
        return self._janelas_colh[hid]

    def fator_capacidade(self, t: float) -> float:
        f = 1.0
        for a, b, v in self.fatores_capacidade:
            if a <= t < b:
                f *= v
        return f

    def classificar_parada_colheitadeira(self, hid: str, t0: float, t1: float) -> list[tuple[float, float, str]]:
        """Divide [t0, t1) em segmentos rotulados pelo motivo da parada."""
        if t1 - t0 <= EPS:
            return []
        rotulos = [
            ("falha", merge(self.falhas_forcadas.get(hid, []))),
            ("parada_clima", self.bloqueio_clima),
            ("manutencao_programada", self._manut[hid]),
        ]
        pontos = {t0, t1}
        for _, ints in rotulos:
            for a, b in ints:
                if t0 < a < t1:
                    pontos.add(a)
                if t0 < b < t1:
                    pontos.add(b)
        for a, b in self.turno_colheita:
            if t0 < a < t1:
                pontos.add(a)
            if t0 < b < t1:
                pontos.add(b)
        ps = sorted(pontos)
        segs: list[tuple[float, float, str]] = []
        for a, b in zip(ps[:-1], ps[1:]):
            mid = (a + b) / 2
            rot = None
            for nome, ints in rotulos:
                if any(c <= mid < d for c, d in ints):
                    rot = nome
                    break
            if rot is None:
                em_turno = any(c <= mid < d for c, d in self.turno_colheita)
                rot = "ocioso" if em_turno else "fora_turno"
            if segs and segs[-1][2] == rot and abs(segs[-1][1] - a) < EPS:
                segs[-1] = (segs[-1][0], b, rot)
            else:
                segs.append((a, b, rot))
        return segs
