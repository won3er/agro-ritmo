"""Gera a vitrine estática do AgroRitmo (pasta ``vitrine/``) para publicação em hospedagem estática (Vercel).

Todo o conteúdo vem de simulações reais executadas no momento da geração: simulador visual, painel,
gargalos validados, comparação de cenários, otimização e relatórios para download.

Uso:  python scripts/gerar_vitrine.py
"""
from __future__ import annotations

import html
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import plotly.offline  # noqa: E402

from agroritmo import __version__  # noqa: E402
from agroritmo.analytics import (  # noqa: E402
    calcular_custos,
    calcular_kpis,
    chegadas_por_hora,
    composicao_ciclo,
    identificar_gargalos,
    kpis_dict,
    resumo_custos,
    serie_temporal,
    utilizacao_caminhoes,
    utilizacao_colheitadeiras,
    validar_recomendacoes,
)
from agroritmo.analytics.bottlenecks import AVALIACOES  # noqa: E402
from agroritmo.domain.defaults import exemplo_soja  # noqa: E402
from agroritmo.domain.units import brl, formatar_relogio, num  # noqa: E402
from agroritmo.optimization import buscar_capacidade_recebimento, dimensionar_frota, distribuir_frota_atual, otimizar_sequencia  # noqa: E402
from agroritmo.reports import PacoteRelatorio, exportar_csv_zip, exportar_excel, gerar_pdf  # noqa: E402
from agroritmo.scenarios import OBJETIVOS, cenarios_padrao, comparar  # noqa: E402
from agroritmo.simulation import hash_resultado, simular  # noqa: E402
from agroritmo.theme import CORES_SEVERIDADE, CORES_TIPO_DADO  # noqa: E402
from agroritmo.ui import charts  # noqa: E402
from agroritmo.ui.components.sim_view import html_simulador  # noqa: E402

SAIDA = RAIZ / "vitrine"
PLOTLY = f"https://cdn.jsdelivr.net/npm/plotly.js-dist-min@{plotly.offline.get_plotlyjs_version()}/plotly.min.js"
SEV = {"alta": "ALTA", "media": "MÉDIA", "baixa": "BAIXA"}


def e(s) -> str:
    return html.escape(str(s))


def fig(f, id_: str) -> str:
    f.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return (f'<div class="graf" id="{id_}"></div><script>Plotly.newPlot("{id_}", ...(() => {{ const f = {f.to_json()}; '
            f'return [f.data, f.layout, {{responsive: true, displaylogo: false}}]; }})());</script>')


def kpi(rot, val, uni, tipo, det="") -> str:
    cor = CORES_TIPO_DADO[tipo]
    return (f'<div class="kpi"><span class="badge" style="color:{cor};border-color:{cor}">{tipo.upper()}</span>'
            f'<div class="l">{e(rot)}</div><div class="v">{e(val)}<small>{e(uni)}</small></div><div class="d">{e(det)}</div></div>')


def tabela(df, cols: dict, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    cab = "".join(f"<th>{e(r)}</th>" for r in cols.values())
    linhas = []
    for _, row in df.iterrows():
        cel = []
        for c in cols:
            v = row.get(c)
            if c in fmt and v is not None and v == v:
                v = fmt[c](v)
            cel.append(f"<td>{e('—' if v is None or v != v else v)}</td>")
        linhas.append("<tr>" + "".join(cel) + "</tr>")
    return f'<div class="tw"><table><thead><tr>{cab}</tr></thead><tbody>{"".join(linhas)}</tbody></table></div>'


def main() -> None:
    print("Simulando operação de exemplo...")
    cfg = exemplo_soja()
    res = simular(cfg)
    custos = calcular_custos(res)
    k = kpis_dict(calcular_kpis(res, float(custos["valor"].sum())))
    print("Gargalos e validação...")
    gs = validar_recomendacoes(res, identificar_gargalos(res))
    print("Cenários...")
    comp = comparar(cfg, cenarios_padrao(cfg), 1, "custo_por_t")
    print("Otimização...")
    frota = dimensionar_frota(cfg)
    dist = distribuir_frota_atual(cfg)
    seq = otimizar_sequencia(cfg)
    receb = buscar_capacidade_recebimento(cfg, 10.0)

    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    (SAIDA / "arquivos").mkdir(parents=True)
    print("Relatórios...")
    pacote = PacoteRelatorio.montar(res, gs, comp.tabela, {"justificativa": f"Melhor cenário: {comp.melhor}. {comp.justificativa}",
                                                          "frota_analitico": frota.tabela,
                                                          "frota_simulado": frota.detalhes["simulacao"]})
    (SAIDA / "arquivos" / "relatorio_agroritmo.pdf").write_bytes(gerar_pdf(pacote))
    (SAIDA / "arquivos" / "resultados_agroritmo.xlsx").write_bytes(exportar_excel(pacote))
    (SAIDA / "arquivos" / "resultados_agroritmo_csv.zip").write_bytes(exportar_csv_zip(pacote))
    (SAIDA / "arquivos" / "configuracao_exemplo.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")

    sim = html_simulador(res, 700).replace("background:transparent;", "background:#0E1316;", 1)
    (SAIDA / "simulador.html").write_text(sim, encoding="utf-8")

    serie = serie_temporal(res, 15.0)
    secoes = []
    # ---------------------------------------------------------------- KPIs
    kp = [
        kpi("Toneladas entregues", num(k["t_entregues"], 0), " t", "medido", f"de {num(k['t_previstas'], 0)} t previstas"),
        kpi("Duração da operação", num(k["duracao_h"], 1), " h", "medido", f"{int(k['dias_operacao'])} dias de calendário"),
        kpi("Custo operacional", brl(k["custo_total"]), "", "calculado", "Σ componentes com fórmula"),
        kpi("Custo por tonelada", num(k["custo_por_t"], 2), " R$/t", "calculado", f"{brl(k['custo_por_ha'])}/ha"),
        kpi("Utilização colheitadeiras", num(k["util_colheitadeiras"], 1), " %", "medido", "colhendo ÷ horas de turno"),
        kpi("Utilização caminhões", num(k["util_caminhoes"], 1), " %", "medido", "ciclo produtivo ÷ jornada"),
        kpi("Colheitadeiras sem caminhão", num(k["espera_colh_caminhao_h"], 1), " h", "medido", "soma das máquinas"),
        kpi("Fila de descarga", num(k["fila_descarga_h"], 1), " h", "medido", f"máx. {int(k['fila_max'])} caminhões"),
    ]
    secoes.append(f'<section id="painel"><h2>Painel executivo</h2><div class="kpis">{"".join(kp)}</div>'
                  f'<div class="g2">{fig(charts.producao(serie), "g_prod")}{fig(charts.volumes_em_processo(serie), "g_vol")}</div>'
                  f'<div class="g2">{fig(charts.filas(serie), "g_filas")}{fig(charts.chegadas(chegadas_por_hora(res)), "g_cheg")}</div>'
                  f'<div class="g2">{fig(charts.utilizacao(utilizacao_colheitadeiras(res), "colheitadeira", ["colhendo", "descarregando", "aguardando_caminhao", "deslocando", "manutencao_programada", "falha", "parada_clima", "ocioso"], "Utilização das colheitadeiras (horas por estado)"), "g_uc")}'
                  f'{fig(charts.utilizacao(utilizacao_caminhoes(res), "caminhao", ["em_carregamento", "carregando", "manobra", "transporte_carregado", "descarregando", "retorno_vazio", "aguardando_carregamento", "fila_descarga", "fila_unidade_fechada", "falha"], "Utilização dos caminhões (horas por estado)"), "g_ut")}</div>'
                  f'<div class="g2">{fig(charts.custos(resumo_custos(custos)), "g_custo")}{fig(charts.ciclo(composicao_ciclo(res)), "g_ciclo")}</div>'
                  f'</section>')
    # ---------------------------------------------------------------- gargalos
    itens = []
    for i, g in enumerate(gs, 1):
        val = ""
        if g.impacto:
            a = g.impacto["avaliacao"]
            cls = {"melhora": "ok", "trade_off": "warn", "nao_confirmada": "bad"}[a]
            val = (f'<div class="val {cls}"><b>Validado por nova simulação</b> ({e(g.impacto["descricao"])}, mesma semente): '
                   f'{e(g.impacto["resumo"])} — {e(AVALIACOES[a])}.</div>')
        itens.append(f'<div class="garg"><div><span class="sev" style="background:{CORES_SEVERIDADE[g.severidade]}">{SEV[g.severidade]}</span> '
                     f'<b>{i}. {e(g.titulo)}</b></div><p><b>Evidência:</b> {e(g.evidencia)}</p>'
                     f'<p><b>Consequência:</b> {num(g.consequencia_tempo_h, 1)} h · {num(g.consequencia_volume_t, 1)} t · {e(brl(g.consequencia_rs))}</p>'
                     f'<div class="formula">{e(g.formula_rs)}</div><p><b>Recomendação:</b> {e(g.recomendacao)}</p>{val}</div>')
    secoes.append(f'<section id="gargalos"><h2>Gargalos identificados</h2><p class="sub">Regras automáticas sobre os eventos simulados. '
                  f'O custo de tempo parado já está no custo total — a consequência mostra quanto dele foi improdutivo.</p>{"".join(itens)}</section>')
    # ---------------------------------------------------------------- cenários
    tab = comp.tabela
    secoes.append(
        f'<section id="cenarios"><h2>Comparação de cenários</h2>'
        f'<div class="destaque">Melhor cenário — {e(OBJETIVOS[comp.objetivo])}: <b>{e(comp.melhor)}</b>. {e(comp.justificativa)}</div>'
        f'<div class="g2">{fig(charts.fronteira(tab, comp.melhor), "g_fr")}{fig(charts.comparacao(tab, "custo_por_t", "Custo por tonelada (R$/t)", comp.melhor), "g_ct")}</div>'
        + tabela(tab, {"cenario": "Cenário", "tipo": "Tipo", "duracao_h": "Duração (h)", "t_entregues": "t entregues",
                       "custo_total": "Custo total", "custo_por_t": "R$/t", "espera_colh_caminhao_h": "Colh. aguardando (h)",
                       "fila_descarga_h": "Fila (h)", "util_caminhoes": "Util. caminhões (%)"},
                 {"duracao_h": lambda v: num(v, 1), "t_entregues": lambda v: num(v, 0), "custo_total": brl,
                  "custo_por_t": lambda v: num(v, 2), "espera_colh_caminhao_h": lambda v: num(v, 1),
                  "fila_descarga_h": lambda v: num(v, 1), "util_caminhoes": lambda v: num(v, 1)})
        + '</section>')
    # ---------------------------------------------------------------- otimização
    rf, rd, rs, rr = frota.recomendacao, dist.recomendacao, seq.recomendacao, receb.recomendacao
    sim_f = frota.detalhes["simulacao"]
    secoes.append(
        f'<section id="otimizacao"><h2>Otimização (OR-Tools)</h2><div class="cards4">'
        f'<div class="card"><h3>Tamanho da frota</h3><p class="st">{e(frota.status)}</p><p>Atual: <b>{rf["atual"]}</b> caminhões · '
        f'ótimo analítico: <b>{rf["caminhoes_analitico"]}</b> · melhor simulado: <b>{rf.get("caminhoes_simulado", "—")}</b> '
        f'({e(rf.get("composicao_simulado", ""))}) a {brl(rf.get("custo_por_t_simulado", 0))}/t.</p></div>'
        f'<div class="card"><h3>Distribuição</h3><p class="st">{e(dist.status)}</p><p>'
        + ", ".join(f"{h}: {n}" for h, n in rd["alocacao"].items())
        + f' caminhões — vazão estimada {num(rd["vazao_t_h"], 1)} t/h.</p></div>'
        f'<div class="card"><h3>Sequência de talhões</h3><p class="st">{e(seq.status)}</p><p>Melhoria sobre a regra atual: '
        f'<b>{num(rs["melhoria_pct"] or 0, 1)}%</b>'
        + (" — a regra atual já é ótima nesta instância." if (rs["melhoria_pct"] or 0) < 0.05 else ".") + '</p></div>'
        f'<div class="card"><h3>Recebimento</h3><p class="st">{e(receb.status)}</p><p>Atual {num(rr["capacidade_atual_t_h"], 0)} t/h → '
        f'<b>{num(rr["capacidade_t_h"], 0)} t/h</b> mantém espera média ≤ 10 min ({num(rr["fila_media_min"], 1)} min).</p></div></div>'
        f'{fig(charts.frota(frota.tabela, sim_f), "g_frota")}'
        + tabela(sim_f, {"cenario": "Frota", "composicao": "Composição", "duracao_h": "Duração (h)", "custo_por_t": "R$/t",
                         "espera_colh_caminhao_h": "Colh. aguardando (h)", "fila_descarga_h": "Fila (h)"},
                 {"duracao_h": lambda v: num(v, 1), "custo_por_t": lambda v: num(v, 2),
                  "espera_colh_caminhao_h": lambda v: num(v, 1), "fila_descarga_h": lambda v: num(v, 1)})
        + '<p class="sub">Cada resultado informa método e garantia: CP-SAT dá prova de otimalidade apenas para o modelo analítico '
          '(sem filas nem variabilidade); por isso os candidatos são re-simulados e a recomendação final vem da simulação.</p></section>')

    gerado = datetime.now().strftime("%d/%m/%Y %H:%M")
    pagina = TEMPLATE.format(
        plotly=PLOTLY, versao=__version__, gerado=gerado, hash=hash_resultado(res), semente=cfg.simulacao.semente,
        inicio=formatar_relogio(res.t_inicio), fim=formatar_relogio(res.t_fim), area=num(cfg.area_total_ha, 0),
        secoes="\n".join(secoes))
    (SAIDA / "index.html").write_text(pagina, encoding="utf-8")
    (SAIDA / "vercel.json").write_text(json.dumps({"cleanUrls": True, "headers": [
        {"source": "/arquivos/(.*)", "headers": [{"key": "Content-Disposition", "value": "attachment"}]}]}, indent=2), encoding="utf-8")
    print(f"Vitrine gerada em {SAIDA}")


TEMPLATE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgroRitmo — simulação e otimização de colheita e transporte de grãos</title>
<meta name="description" content="Demonstração do AgroRitmo: simulação de eventos discretos, gargalos, cenários e otimização com OR-Tools para operações de colheita e transporte de grãos.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌾</text></svg>">
<script src="{plotly}"></script>
<style>
:root{{--bg:#0E1316;--panel:#151C21;--borda:#25313A;--txt:#E4EAEF;--suave:#93A1AD;--verde:#2FA866;--ambar:#F0A73A}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);font-family:Inter,"Segoe UI",system-ui,sans-serif;font-size:15px;line-height:1.5}}
header{{border-bottom:1px solid var(--borda);background:#11181c;position:sticky;top:0;z-index:5}}
nav{{max-width:1320px;margin:0 auto;padding:10px 16px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
nav b{{font-size:17px;margin-right:auto}} nav a{{color:var(--suave);text-decoration:none;font-size:14px}} nav a:hover{{color:var(--txt)}}
main{{max-width:1320px;margin:0 auto;padding:0 16px 60px}}
.hero{{padding:38px 0 18px}} .hero h1{{font-size:clamp(26px,4vw,40px);margin:0 0 8px;letter-spacing:-.02em}}
.hero p.q{{font-size:clamp(16px,2vw,20px);color:#c9d5de;margin:0 0 14px;max-width:900px}}
.aviso{{border:1px solid #6b5418;background:rgba(240,167,58,.09);color:#F3D9A4;padding:10px 14px;border-radius:8px;font-size:14px;margin:14px 0}}
.meta{{color:var(--suave);font-size:13px}}
section{{padding-top:34px}} h2{{font-size:22px;margin:0 0 10px;border-bottom:1px solid var(--borda);padding-bottom:8px}}
.sub{{color:var(--suave);font-size:14px}}
iframe{{width:100%;height:730px;border:0;border-radius:10px;background:var(--bg)}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}}
.kpi{{background:var(--panel);border:1px solid var(--borda);border-radius:8px;padding:10px 12px;position:relative}}
.kpi .l{{color:var(--suave);font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding-right:76px}}
.kpi .v{{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}} .kpi small{{font-size:13px;color:var(--suave);font-weight:400}}
.kpi .d{{font-size:12px;color:var(--suave)}}
.badge{{position:absolute;top:9px;right:10px;font-size:10px;font-weight:700;border:1px solid;border-radius:3px;padding:0 5px;letter-spacing:.05em}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} .graf{{background:var(--panel);border:1px solid var(--borda);border-radius:8px;min-height:320px;margin:6px 0}}
.garg{{background:var(--panel);border:1px solid var(--borda);border-radius:8px;padding:12px 14px;margin:10px 0}} .garg p{{margin:6px 0}}
.sev{{color:#0E1316;font-weight:800;font-size:11px;border-radius:10px;padding:2px 8px;margin-right:4px}}
.formula{{font-family:Consolas,ui-monospace,monospace;font-size:13px;color:#BFD3DF;background:#10171c;border:1px solid var(--borda);border-radius:5px;padding:6px 9px}}
.val{{border-radius:6px;padding:7px 10px;font-size:14px;margin-top:6px}} .ok{{background:rgba(47,168,102,.12);border:1px solid #1f6b43}}
.warn{{background:rgba(240,167,58,.1);border:1px solid #6b5418}} .bad{{background:rgba(224,82,77,.1);border:1px solid #6b2522}}
.destaque{{background:rgba(47,168,102,.1);border:1px solid #1f6b43;border-radius:8px;padding:10px 14px;margin:8px 0}}
.tw{{overflow-x:auto;margin:10px 0}} table{{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 9px;border-bottom:1px solid var(--borda);text-align:left;white-space:nowrap}} th{{color:var(--suave);font-weight:600;background:#121a1f}}
.cards4{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0}}
.card{{background:var(--panel);border:1px solid var(--borda);border-radius:8px;padding:12px 14px}} .card h3{{margin:0 0 4px;font-size:16px}}
.card .st{{color:var(--verde);font-size:12px;margin:0 0 6px}} .card p{{margin:4px 0;font-size:14px}}
.dl{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}} .dl a{{background:var(--panel);border:1px solid var(--borda);color:var(--txt);text-decoration:none;padding:10px 14px;border-radius:8px}}
.dl a.p{{background:var(--verde);border-color:var(--verde);color:#06130b;font-weight:700}}
code{{background:#10171c;border:1px solid var(--borda);border-radius:4px;padding:1px 5px}}
footer{{color:var(--suave);font-size:13px;border-top:1px solid var(--borda);margin-top:40px;padding-top:14px}}
@media (max-width:900px){{.kpis,.cards4{{grid-template-columns:1fr 1fr}} .g2{{grid-template-columns:1fr}} iframe{{height:760px}}}}
@media (max-width:520px){{.kpis,.cards4{{grid-template-columns:1fr}}}}
</style></head>
<body>
<header><nav><b>🌾 AgroRitmo</b><a href="#simulador">Simulador</a><a href="#painel">Painel</a><a href="#gargalos">Gargalos</a>
<a href="#cenarios">Cenários</a><a href="#otimizacao">Otimização</a><a href="#relatorios">Relatórios</a></nav></header>
<main>
<div class="hero"><h1>Inteligência operacional para colheita e transporte de grãos</h1>
<p class="q">Como organizar máquinas, caminhões, horários e recebimento para colher e transportar mais grãos, com menos ociosidade, menor custo e sem gargalos?</p>
<p>O AgroRitmo simula a operação do talhão à unidade de recebimento com eventos discretos (SimPy), identifica gargalos com evidências,
compara cenários e otimiza recursos com OR-Tools. Esta página é uma <b>demonstração pré-calculada</b>: todos os números abaixo vêm de
simulações reais do motor, executadas na geração da página.</p>
<div class="aviso">⚠ <b>Cenário sintético de exemplo</b> — soja, {area} ha, 6 talhões, 3 colheitadeiras, 6 caminhões. Os parâmetros são ilustrativos:
não são médias oficiais do setor nem dados de uma fazenda real. Para editar a operação e rodar novas simulações, use o aplicativo completo (instruções no fim da página).</div>
<p class="meta">Semente {semente} · hash do resultado <code>{hash}</code> · colheita de {inicio} a {fim} · AgroRitmo {versao} · gerado em {gerado}</p></div>

<section id="simulador"><h2>Simulador visual</h2>
<p class="sub">Reprodução dos estados registrados pelo simulador — cada posição e cor vem de um intervalo de estado real. Use ▶ Iniciar, velocidade,
±15 min, a linha do tempo ou "Ir ⏭" para saltar ao próximo evento crítico. Passe o mouse sobre máquinas e talhões.</p>
<iframe src="simulador.html" title="Simulador visual AgroRitmo" loading="lazy"></iframe></section>
{secoes}
<section id="relatorios"><h2>Relatórios e dados</h2>
<p class="sub">Gerados a partir da mesma simulação (mesma semente e hash).</p>
<div class="dl"><a class="p" href="arquivos/relatorio_agroritmo.pdf">📄 Relatório PDF para gestores</a>
<a href="arquivos/resultados_agroritmo.xlsx">📊 Excel completo</a><a href="arquivos/resultados_agroritmo_csv.zip">🗂 CSV (zip)</a>
<a href="arquivos/configuracao_exemplo.json">⚙ Configuração (JSON)</a></div></section>

<section><h2>Aplicativo completo</h2>
<p>A versão interativa (configurar a operação, importar dados, rodar simulações, cenários, otimização e calibração) é um app Streamlit
que precisa de um servidor Python permanente:</p>
<p><code>pip install -r requirements.txt</code> &nbsp; <code>streamlit run app.py</code></p></section>
<footer>Legenda de origem: <b>MEDIDO</b> nos eventos da simulação · <b>CALCULADO</b> por fórmula · <b>INFORMADO</b> pelo usuário ·
<b>ESTIMADO</b> por modelo aproximado. Sem calibração com observações reais, os resultados não representam uma fazenda específica.</footer>
</main></body></html>
"""

if __name__ == "__main__":
    main()
