# Arquitetura do AgroRitmo

## Visão geral

```
                ┌────────────────────────── ui (Streamlit) ───────────────────────────┐
                │ páginas · simulador visual (HTML/Canvas) · gráficos Plotly · estado  │
                └───────┬─────────────┬──────────────┬──────────────┬─────────────────┘
                        │             │              │              │
   domain ◄─────── simulation ◄── analytics ◄── scenarios ◄── optimization
 (Pydantic)        (SimPy)        (KPIs,        (modificações,   (OR-Tools CP-SAT +
                                  custos,        comparação,       validação por
                                  gargalos)      sensibilidade)    simulação)
                        ▲             ▲
                        │             │
                      data ─────── reports
             (SQLite, importação,  (Excel, CSV, PDF)
               calibração)
```

Dependências apontam sempre para o núcleo (`domain` → nada; `simulation` → `domain`; …). A interface só orquestra.

## Estrutura de diretórios

```
AgroRitmo/
├── app.py                         # streamlit run app.py
├── agroritmo/
│   ├── domain/                    # entidades e regras (Pydantic)
│   │   ├── models.py              # Talhao, Colheitadeira, TipoCaminhao, UnidadeRecebimento, JanelaOperacao, OperationConfig...
│   │   ├── crops.py               # registro configurável de culturas (soja, milho, +novas)
│   │   ├── units.py               # conversões e formatação
│   │   └── defaults.py            # cenários sintéticos de EXEMPLO
│   ├── simulation/
│   │   ├── calendar.py            # janelas: turnos, chuva, manutenção, falhas informadas, horário da unidade
│   │   ├── engine.py              # processos SimPy (colheitadeiras, caminhões, moegas) e despacho
│   │   ├── records.py             # log de eventos, segmentos de estado, cargas
│   │   └── results.py             # SimulationResult (DataFrames)
│   ├── analytics/
│   │   ├── kpis.py                # indicadores com origem, séries temporais, utilização
│   │   ├── costs.py               # custos linha a linha com fórmula
│   │   └── bottlenecks.py         # regras de gargalo + validação por nova simulação
│   ├── scenarios/
│   │   ├── modifications.py       # modificações declarativas e cenários padrão
│   │   ├── compare.py             # execução, replicações (IC 95%), escolha por objetivo
│   │   └── sensitivity.py         # tornado e varredura
│   ├── optimization/
│   │   ├── flow_model.py          # modelo analítico de fluxo
│   │   ├── fleet.py               # CP-SAT: tamanho/composição e distribuição da frota
│   │   ├── sequencing.py          # CP-SAT: sequência de talhões (+ heurística e força bruta)
│   │   └── receiving.py           # bisseção por simulação da capacidade de recebimento
│   ├── data/
│   │   ├── db.py                  # SQLite: operações, execuções, observações, calibrações
│   │   ├── importers.py           # CSV/Excel com validação e modelos para download
│   │   └── calibration.py         # simulado × observado, calibração, origem dos parâmetros
│   ├── reports/                   # Excel, CSV (zip), PDF (reportlab + matplotlib)
│   ├── ui/                        # Streamlit: main, páginas, simulador visual, widgets, gráficos
│   ├── theme.py                   # cores consistentes por estado operacional
│   └── logging_config.py
├── tests/                         # unitários, integração, invariantes, cenários controlados, otimizador × força bruta
├── docs/                          # ARQUITETURA.md, MODELO.md
└── data/agroritmo.db              # criado na primeira execução
```

## Decisões arquiteturais

| Decisão | Motivo |
|---|---|
| **Streamlit** em vez de SPA + API | Entrega uma interface analítica completa só em Python; o único ponto que exige interatividade fina (o player do simulador) é um componente HTML/Canvas que roda no navegador, sem recarregar a página. |
| **Simulador visual alimentado por segmentos de estado** | O motor registra, para cada recurso, intervalos `[início, fim, estado, talhão, origem, destino, carga]`. O player só interpola posições dentro de intervalos de viagem reais — nenhuma movimentação é inventada. |
| **Colheita em fatias com janelas pré-calculadas** | Turnos, chuva e falhas informadas viram listas de intervalos; cada fatia termina no primeiro limite (tanque cheio, fim da janela, próxima falha). Evita interrupções SimPy complexas e torna os resultados verificáveis à mão. |
| **Fluxos aleatórios por recurso** (`SeedSequence(semente, hash(chave))`) | Reprodutibilidade e números aleatórios comuns entre cenários. |
| **SQLite via biblioteca padrão** | Esquema pequeno; dispensa ORM. Caminho configurável por `AGRORITMO_DB` (troca para PostgreSQL concentrada em `data/db.py`). |
| **CP-SAT só onde há modelo exato** | Frota/distribuição/sequência são problemas inteiros pequenos com prova de otimalidade. Fila na recepção não tem modelo exato simples → busca por simulação, rotulada como heurística. |
| **Validação por simulação de tudo que o otimizador recomenda** | O modelo analítico ignora filas e variabilidade; a recomendação final vem do simulador. |
| **reportlab + matplotlib** para PDF | Sem dependência de navegador headless; a fonte DejaVu (incluída no matplotlib) cobre Σ, ×, →, ≤. |

## Fluxo de uma simulação

1. `OperationConfig` validada (Pydantic) → `Simulador` monta calendário e agentes.
2. `env.run(until=horizonte)` → eventos, segmentos, cargas.
3. Pós-processamento reclassifica esperas fora de jornada/horário (ex.: `fila_unidade_fechada`).
4. `analytics` deriva KPIs, custos, séries e gargalos dos registros — nunca de parâmetros diretamente.

## Logs e erros

* `AGRORITMO_LOG_LEVEL` controla o nível; cada simulação registra resumo e tempo de execução.
* Entradas inválidas geram mensagens por campo (Pydantic) na interface; nada é aplicado parcialmente.
* Importações reportam linha, coluna e motivo de cada erro; uma tabela com erro não é importada.

## Evolução prevista

Mapas georreferenciados, transbordo (graneleiro), secador/armazenagem, PostgreSQL multiusuário, API REST para integração com telemetria e uma SPA dedicada podem ser acrescentados sem alterar o núcleo (`domain`/`simulation`/`analytics`).
