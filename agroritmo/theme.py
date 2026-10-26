"""Paleta visual compartilhada pela interface e pelos relatórios (cores consistentes por estado)."""
from __future__ import annotations

CORES_ESTADO = {
    # colheitadeiras
    "colhendo": "#2FA866",
    "descarregando": "#38B6C4",
    "aguardando_caminhao": "#F0A73A",
    "deslocando": "#7B93C4",
    "manutencao_programada": "#9273C9",
    "falha": "#D04BC4",
    "parada_clima": "#6F8396",
    "fora_turno": "#5A636E",
    "ocioso": "#A9B2BC",
    "concluida": "#C9D2DA",
    # caminhões
    "aguardando_carregamento": "#E8C547",
    "em_carregamento": "#7FCB8F",
    "manobra": "#9DB4DE",
    "carregando": "#38B6C4",
    "transporte_carregado": "#3D7BE0",
    "fila_descarga": "#E0524D",
    "fila_unidade_fechada": "#9C3532",
    "retorno_vazio": "#7B93C4",
    "fora_jornada": "#5A636E",
    "concluido": "#C9D2DA",
}

MARCA = {
    "fundo": "#0E1316",
    "painel": "#151C21",
    "borda": "#25313A",
    "texto": "#E4EAEF",
    "texto_suave": "#93A1AD",
    "verde": "#2FA866",
    "ambar": "#F0A73A",
    "vermelho": "#E0524D",
    "azul": "#3D7BE0",
    "ciano": "#38B6C4",
}

CORES_SEVERIDADE = {"alta": "#E0524D", "media": "#F0A73A", "baixa": "#7B93C4"}
CORES_TIPO_DADO = {"medido": "#2FA866", "calculado": "#38B6C4", "informado": "#A9B2BC", "estimado": "#F0A73A"}
ROTULO_TIPO_DADO = {"medido": "MEDIDO", "calculado": "CALCULADO", "informado": "INFORMADO", "estimado": "ESTIMADO"}
SEQ_CENARIOS = ["#2FA866", "#3D7BE0", "#F0A73A", "#38B6C4", "#9273C9", "#E0524D", "#7B93C4", "#C9A227", "#D04BC4",
                "#6F8396", "#7FCB8F", "#9C3532"]
