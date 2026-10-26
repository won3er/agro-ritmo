"""Gera um vídeo curto (10 s, 1080×1080, MP4) para divulgação a partir do simulador visual real.

Os quadros da simulação são capturas do próprio player (vitrine/simulador.html) posicionado em instantes
sucessivos da execução de exemplo — nada é desenhado à parte. Requer: playwright, imageio-ffmpeg e um Chrome local.

    .venv/Scripts/python scripts/gerar_video.py [caminho_do_chrome]
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
SIMULADOR = RAIZ / "vitrine" / "simulador.html"
SAIDA = RAIZ / "docs" / "media" / "agroritmo.mp4"
CHROME = sys.argv[1] if len(sys.argv) > 1 else "C:/Program Files/Google/Chrome/Application/chrome.exe"

W = H = 1080
FPS = 30
N_INTRO, N_SIM, N_FIM = 45, 180, 75  # 1,5 s + 6 s + 2,5 s = 10 s
# D5 13:30 → D5 19:30 (1 h de operação por segundo): trecho com espera por caminhão e fila nas moegas
T0_MIN = 4 * 1440 + 13.5 * 60
T1_MIN = T0_MIN + 6 * 60

FUNDO = (14, 19, 22)
TEXTO = (228, 234, 239)
SUAVE = (147, 161, 173)
VERDE = (47, 168, 102)
AMBAR = (240, 167, 58)


def fonte(tam: int, negrito: bool = False) -> ImageFont.FreeTypeFont:
    nome = "segoeuib.ttf" if negrito else "segoeui.ttf"
    try:
        return ImageFont.truetype(f"C:/Windows/Fonts/{nome}", tam)
    except OSError:
        import matplotlib
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        return ImageFont.truetype(str(base / ("DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf")), tam)


def centro(d: ImageDraw.ImageDraw, y: int, s: str, f, cor) -> None:
    w = d.textlength(s, font=f)
    d.text(((W - w) / 2, y), s, font=f, fill=cor)


def capturar() -> list[tuple[Image.Image, Image.Image]]:
    """Captura (faixa de indicadores, mapa) para cada quadro da janela simulada."""
    quadros = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME)
        pg = nav.new_page(viewport={"width": 1000, "height": 760}, device_scale_factor=2)
        pg.goto(SIMULADOR.as_uri())
        pg.wait_for_timeout(800)
        kpis = pg.locator("#kpis").bounding_box()
        cv = pg.locator("#cv").bounding_box()
        for i in range(N_SIM):
            t = T0_MIN + (T1_MIN - T0_MIN) * i / (N_SIM - 1)
            pg.evaluate(f"t = {t}; render()")
            png = pg.screenshot(clip={"x": 0, "y": 0, "width": 1000, "height": kpis["y"] + kpis["height"]})
            mapa = pg.screenshot(clip=cv)
            quadros.append((Image.open(io.BytesIO(png)).convert("RGB"), Image.open(io.BytesIO(mapa)).convert("RGB")))
        nav.close()
    return quadros


def quadro_intro(k: int) -> Image.Image:
    im = Image.new("RGB", (W, H), FUNDO)
    d = ImageDraw.Draw(im)
    d.rectangle([W / 2 - 60, 360, W / 2 + 60, 366], fill=VERDE)
    centro(d, 400, "AgroRitmo", fonte(120, True), TEXTO)
    centro(d, 560, "Colheita e transporte de grãos", fonte(46), TEXTO)
    centro(d, 620, "simulados minuto a minuto", fonte(46), TEXTO)
    centro(d, 740, "Simulação de eventos discretos  ·  Otimização  ·  Gargalos", fonte(30), SUAVE)
    return im


def quadro_sim(kpi: Image.Image, mapa: Image.Image, i: int) -> Image.Image:
    im = Image.new("RGB", (W, H), FUNDO)
    d = ImageDraw.Draw(im)
    d.text((40, 34), "AgroRitmo", font=fonte(44, True), fill=TEXTO)
    d.text((40, 92), "Cada movimento vem de um evento registrado pelo simulador", font=fonte(27), fill=SUAVE)
    badge = "1 h de operação por segundo"
    fb = fonte(24, True)
    bw = d.textlength(badge, font=fb)
    d.rounded_rectangle([W - 40 - bw - 28, 44, W - 40, 88], 22, outline=AMBAR, width=2)
    d.text((W - 40 - bw - 14, 50), badge, font=fb, fill=AMBAR)

    larg = W - 60
    k = kpi.resize((larg, round(kpi.height * larg / kpi.width)), Image.LANCZOS)
    m = mapa.resize((larg, round(mapa.height * larg / mapa.width)), Image.LANCZOS)
    y = 150 + (H - 150 - 70 - (k.height + 14 + m.height + 50)) // 2  # centraliza o bloco entre o título e o rodapé
    im.paste(k, (30, y))
    y += k.height + 14
    im.paste(m, (30, y))
    y += m.height + 18

    legendas = [((47, 168, 102), "colhendo"), ((240, 167, 58), "sem caminhão"), ((61, 123, 224), "transporte"),
                ((224, 82, 77), "fila na moega"), ((208, 75, 196), "falha")]
    f = fonte(24)
    x = 40
    for cor, rot in legendas:
        d.ellipse([x, y + 8, x + 16, y + 24], fill=cor)
        d.text((x + 24, y), rot, font=f, fill=TEXTO)
        x += 24 + d.textlength(rot, font=f) + 34
    d.text((40, H - 54), "Dados sintéticos de exemplo · soja · 1.120 ha · 3 colheitadeiras · 6 caminhões", font=fonte(22), fill=SUAVE)
    return im


def quadro_fim(k: int) -> Image.Image:
    im = Image.new("RGB", (W, H), FUNDO)
    d = ImageDraw.Draw(im)
    centro(d, 150, "AgroRitmo", fonte(84, True), TEXTO)
    itens = ["Encontra gargalos com evidência e fórmula",
             "Testa cada recomendação em nova simulação",
             "Dimensiona a frota com OR-Tools (CP-SAT)",
             "Compara cenários com intervalo de confiança"]
    f = fonte(38)
    y = 320
    for s in itens:
        d.ellipse([150, y + 16, 168, y + 34], fill=VERDE)
        d.text((190, y), s, font=f, fill=TEXTO)
        y += 76
    centro(d, 660, "Python · SimPy · OR-Tools · Pandas · Plotly · Streamlit", fonte(30), SUAVE)
    centro(d, 790, "agroritmo-one.vercel.app", fonte(40, True), VERDE)
    centro(d, 850, "github.com/won3er/agro-ritmo", fonte(34), TEXTO)
    return im


def misturar(a: Image.Image, b: Image.Image, s: float) -> Image.Image:
    return Image.blend(a, b, max(0.0, min(1.0, s)))


def main() -> None:
    print("Capturando quadros do simulador...")
    sim = [quadro_sim(k, m, i) for i, (k, m) in enumerate(capturar())]
    intro = quadro_intro(0)
    fim = quadro_fim(0)
    preto = Image.new("RGB", (W, H), FUNDO)
    TR = 8  # quadros de transição

    quadros: list[Image.Image] = []
    for i in range(N_INTRO):
        q = misturar(preto, intro, i / TR) if i < TR else intro
        quadros.append(misturar(q, sim[0], (i - (N_INTRO - TR)) / TR) if i >= N_INTRO - TR else q)
    quadros += sim
    for i in range(N_FIM):
        quadros.append(misturar(sim[-1], fim, (i + 1) / TR))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-crf", "20", "-preset", "slow",
           "-movflags", "+faststart", str(SAIDA)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for q in quadros:
        proc.stdin.write(np.asarray(q, dtype=np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()
    print(f"{len(quadros)} quadros ({len(quadros) / FPS:.1f} s) -> {SAIDA} ({SAIDA.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
