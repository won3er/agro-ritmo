"""Configuração da operação: criar, editar, validar, salvar, carregar e importar."""
from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ...data.calibration import tabela_parametros
from ...data.importers import dicionario_df, importar_arquivo, importar_operacao_excel, modelo_csv, modelo_excel
from ...domain.crops import culturas_disponiveis
from ...domain.defaults import EXEMPLOS
from ...domain.models import OperationConfig, OrigemDado
from ...domain.units import num
from .. import state
from ..widgets import banner_origem, cabecalho

NC = st.column_config.NumberColumn
TC = st.column_config.TextColumn


def _versao() -> int:
    return st.session_state.setdefault("form_ver", 0)


def _nova_versao() -> None:
    st.session_state.form_ver = _versao() + 1


def _registros(df: pd.DataFrame, obrigatorio: str = "id") -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        if obrigatorio and (r.get(obrigatorio) is None or (isinstance(r.get(obrigatorio), float) and math.isnan(r[obrigatorio]))
                            or str(r.get(obrigatorio)).strip() == ""):
            continue
        limpo = {}
        for k, v in r.items():
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            if isinstance(v, float) and k in ("prioridade", "quantidade", "disponivel_a_partir_dia", "dia"):
                v = int(round(v))
            limpo[k] = v
        out.append(limpo)
    return out


def _erros_amigaveis(e: ValidationError) -> list[str]:
    msgs = []
    for err in e.errors():
        loc = " → ".join(str(x) for x in err["loc"])
        msgs.append(f"**{loc or 'operação'}**: {err['msg']}")
    return msgs


def _carregar(cfg: OperationConfig, cfg_id=None) -> None:
    state.definir_cfg(cfg, cfg_id)
    _nova_versao()


def render() -> None:
    cfg = state.cfg()
    repo = state.repositorio()
    cabecalho("Configurar operação", "Crie, edite, valide e salve a operação. Unidades explícitas em cada campo.")
    banner_origem(cfg)

    c1, c2, c3 = st.columns([1.4, 1.2, 1])
    with c1:
        salvas = repo.listar_operacoes()
        opcoes = ["—"] + [f"{r.id} · {r.nome}" for r in salvas.itertuples()]
        sel = st.selectbox("Operações salvas no banco", opcoes, key=f"sel_salva_{_versao()}")
        b1, b2 = st.columns(2)
        if b1.button("Carregar", disabled=sel == "—", use_container_width=True):
            oid = int(sel.split(" · ")[0])
            _carregar(repo.carregar_operacao(oid), oid)
            st.rerun()
        if b2.button("Excluir", disabled=sel == "—", use_container_width=True):
            repo.excluir_operacao(int(sel.split(" · ")[0]))
            st.toast("Operação excluída.")
            st.rerun()
    with c2:
        ex = st.selectbox("Cenários de exemplo (sintéticos)", list(EXEMPLOS))
        if st.button("Carregar exemplo", use_container_width=True):
            _carregar(EXEMPLOS[ex]())
            st.rerun()
    with c3:
        st.write("")
        st.write("")
        if st.button("💾 Salvar operação atual", type="primary", use_container_width=True):
            oid = repo.salvar_operacao(cfg)
            st.session_state.cfg_id = oid
            st.toast(f"Operação '{cfg.nome}' salva (id {oid}).", icon="💾")
        st.download_button("⬇ Configuração (JSON)", cfg.model_dump_json(indent=2).encode("utf-8"),
                           file_name=f"operacao_{cfg.nome[:40]}.json".replace(" ", "_"), mime="application/json",
                           use_container_width=True)

    v = _versao()
    with st.form(f"form_operacao_{v}"):
        tabs = st.tabs(["Geral", "Talhões", "Colheitadeiras", "Caminhões", "Recebimento e janelas", "Custos",
                        "Clima e eventos", "Simulação"])
        with tabs[0]:
            g1, g2 = st.columns([2, 1])
            nome = g1.text_input("Nome da operação", cfg.nome, max_chars=120)
            culturas = culturas_disponiveis()
            cultura = g2.selectbox("Cultura", culturas, index=culturas.index(cfg.cultura) if cfg.cultura in culturas else 0)
            descricao = st.text_area("Descrição / notas", cfg.descricao, height=80)
            origens = [o.value for o in OrigemDado]
            origem = st.selectbox("Origem principal dos dados", origens, index=origens.index(cfg.origem_dados.value),
                                  help="Exemplo sintético, informado pelo usuário, importado ou calibrado. Parâmetros alterados "
                                       "manualmente passam a ser marcados como 'usuario'.")
            st.caption(f"Massa da saca considerada: {num(cfg.kg_por_saca, 0)} kg · Área total atual: {num(cfg.area_total_ha, 1)} ha · "
                       f"Produção prevista: {num(cfg.producao_prevista_t, 1)} t")
        with tabs[1]:
            st.caption("Uma linha por talhão. Posição X/Y (km) é esquemática e usada no deslocamento entre talhões e no mapa.")
            df_t = pd.DataFrame([t.model_dump() for t in cfg.talhoes])
            ed_t = st.data_editor(df_t, num_rows="dynamic", use_container_width=True, key=f"ed_t_{v}", column_config={
                "id": TC("ID", required=True), "nome": TC("Nome"),
                "area_ha": NC("Área (ha)", min_value=0.01, format="%.1f", required=True),
                "produtividade_sc_ha": NC("Produtividade (sc/ha)", min_value=1.0, format="%.1f", required=True),
                "prioridade": NC("Prioridade (1=alta)", min_value=1, max_value=5, step=1),
                "distancia_km": NC("Distância à unidade (km)", min_value=0.1, format="%.1f", required=True),
                "x_km": NC("X (km)", format="%.1f"), "y_km": NC("Y (km)", format="%.1f"),
                "disponivel_a_partir_dia": NC("Liberado a partir do dia", min_value=1, step=1)})
        with tabs[2]:
            st.caption("Produtividade nominal (ha/h) e eficiência de campo são separadas; a disponibilidade mecânica gera falhas "
                       "na simulação e NÃO reduz a taxa (evita descontar duas vezes).")
            df_c = pd.DataFrame([c.model_dump() for c in cfg.colheitadeiras])
            ed_c = st.data_editor(df_c, num_rows="dynamic", use_container_width=True, key=f"ed_c_{v}", column_config={
                "id": TC("ID", required=True), "nome": TC("Nome"), "modelo": TC("Modelo"),
                "capacidade_campo_ha_h": NC("Cap. nominal (ha/h)", min_value=0.1, format="%.2f", required=True),
                "eficiencia_campo": NC("Eficiência de campo (0–1)", min_value=0.05, max_value=1.0, format="%.2f"),
                "capacidade_tanque_t": NC("Tanque (t)", min_value=0.5, format="%.1f", required=True),
                "tempo_descarga_tanque_min": NC("Descarga do tanque (min)", min_value=0.1, format="%.1f"),
                "velocidade_deslocamento_km_h": NC("Vel. deslocamento (km/h)", min_value=1.0, format="%.0f"),
                "disponibilidade_mecanica": NC("Disponibilidade (0–1)", min_value=0.3, max_value=1.0, format="%.2f"),
                "mttr_h": NC("MTTR (h)", min_value=0.1, format="%.1f"),
                "parada_programada_min_dia": NC("Manutenção diária (min)", min_value=0.0, format="%.0f"),
                "custo_fixo_h": NC("Custo fixo (R$/h)", min_value=0.0, format="%.2f"),
                "custo_variavel_h": NC("Custo variável (R$/h)", min_value=0.0, format="%.2f"),
                "consumo_l_h": NC("Consumo (L/h)", min_value=0.0, format="%.1f")})
        with tabs[3]:
            st.caption("Cada linha é um grupo de caminhões iguais; os caminhões recebem IDs GRUPO-01, GRUPO-02...")
            df_f = pd.DataFrame([g.model_dump() for g in cfg.frota])
            ed_f = st.data_editor(df_f, num_rows="dynamic", use_container_width=True, key=f"ed_f_{v}", column_config={
                "id": TC("Prefixo", required=True), "nome": TC("Descrição"),
                "quantidade": NC("Quantidade", min_value=0, step=1, required=True),
                "capacidade_t": NC("Capacidade (t)", min_value=1.0, format="%.1f", required=True),
                "velocidade_carregado_km_h": NC("Vel. carregado (km/h)", min_value=1.0, format="%.0f"),
                "velocidade_vazio_km_h": NC("Vel. vazio (km/h)", min_value=1.0, format="%.0f"),
                "tempo_manobra_min": NC("Manobra (min)", min_value=0.0, format="%.1f"),
                "disponibilidade_mecanica": NC("Disponibilidade (0–1)", min_value=0.3, max_value=1.0, format="%.2f"),
                "mttr_h": NC("MTTR (h)", min_value=0.1, format="%.1f"),
                "custo_fixo_h": NC("Custo fixo (R$/h)", min_value=0.0, format="%.2f"),
                "custo_variavel_km": NC("Custo variável (R$/km)", min_value=0.0, format="%.2f"),
                "consumo_km_l": NC("Rendimento (km/L)", min_value=0.1, format="%.2f")})
        with tabs[4]:
            r = cfg.recebimento
            j = cfg.janela
            a1, a2, a3 = st.columns(3)
            with a1:
                st.markdown("**Unidade de recebimento**")
                r_nome = st.text_input("Nome da unidade", r.nome)
                r_moegas = st.number_input("Moegas (descargas simultâneas)", 1, 20, r.n_moegas)
                r_cap = st.number_input("Capacidade total de recebimento (t/h)", 1.0, 5000.0, float(r.capacidade_t_h), step=5.0)
                r_fixo = st.number_input("Tempo fixo por caminhão (min) — pesagem/amostragem", 0.0, 120.0, float(r.tempo_fixo_min))
                st.caption(f"Descarga de uma carga de 30 t ≈ {num(r_fixo + 30 / (r_cap / r_moegas) * 60, 1)} min (calculado)")
            with a2:
                st.markdown("**Horários**")
                r_ab = st.number_input("Abertura da unidade (h)", 0.0, 24.0, float(r.hora_abertura), step=0.5)
                r_fe = st.number_input("Fechamento da unidade (h)", 0.0, 24.0, float(r.hora_fechamento), step=0.5)
                j_ci = st.number_input("Início do turno de colheita (h)", 0.0, 24.0, float(j.colheita_inicio_h), step=0.5)
                j_cf = st.number_input("Fim do turno de colheita (h)", 0.0, 24.0, float(j.colheita_fim_h), step=0.5)
                j_ti = st.number_input("Início da jornada dos caminhões (h)", 0.0, 24.0, float(j.caminhoes_inicio_h), step=0.5)
                j_tf = st.number_input("Fim da jornada dos caminhões (h)", 0.0, 24.0, float(j.caminhoes_fim_h), step=0.5)
            with a3:
                st.markdown("**Janela da operação**")
                j_hor = st.number_input("Janela disponível (dias)", 1, 180, int(j.horizonte_dias))
                j_alvo = st.number_input("Prazo desejado (dias; 0 = sem prazo)", 0.0, 180.0, float(j.data_alvo_dias or 0), step=1.0)
                r_custo = st.number_input("Custo de recepção (R$/t)", 0.0, 1000.0, float(r.custo_recebimento_t), step=0.5)
        with tabs[5]:
            k1, k2 = st.columns(2)
            diesel = k1.number_input("Preço do combustível (R$/L)", 0.0, 50.0, float(cfg.custos.preco_diesel_l), step=0.05)
            saca = k2.number_input("Preço de referência da saca (R$/sc) — só para valorar volume em risco", 0.0, 1000.0,
                                   float(cfg.custos.valor_saca), step=1.0)
            st.caption("Outros custos: por dia de operação, por tonelada entregue ou valor fixo.")
            df_o = pd.DataFrame([o.model_dump() for o in cfg.custos.outros_custos], columns=["nome", "tipo", "valor"])
            ed_o = st.data_editor(df_o, num_rows="dynamic", use_container_width=True, key=f"ed_o_{v}", column_config={
                "nome": TC("Descrição", required=True),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["por_dia", "por_tonelada", "fixo"], required=True),
                "valor": NC("Valor (R$)", min_value=0.0, format="%.2f", required=True)})
        with tabs[6]:
            cl = cfg.clima
            k1, k2, k3 = st.columns(3)
            prob = k1.number_input("Probabilidade diária de chuva aleatória (0–1)", 0.0, 1.0, float(cl.prob_chuva_dia), step=0.05)
            dur = k2.number_input("Duração média da chuva aleatória (h)", 0.1, 48.0, float(cl.duracao_media_chuva_h))
            seca = k3.number_input("Espera para secagem após chuva (h)", 0.0, 48.0, float(cl.espera_pos_chuva_h))
            st.markdown("**Chuvas previstas** (bloqueiam a colheita; o transporte continua)")
            df_ch = pd.DataFrame([e.model_dump() for e in cl.eventos_chuva], columns=["dia", "hora_inicio", "duracao_h"])
            ed_ch = st.data_editor(df_ch, num_rows="dynamic", use_container_width=True, key=f"ed_ch_{v}", column_config={
                "dia": NC("Dia", min_value=1, step=1, required=True), "hora_inicio": NC("Hora de início", min_value=0.0, max_value=23.99),
                "duracao_h": NC("Duração (h)", min_value=0.1)})
            st.markdown("**Eventos operacionais** — falhas informadas, interrupções da unidade e mudanças de capacidade")
            ids = [c.id for c in cfg.colheitadeiras] + [cid for cid, _ in cfg.caminhoes_expandidos()]
            df_ev = pd.DataFrame([e.model_dump() for e in cfg.eventos], columns=["tipo", "dia", "hora", "duracao_h", "recurso_id", "valor"])
            ed_ev = st.data_editor(df_ev, num_rows="dynamic", use_container_width=True, key=f"ed_ev_{v}", column_config={
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["falha_forcada", "interrupcao_recebimento", "capacidade_recebimento"],
                                                         required=True),
                "dia": NC("Dia", min_value=1, step=1, required=True), "hora": NC("Hora", min_value=0.0, max_value=23.99),
                "duracao_h": NC("Duração (h)", min_value=0.0), "recurso_id": st.column_config.SelectboxColumn("Recurso (falha)", options=ids),
                "valor": NC("Fator de capacidade", min_value=0.01, help="Para capacidade_recebimento: ex. 0,5 = metade")})
        with tabs[7]:
            s = cfg.simulacao
            k1, k2, k3 = st.columns(3)
            semente = k1.number_input("Semente aleatória", 0, 10**9, int(s.semente))
            cv = k2.number_input("Variabilidade dos tempos (CV, 0 = determinístico)", 0.0, 0.6, float(s.variabilidade_cv), step=0.05)
            falhas = k3.checkbox("Gerar falhas a partir da disponibilidade", s.falhas_aleatorias)
            k4, k5, k6 = st.columns(3)
            modo = k4.selectbox("Despacho de caminhões", ["pool", "dedicada"], index=["pool", "dedicada"].index(s.modo_alocacao),
                                help="pool = despacho dinâmico para a colheitadeira com menor folga; dedicada = caminhões fixos por máquina")
            regras = ["prioridade", "proximidade", "plano"]
            regra = k5.selectbox("Sequência de talhões", regras, index=regras.index(s.regra_sequencia))
            ajuda = k6.checkbox("Colheitadeira livre ajuda em talhão em andamento", s.ajuda_entre_colheitadeiras)
            esvaziar = st.checkbox("Esvaziar tanque ao fim do turno", s.descarregar_fim_turno)
            st.caption(f"Alocação dedicada atual: {s.alocacao or '—'} · Mapa explícito: {len(s.alocacao_caminhoes)} caminhão(ões) · "
                       f"Plano de sequência: {s.plano_sequencia or '—'} (definidos pela página de Otimização)")
        aplicar = st.form_submit_button("✔ Validar e aplicar alterações", type="primary")

    if aplicar:
        d = cfg.model_dump()
        d.update({"nome": nome, "cultura": cultura, "descricao": descricao, "origem_dados": origem})
        d["talhoes"] = _registros(ed_t)
        d["colheitadeiras"] = _registros(ed_c)
        d["frota"] = _registros(ed_f)
        d["recebimento"].update({"nome": r_nome, "n_moegas": int(r_moegas), "capacidade_t_h": r_cap, "tempo_fixo_min": r_fixo,
                                 "hora_abertura": r_ab, "hora_fechamento": r_fe, "custo_recebimento_t": r_custo})
        d["janela"].update({"colheita_inicio_h": j_ci, "colheita_fim_h": j_cf, "caminhoes_inicio_h": j_ti, "caminhoes_fim_h": j_tf,
                            "horizonte_dias": int(j_hor), "data_alvo_dias": j_alvo or None})
        d["custos"].update({"preco_diesel_l": diesel, "valor_saca": saca, "outros_custos": _registros(ed_o, "nome")})
        d["clima"].update({"prob_chuva_dia": prob, "duracao_media_chuva_h": dur, "espera_pos_chuva_h": seca,
                           "eventos_chuva": _registros(ed_ch, "dia")})
        d["eventos"] = _registros(ed_ev, "tipo")
        d["simulacao"].update({"semente": int(semente), "variabilidade_cv": cv, "falhas_aleatorias": falhas, "modo_alocacao": modo,
                               "regra_sequencia": regra, "ajuda_entre_colheitadeiras": ajuda, "descarregar_fim_turno": esvaziar})
        if modo == "pool":
            d["simulacao"]["alocacao"], d["simulacao"]["alocacao_caminhoes"] = {}, {}
        try:
            novo = OperationConfig.model_validate(d)
        except ValidationError as e:
            st.error("A configuração tem inconsistências — nada foi aplicado:")
            for m in _erros_amigaveis(e):
                st.markdown(f"- {m}")
        else:
            state.definir_cfg(novo)
            _nova_versao()
            st.session_state.flash = "Configuração validada e aplicada. Execute a simulação para ver os efeitos."
            st.rerun()

    alertas = cfg.alertas()
    if alertas:
        with st.expander(f"⚠ {len(alertas)} alerta(s) de plausibilidade", expanded=False):
            for a in alertas:
                st.markdown(f"- {a}")

    with st.expander("Parâmetros e origem dos dados (padrão de exemplo × usuário × importado × calibrado)"):
        tp = tabela_parametros(cfg)
        filtro = st.multiselect("Filtrar por origem", sorted(tp["origem"].unique()), default=sorted(tp["origem"].unique()))
        st.dataframe(tp[tp["origem"].isin(filtro)], use_container_width=True, hide_index=True, height=320)

    with st.expander("Importar dados próprios (CSV ou Excel)"):
        st.markdown("Baixe os modelos, preencha com seus dados e importe. Colunas, unidades, campos obrigatórios e "
                    "inconsistências são validados antes de qualquer alteração.")
        m1, m2, m3, m4 = st.columns(4)
        m1.download_button("Modelo Excel completo", modelo_excel(), "agroritmo_modelo.xlsx", use_container_width=True)
        m2.download_button("talhoes.csv", modelo_csv("talhoes"), "talhoes.csv", use_container_width=True)
        m3.download_button("colheitadeiras.csv", modelo_csv("colheitadeiras"), "colheitadeiras.csv", use_container_width=True)
        m4.download_button("caminhoes.csv", modelo_csv("caminhoes"), "caminhoes.csv", use_container_width=True)
        tabela = st.radio("O que importar", ["Workbook Excel (talhões + colheitadeiras + caminhões)", "talhoes", "colheitadeiras",
                                             "caminhoes", "Configuração JSON"], horizontal=True)
        arq = st.file_uploader("Arquivo", type=["csv", "xlsx", "json"], key=f"up_{v}")
        if tabela in ("talhoes", "colheitadeiras", "caminhoes"):
            with st.popover("Dicionário de colunas"):
                st.dataframe(dicionario_df(tabela), hide_index=True, use_container_width=True)
        if arq is not None and st.button("Validar e importar", type="primary"):
            _importar(arq, tabela, cfg)


def _importar(arq: Any, tabela: str, cfg: OperationConfig) -> None:
    if tabela == "Configuração JSON":
        try:
            novo = OperationConfig.model_validate(json.loads(arq.getvalue().decode("utf-8")))
        except (ValidationError, ValueError) as e:
            st.error(f"JSON inválido: {e}")
            return
        _carregar(novo)
        st.success(f"Operação '{novo.nome}' importada.")
        st.rerun()
    if tabela.startswith("Workbook"):
        novo, rels = importar_operacao_excel(arq, cfg)
        for r in rels:
            _mostrar_relatorio(r)
        if novo is not None:
            _carregar(novo)
            st.success("Workbook importado e validado. Talhões, colheitadeiras e caminhões substituídos.")
        return
    rel = importar_arquivo(arq.getvalue(), arq.name, tabela)
    _mostrar_relatorio(rel)
    if not rel.ok:
        return
    d = cfg.model_dump()
    campo = {"talhoes": "talhoes", "colheitadeiras": "colheitadeiras", "caminhoes": "frota"}[tabela]
    d[campo] = _registros(rel.dados)
    d["origem_dados"] = OrigemDado.IMPORTADO.value
    d["simulacao"].update({"plano_sequencia": {}, "alocacao": {}, "alocacao_caminhoes": {}, "modo_alocacao": "pool"})
    d["eventos"] = [e for e in d["eventos"] if e["tipo"] != "falha_forcada"]
    try:
        _carregar(OperationConfig.model_validate(d))
        st.success(f"{len(rel.dados)} linha(s) importada(s) em {tabela}.")
    except ValidationError as e:
        st.error("Os dados importados são válidos isoladamente, mas inconsistentes com o restante da operação:")
        for m in _erros_amigaveis(e):
            st.markdown(f"- {m}")


def _mostrar_relatorio(rel) -> None:
    if rel.ok:
        st.success(f"{rel.tabela}: {rel.linhas_lidas} linha(s) lida(s), sem erros.")
    else:
        st.error(f"{rel.tabela}: {len(rel.erros)} erro(s) — nada foi importado desta tabela.")
    if rel.erros or rel.avisos:
        st.dataframe(rel.resumo(), hide_index=True, use_container_width=True)
