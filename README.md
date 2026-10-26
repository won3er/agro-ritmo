# AgroRitmo

**Plataforma de simulação e otimização de operações de colheita e transporte de grãos.**

> Como organizar máquinas, caminhões, horários e capacidade de recebimento para colher e transportar mais grãos, reduzir ociosidade, diminuir custos e evitar gargalos?

O AgroRitmo representa a operação do talhão até a unidade de recebimento, simula minuto a minuto com eventos discretos, mostra a operação em movimento, identifica gargalos com evidências, compara cenários e otimiza recursos com OR-Tools — sempre identificando se cada número é **medido**, **calculado**, **informado** ou **estimado**.

## Instalação

Requisitos: Python 3.10+ (testado em 3.11, Windows).

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

(Linux/macOS: `.venv/bin/python`.)

## Execução

```bash
.venv/Scripts/python -m streamlit run app.py
```

Abra http://localhost:8501 e use **Início → Executar demonstração completa** para ver o fluxo inteiro em um cenário sintético (soja, 1.120 ha, 3 colheitadeiras, 6 caminhões).

## Demonstração online (Vercel)

Vitrine estática pré-calculada: **https://agroritmo-one.vercel.app** (simulador visual, painel, gargalos, cenários, otimização e relatórios).
O Streamlit precisa de um servidor permanente com websocket, que a Vercel não oferece; por isso a versão online não permite editar a operação nem rodar novas simulações.

Para regenerar e publicar:

```bash
.venv/Scripts/python scripts/gerar_vitrine.py
```

```bash
cd vitrine && npx vercel deploy --prod --yes
```

## Vídeo de divulgação

[docs/media/agroritmo.mp4](docs/media/agroritmo.mp4) — 10 s, 1080×1080, capturado do próprio simulador visual. Para regenerar (requer `playwright`, `imageio-ffmpeg` e Chrome instalado):

```bash
.venv/Scripts/python scripts/gerar_video.py
```

## Testes

```bash
.venv/Scripts/python -m pytest
```

88 testes cobrem: conservação de volume, ausência de dupla contabilização, recursos sem tarefas simultâneas, capacidades de carga e recebimento, custos e tempos calculados à mão, situações extremas, consistência eventos × indicadores × relatórios, cenários idênticos, reprodutibilidade por semente e o otimizador comparado com força bruta.

## O que cada tela faz

| Tela | Conteúdo |
|---|---|
| Início e demonstração | Pergunta central, passos, demonstração guiada de ponta a ponta |
| Configurar operação | Talhões, colheitadeiras, grupos de caminhões, recebimento, turnos/janela, custos, clima e eventos, parâmetros da simulação; salvar/carregar (SQLite); importar CSV/Excel/JSON; origem de cada parâmetro |
| Simulação | Simulador visual (iniciar, pausar, ±15 min, velocidade, linha do tempo, saltar para o próximo evento crítico), linha do tempo por recurso, log de eventos filtrável, cargas, talhões, registro da execução e verificação de reprodutibilidade |
| Painel executivo | KPIs com origem, evolução da produção, volumes em processo, filas, chegadas × capacidade, utilização, custos, ciclo do caminhão, gargalos, atual × otimizado |
| Gargalos | Evidência, duração, frequência, recursos, consequência (h, t, R$) com fórmula, recomendação e impacto validado por nova simulação |
| Cenários e sensibilidade | 12 cenários padrão + personalizados, replicações com IC 95%, melhor cenário por objetivo, fronteira tempo × custo, tornado e varredura |
| Otimização | Tamanho/composição da frota, distribuição entre colheitadeiras, sequência de talhões (CP-SAT) e capacidade de recebimento (busca simulada), com método, restrições, status e limitações |
| Dados reais e calibração | Observações, simulado × observado, calibração com nova operação salva, origem dos parâmetros |
| Relatórios e exportação | PDF para gestores, Excel completo, CSV (zip), JSON da configuração, histórico e re-execução com conferência de hash |
| Metodologia | [docs/MODELO.md](docs/MODELO.md) |

## Documentação

* [docs/ARQUITETURA.md](docs/ARQUITETURA.md) — módulos, estrutura de diretórios e decisões arquiteturais
* [docs/MODELO.md](docs/MODELO.md) — modelo de simulação, indicadores, custos, gargalos, otimização, limitações

## Uso como biblioteca

```python
from agroritmo.domain.defaults import exemplo_soja
from agroritmo.simulation import simular
from agroritmo.analytics import calcular_kpis, identificar_gargalos, validar_recomendacoes
from agroritmo.optimization import dimensionar_frota

cfg = exemplo_soja()
res = simular(cfg)
gargalos = validar_recomendacoes(res, identificar_gargalos(res))
frota = dimensionar_frota(cfg)
```

## Aviso

Os cenários de exemplo são **sintéticos e ilustrativos** — não são médias oficiais do setor nem dados de uma fazenda real. Antes de usar os resultados em decisões, importe os dados da sua operação e calibre o modelo com observações reais.
