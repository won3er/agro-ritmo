"""Relatório PDF para gestores: premissas, resultados, gráficos, gargalos e recomendações."""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.fonts import addMapping  # noqa: F401  (mantido para versões antigas do reportlab)
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .. import __version__
from ..analytics.bottlenecks import AVALIACOES
from ..analytics.costs import resumo_custos
from ..analytics.kpis import composicao_ciclo
from ..domain.models import OrigemDado
from ..domain.units import brl, formatar_relogio, num
from ..theme import CORES_SEVERIDADE, CORES_TIPO_DADO
from . import charts
from .export import PacoteRelatorio

_FONTES_OK = False


def _registrar_fontes() -> tuple[str, str]:
    """DejaVu Sans (vem com o matplotlib) cobre símbolos como Σ, ×, → e ≤."""
    global _FONTES_OK
    if not _FONTES_OK:
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DejaVu", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(base / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(base / "DejaVuSans-Oblique.ttf")))
        registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Oblique", boldItalic="DejaVu-Bold")
        _FONTES_OK = True
    return "DejaVu", "DejaVu-Bold"


VERDE = colors.HexColor("#1F7A4A")
CINZA = colors.HexColor("#5A636E")
CLARO = colors.HexColor("#EEF2F4")


def _estilos():
    f, fb = _registrar_fontes()
    ss = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("titulo", parent=ss["Title"], fontName=fb, fontSize=22, leading=27, textColor=colors.HexColor("#14202A"),
                                 alignment=TA_LEFT),
        "sub": ParagraphStyle("sub", fontName=f, fontSize=11, leading=15, textColor=CINZA),
        "h1": ParagraphStyle("h1", fontName=fb, fontSize=14, leading=18, textColor=VERDE, spaceBefore=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=fb, fontSize=10.5, leading=14, textColor=colors.HexColor("#14202A"), spaceBefore=6, spaceAfter=3),
        "p": ParagraphStyle("p", fontName=f, fontSize=9, leading=12.5),
        "pq": ParagraphStyle("pq", fontName=f, fontSize=7.6, leading=10, textColor=CINZA),
        "cel": ParagraphStyle("cel", fontName=f, fontSize=7.4, leading=9.2),
        "celb": ParagraphStyle("celb", fontName=fb, fontSize=7.4, leading=9.2),
        "aviso": ParagraphStyle("aviso", fontName=fb, fontSize=9, leading=12, textColor=colors.HexColor("#8A5A00"),
                                backColor=colors.HexColor("#FFF4DC"), borderPadding=6),
    }


def _tabela(dados: list[list], larguras: list[float], est, cabecalho=True, zebra=True) -> Table:
    linhas = [[c if not isinstance(c, str) else Paragraph(c, est["celb"] if (cabecalho and i == 0) else est["cel"])
               for c in row] for i, row in enumerate(dados)]
    t = Table(linhas, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, CINZA),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if cabecalho:
        st.append(("BACKGROUND", (0, 0), (-1, 0), CLARO))
    if zebra:
        for i in range(1, len(linhas)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFB")))
    t.setStyle(TableStyle(st))
    return t


def _img(png: bytes, largura_cm: float = 17.0) -> Image:
    im = Image(io.BytesIO(png))
    r = im.imageHeight / im.imageWidth
    im.drawWidth = largura_cm * cm
    im.drawHeight = largura_cm * cm * r
    return im


def _rodape(canvas, doc):
    f, _ = _registrar_fontes()
    canvas.saveState()
    canvas.setFont(f, 7)
    canvas.setFillColor(CINZA)
    canvas.drawString(1.6 * cm, 1.0 * cm, f"AgroRitmo {__version__} — relatório de simulação")
    canvas.drawRightString(A4[0] - 1.6 * cm, 1.0 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _sumario(p: PacoteRelatorio) -> list[str]:
    k = dict(zip(p.kpis["chave"], p.kpis["valor"]))
    res = p.res
    cfg = res.config
    frases = []
    if res.concluida:
        frases.append(f"A operação colheu e entregou <b>{num(k['t_entregues'], 0)} t</b> de {cfg.crop.nome.lower()} em "
                      f"<b>{num(k['duracao_h'], 1)} h</b> ({int(k['dias_operacao'])} dias de calendário), concluindo "
                      f"{num(k['pct_area'], 0)}% da área.")
    else:
        frases.append(f"<b>A operação NÃO concluiu dentro da janela de {cfg.janela.horizonte_dias} dias</b>: foram entregues "
                      f"{num(k['t_entregues'], 0)} t ({num(k['pct_area'], 0)}% da área).")
    frases.append(f"Custo operacional total calculado: <b>{brl(k['custo_total'])}</b>, equivalente a "
                  f"<b>{brl(k['custo_por_t'] or 0)}/t</b>.")
    frases.append(f"Utilização: colheitadeiras colhendo {num(k['util_colheitadeiras'], 0)}% do turno; caminhões em atividade "
                  f"{num(k['util_caminhoes'], 0)}% da jornada; moegas ocupadas {num(k['util_recepcao'], 0)}% do horário aberto.")
    frases.append(f"Esperas: colheitadeiras aguardaram caminhão por {num(k['espera_colh_caminhao_h'], 1)} h; caminhões ficaram "
                  f"{num(k['fila_descarga_h'], 1)} h em fila de descarga (fila máxima de {int(k['fila_max'])}).")
    if p.gargalos:
        g = p.gargalos[0]
        txt = f"Principal gargalo: <b>{g.titulo}</b> — {g.evidencia}"
        if g.impacto:
            txt += f" Recomendação testada ({g.validacao.nome}): {g.impacto['resumo']} — {AVALIACOES[g.impacto['avaliacao']].lower()}."
        frases.append(txt)
    return frases


def gerar_pdf(p: PacoteRelatorio) -> bytes:
    est = _estilos()
    res = p.res
    cfg = res.config
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.5 * cm,
                            bottomMargin=1.6 * cm, title=f"AgroRitmo — {cfg.nome}", author="AgroRitmo")
    W = A4[0] - 3.2 * cm
    s: list = []

    # ── capa
    s.append(Spacer(1, 2.2 * cm))
    s.append(Paragraph("AgroRitmo", ParagraphStyle("marca", fontName=_registrar_fontes()[1], fontSize=12, textColor=VERDE)))
    s.append(Spacer(1, 0.3 * cm))
    s.append(Paragraph("Relatório de simulação da operação de colheita e transporte", est["titulo"]))
    s.append(Spacer(1, 0.4 * cm))
    s.append(Paragraph(f"{cfg.nome}", est["sub"]))
    s.append(Paragraph(f"Cultura: {cfg.crop.nome} · Área: {num(cfg.area_total_ha, 0)} ha · Gerado em {p.gerado_em}", est["sub"]))
    s.append(Spacer(1, 0.8 * cm))
    if cfg.origem_dados == OrigemDado.EXEMPLO:
        s.append(Paragraph("CENÁRIO SINTÉTICO DE EXEMPLO — os parâmetros são ilustrativos, não são médias oficiais do setor "
                           "nem dados de uma fazenda real.", est["aviso"]))
        s.append(Spacer(1, 0.4 * cm))
    s.append(Paragraph("Os resultados são produzidos por simulação de eventos discretos a partir dos parâmetros informados. "
                       "Sem calibração e validação com dados observados, eles não devem ser tomados como representação fiel "
                       "de uma operação real.", est["pq"]))
    s.append(Spacer(1, 0.6 * cm))
    s.append(_tabela([["Reprodutibilidade", ""], ["Semente aleatória", str(cfg.simulacao.semente)],
                      ["Hash do resultado", p.hash], ["Variabilidade dos tempos (CV)", num(cfg.simulacao.variabilidade_cv, 2)],
                      ["Versão", __version__]], [6 * cm, 6 * cm], est))

    # ── sumário executivo
    s.append(PageBreak())
    s.append(Paragraph("1. Sumário executivo", est["h1"]))
    for fr in _sumario(p):
        s.append(Paragraph("• " + fr, est["p"]))
        s.append(Spacer(1, 3))
    s.append(Spacer(1, 6))
    s.append(Paragraph("Legenda de origem dos números: <b>MEDIDO</b> = observado nos eventos da simulação; <b>CALCULADO</b> = fórmula "
                       "sobre valores medidos e informados; <b>INFORMADO</b> = parâmetro de entrada; <b>ESTIMADO</b> = projeção "
                       "aproximada.", est["pq"]))

    s.append(Paragraph("2. Indicadores", est["h1"]))
    linhas = [["Indicador", "Valor", "Unidade", "Origem", "Como é obtido"]]
    for _, r in p.kpis.iterrows():
        v = r["valor"]
        txt = "—" if v is None or pd.isna(v) else (brl(v) if r["unidade"] == "R$" else num(v, 2 if abs(v) < 100 else 1))
        cor = CORES_TIPO_DADO.get(r["tipo"], "#333")
        linhas.append([r["rotulo"], txt, r["unidade"], f'<font color="{cor}"><b>{r["tipo"].upper()}</b></font>', r["formula"] or ""])
    s.append(_tabela(linhas, [5.2 * cm, 2.4 * cm, 2.0 * cm, 2.2 * cm, W - 11.8 * cm], est))

    # ── gráficos
    s.append(PageBreak())
    s.append(Paragraph("3. Evolução da operação", est["h1"]))
    s.append(Paragraph("Produção colhida e entregue ao longo do tempo (a faixa âmbar é o volume em tanques e caminhões).", est["pq"]))
    s.append(_img(charts.producao_acumulada(p.serie)))
    s.append(Paragraph("Filas: caminhões aguardando descarga e colheitadeiras aguardando caminhão.", est["pq"]))
    s.append(_img(charts.filas(p.serie)))
    s.append(Paragraph("4. Utilização dos recursos", est["h1"]))
    s.append(_img(charts.utilizacao(p.util_colheitadeiras, "colheitadeira",
                                    ["colhendo", "descarregando", "aguardando_caminhao", "deslocando", "manutencao_programada",
                                     "falha", "parada_clima", "ocioso"])))
    s.append(_img(charts.utilizacao(p.util_caminhoes, "caminhao",
                                    ["em_carregamento", "carregando", "manobra", "transporte_carregado", "fila_descarga",
                                     "descarregando", "retorno_vazio", "aguardando_carregamento", "fila_unidade_fechada", "falha"])))
    cc = composicao_ciclo(res)
    if len(cc):
        s.append(Paragraph("Composição média do ciclo do caminhão (minutos por carga)", est["h2"]))
        s.append(_tabela([["Etapa", "min/carga"]] + [[r["etapa"], num(r["min_por_carga"], 1)] for _, r in cc.iterrows()],
                         [8 * cm, 3 * cm], est))

    # ── custos
    s.append(PageBreak())
    s.append(Paragraph("5. Custos", est["h1"]))
    s.append(_img(charts.composicao_custos(resumo_custos(p.custos))))
    s.append(Paragraph("Detalhamento com fórmulas (todas as taxas são parâmetros informados).", est["h2"]))
    linhas = [["Categoria", "Recurso", "Componente", "Fórmula", "Valor"]]
    for _, r in p.custos.iterrows():
        linhas.append([r["categoria"], r["recurso"], r["componente"], r["formula"], brl(r["valor"])])
    linhas.append(["", "", "<b>Total</b>", "", f"<b>{brl(p.custos['valor'].sum())}</b>"])
    s.append(_tabela(linhas, [2.4 * cm, 2.0 * cm, 3.6 * cm, W - 10.6 * cm, 2.6 * cm], est))

    # ── gargalos
    s.append(PageBreak())
    s.append(Paragraph("6. Gargalos e recomendações", est["h1"]))
    if not p.gargalos:
        s.append(Paragraph("Nenhum gargalo relevante identificado pelas regras de análise.", est["p"]))
    for i, g in enumerate(p.gargalos, 1):
        cor = CORES_SEVERIDADE[g.severidade]
        bloco = [Paragraph(f'{i}. {g.titulo} <font color="{cor}">[{ {"alta": "ALTA", "media": "MÉDIA", "baixa": "BAIXA"}[g.severidade] }]</font>', est["h2"]),
                 Paragraph(f"<b>Evidência:</b> {g.evidencia}", est["p"]),
                 Paragraph(f"<b>Duração / frequência:</b> {num(g.duracao_h, 1)} h · {g.frequencia} ocorrência(s) · "
                           f"<b>Recursos:</b> {', '.join(g.recursos) or '—'}", est["p"]),
                 Paragraph(f"<b>Consequência estimada:</b> {num(g.consequencia_tempo_h, 1)} h · {num(g.consequencia_volume_t, 1)} t · "
                           f"{brl(g.consequencia_rs)}", est["p"]),
                 Paragraph(f"<b>Fórmula:</b> {g.formula_rs}", est["pq"]),
                 Paragraph(f"<b>Recomendação:</b> {g.recomendacao}", est["p"])]
        if g.impacto:
            bloco.append(Paragraph(f"<b>Validação por nova simulação</b> ({g.impacto['descricao']}, mesma semente): "
                                   f"{g.impacto['resumo']}. <i>{AVALIACOES[g.impacto['avaliacao']]}.</i>", est["p"]))
        elif g.validacao is None:
            bloco.append(Paragraph("<i>Sem cenário de validação automática para este item.</i>", est["pq"]))
        bloco.append(Spacer(1, 5))
        s.append(KeepTogether(bloco))

    # ── cenários
    if p.comparacao is not None and len(p.comparacao):
        s.append(PageBreak())
        s.append(Paragraph("7. Comparação de cenários", est["h1"]))
        tab = p.comparacao
        s.append(_img(charts.comparacao_cenarios(tab)))
        linhas = [["Cenário", "Duração (h)", "t entregues", "Custo total", "R$/t", "Espera colh. (h)", "Fila (h)", "Concluída"]]
        for _, r in tab.iterrows():
            linhas.append([r["cenario"], num(r["duracao_h"], 1), num(r["t_entregues"], 0), brl(r["custo_total"]),
                           brl(r["custo_por_t"] or 0), num(r["espera_colh_caminhao_h"], 1), num(r["fila_descarga_h"], 1),
                           "sim" if r["concluida"] >= 0.999 else "não"])
        s.append(_tabela(linhas, [4.2 * cm, 1.8 * cm, 1.9 * cm, 2.6 * cm, 1.8 * cm, 1.8 * cm, 1.4 * cm, W - 15.5 * cm], est))
        if "justificativa" in p.otimizacao:
            s.append(Spacer(1, 4))
            s.append(Paragraph(str(p.otimizacao["justificativa"]), est["p"]))

    # ── premissas
    s.append(PageBreak())
    s.append(Paragraph("8. Premissas da simulação", est["h1"]))
    j = cfg.janela
    s.append(Paragraph(f"Turno de colheita {j.colheita_inicio_h:.0f}h–{j.colheita_fim_h:.0f}h; jornada dos caminhões "
                       f"{j.caminhoes_inicio_h:.0f}h–{j.caminhoes_fim_h:.0f}h; unidade aberta {cfg.recebimento.hora_abertura:.0f}h–"
                       f"{cfg.recebimento.hora_fechamento:.0f}h; janela disponível de {j.horizonte_dias} dias. "
                       f"Chuvas informadas: {len(cfg.clima.eventos_chuva)}; probabilidade diária de chuva aleatória "
                       f"{num(cfg.clima.prob_chuva_dia * 100, 0)}%. Eventos operacionais: {len(cfg.eventos)}.", est["p"]))
    s.append(Paragraph("Talhões", est["h2"]))
    linhas = [["ID", "Nome", "Área (ha)", "Prod. (sc/ha)", "Prioridade", "Distância (km)", "Liberado (dia)"]]
    for t in cfg.talhoes:
        linhas.append([t.id, t.nome, num(t.area_ha, 1), num(t.produtividade_sc_ha, 1), str(t.prioridade), num(t.distancia_km, 1),
                       str(t.disponivel_a_partir_dia)])
    s.append(_tabela(linhas, [1.3 * cm, 3.6 * cm, 2 * cm, 2.2 * cm, 2 * cm, 2.4 * cm, W - 13.5 * cm], est))
    s.append(Paragraph("Colheitadeiras", est["h2"]))
    linhas = [["ID", "Cap. nominal (ha/h)", "Eficiência", "Tanque (t)", "Disponib.", "MTTR (h)", "R$/h fixo", "R$/h var.", "L/h"]]
    for c in cfg.colheitadeiras:
        linhas.append([c.id, num(c.capacidade_campo_ha_h, 2), f"{c.eficiencia_campo:.0%}", num(c.capacidade_tanque_t, 1),
                       f"{c.disponibilidade_mecanica:.0%}", num(c.mttr_h, 1), brl(c.custo_fixo_h), brl(c.custo_variavel_h),
                       num(c.consumo_l_h, 0)])
    s.append(_tabela(linhas, [1.2 * cm, 2.4 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 1.5 * cm, 2.1 * cm, 2.1 * cm, W - 14.4 * cm], est))
    s.append(Paragraph("Caminhões", est["h2"]))
    linhas = [["Grupo", "Qtde", "Cap. (t)", "Vel. carreg./vazio", "Manobra", "Disponib.", "R$/h fixo", "R$/km", "km/L"]]
    for g in cfg.frota:
        linhas.append([f"{g.id} — {g.nome}", str(g.quantidade), num(g.capacidade_t, 1),
                       f"{num(g.velocidade_carregado_km_h, 0)}/{num(g.velocidade_vazio_km_h, 0)} km/h",
                       f"{num(g.tempo_manobra_min, 0)} min", f"{g.disponibilidade_mecanica:.0%}", brl(g.custo_fixo_h),
                       brl(g.custo_variavel_km), num(g.consumo_km_l, 1)])
    s.append(_tabela(linhas, [3.6 * cm, 1.1 * cm, 1.4 * cm, 2.6 * cm, 1.5 * cm, 1.6 * cm, 2 * cm, 1.6 * cm, W - 15.4 * cm], est))
    r = cfg.recebimento
    s.append(Paragraph(f"Recebimento: {r.n_moegas} moega(s), {num(r.capacidade_t_h, 0)} t/h no total, tempo fixo de "
                       f"{num(r.tempo_fixo_min, 0)} min por caminhão. Diesel: {brl(cfg.custos.preco_diesel_l)}/L.", est["p"]))

    s.append(Paragraph("9. Método e limitações", est["h1"]))
    for txt in [
        "Simulação de eventos discretos (SimPy). Cada colheitadeira colhe em fatias até encher o tanque, descarrega em um caminhão "
        "posicionado ao seu lado e aguarda se não houver caminhão. Caminhões são despachados para a colheitadeira com menor folga de "
        "cobertura, transportam até a unidade, entram na fila das moegas e retornam.",
        "Produtividade nominal × eficiência de campo define a taxa de colheita; a disponibilidade mecânica não reduz a taxa — ela gera "
        "falhas (tempo médio entre falhas = A·MTTR/(1−A)). Assim nenhum desconto é aplicado duas vezes.",
        "Chuvas bloqueiam a colheita (mais o tempo de secagem informado), mas não o transporte. Falhas informadas de caminhões entram em "
        "vigor ao fim do ciclo em andamento.",
        "Custos de tempo parado (esperas, filas) já estão contidos no custo total pelo custo fixo horário; as consequências financeiras "
        "dos gargalos mostram essa parcela, não um custo adicional.",
        f"Linha do tempo: {formatar_relogio(res.t_inicio)} (início da colheita) a {formatar_relogio(res.t_fim)} (fim da operação).",
    ]:
        s.append(Paragraph("• " + txt, est["p"]))
        s.append(Spacer(1, 2))
    doc.build(s, onFirstPage=_rodape, onLaterPages=_rodape)
    return buf.getvalue()
