## O que o AgroRitmo representa

A operação é modelada do talhão até a unidade de recebimento:

```
talhão ──► colheitadeira (tanque) ──► caminhão no campo ──► transporte carregado ──► fila nas moegas ──► descarga ──► retorno vazio
```

O tempo do simulador é contado em **minutos desde 00:00 do Dia 1**. Massa em **t**, área em **ha**, distância em **km**, valores em **R$**.

## Motor de simulação (eventos discretos — SimPy)

Cada colheitadeira e cada caminhão é um processo sequencial; as moegas são um recurso com capacidade igual ao número de moegas.

**Colheitadeira**
1. Escolhe o próximo talhão pela regra configurada (*prioridade*, *proximidade* ou *plano* vindo do otimizador). Talhões ainda não liberados (dia de disponibilidade) são aguardados. Com "ajuda" habilitada, uma máquina sem talhões pendentes divide a área restante de um talhão em andamento.
2. Colhe em **fatias** até encher o tanque: `taxa = capacidade nominal (ha/h) × eficiência de campo`. Cada fatia respeita a janela de trabalho (turno, manutenção diária no início do turno, chuva + secagem, falhas informadas) e o tempo até a próxima falha aleatória.
3. Com o tanque cheio, descarrega no caminhão posicionado ao seu lado (tempo proporcional à quantidade). **Sem caminhão, a máquina para e aguarda** — essa espera é registrada.
4. No fim do turno esvazia o tanque (configurável); caminhões parcialmente carregados seguem para a unidade.

**Caminhão**
1. Só inicia ciclos dentro da sua jornada.
2. É despachado para a colheitadeira com **menor folga**: (espaço no tanque + espaço nos caminhões junto a ela + capacidade dos que já estão a caminho) ÷ taxa de colheita − tempo de viagem até ela. No modo *dedicado*, atende sempre a mesma máquina.
3. Viaja vazio, manobra, aguarda/enche junto à colheitadeira, parte quando cheio, entra na fila FIFO das moegas, descarrega (`tempo fixo + carga ÷ taxa por moega`) somente com a unidade aberta e retorna.

**Paradas e mudanças de condição**: manutenção programada diária; falhas aleatórias; falhas informadas (colheitadeira: imediatas; caminhão: no fim do ciclo em andamento); chuva informada ou aleatória (bloqueia colheita, não o transporte); interrupção da unidade; mudança temporária da capacidade de recebimento.

### Produtividade nominal, eficiência e disponibilidade — sem desconto duplo

| Conceito | Onde entra | Onde **não** entra |
|---|---|---|
| Capacidade nominal (ha/h) | Taxa de colheita | — |
| Eficiência de campo (0–1) | Multiplica a taxa (manobras, sobreposição) | Tempo de falhas/esperas |
| Disponibilidade mecânica (0–1) | Vira **MTBF = A·MTTR/(1−A)**; falhas são eventos | Taxa de colheita |
| Esperas, clima, turnos | Emergem da simulação | Taxa de colheita |

### Garantias verificadas pelos testes
* Conservação: colhido = entregue + em tanques + em caminhões, a qualquer momento.
* Cada carga tem ID único e é contabilizada como entregue uma só vez; descarregado ≤ transportado ≤ capacidade.
* Nenhum recurso tem estados sobrepostos; um caminhão não faz duas viagens ao mesmo tempo.
* Descargas simultâneas ≤ número de moegas; nenhuma descarga começa com a unidade fechada.
* Colheita somente dentro das janelas; mesma configuração + mesma semente ⇒ resultado idêntico (hash).

## Indicadores e origem dos números

| Etiqueta | Significado |
|---|---|
| **MEDIDO** | Observado diretamente nos eventos/estados da simulação |
| **CALCULADO** | Fórmula sobre valores medidos e informados (ex.: custos) |
| **INFORMADO** | Parâmetro de entrada (usuário, exemplo, importado ou calibrado) |
| **ESTIMADO** | Projeção aproximada (ex.: modelo analítico do otimizador) |

Definições principais:
* **Utilização das colheitadeiras** = horas colhendo ÷ horas de turno mobilizadas (dias de operação).
* **Utilização dos caminhões** = horas em manobra, enchendo junto à máquina, carregando, transporte, descarga e retorno ÷ horas de jornada mobilizadas.
* **Ocupação das moegas** = horas de descarga ÷ (moegas × horas abertas).
* **Volume aguardando transporte** = t em tanques + t em caminhões ainda no campo.

## Custos (todas as taxas são informadas)

| Componente | Fórmula |
|---|---|
| Colheitadeira — fixo | horas de turno mobilizadas × R$/h |
| Colheitadeira — variável | horas colhendo × R$/h |
| Colheitadeira — combustível | (horas colhendo + deslocando) × L/h × R$/L |
| Caminhão — fixo | horas de jornada mobilizadas × R$/h |
| Caminhão — variável | km rodados × R$/km |
| Caminhão — combustível | km ÷ (km/L) × R$/L |
| Recepção | t entregues × R$/t |
| Outros | por dia de operação, por tonelada ou fixo |

O custo de tempo improdutivo (esperas, filas) **já está** no custo fixo horário. Nos gargalos, a "consequência financeira" mostra essa parcela — não é somada de novo. Sem preço de referência da saca, o volume em risco não é valorado.

## Gargalos

Regras automáticas sobre os registros: colheitadeiras aguardando caminhão, caminhões ociosos no turno, jornada desalinhada, fila de descarga, cargas retidas com unidade fechada, chegadas acima da capacidade, falhas, baixa utilização, talhões que exigem mais transporte por tonelada, janela/prazo excedidos e clima. Cada um traz evidência, duração, frequência, recursos, consequência (h, t, R$) com fórmula e recomendação. Quando há um cenário de validação, a recomendação é **testada em nova simulação com a mesma semente** e classificada como *confirmada*, *confirmada com trade-off* (melhora o alvo mas encarece a tonelada) ou *não confirmada*.

## Cenários e sensibilidade

Cenários são modificações declarativas sobre a configuração base. Todos usam **números aleatórios comuns** (cada recurso tem seu próprio fluxo aleatório derivado da semente), o que torna as diferenças entre cenários atribuíveis às modificações. Com replicações, a tabela traz média e IC 95% (t de Student). Cenários de **condição externa** (chuva, produtividade, distância, falhas) são testes de estresse e não concorrem ao "melhor cenário". O sistema mostra separadamente o cenário mais rápido e o de menor custo por tonelada — eles frequentemente diferem.

## Otimização

| Problema | Método | Garantia |
|---|---|---|
| Tamanho e composição da frota | CP-SAT para cada K (máx. vazão, depois mín. custo horário) + enumeração de K + re-simulação dos candidatos | **Ótimo para o modelo analítico** em regime permanente; recomendação final pela simulação (estimativa) |
| Distribuição dos caminhões entre colheitadeiras | CP-SAT lexicográfico | Ótimo para o modelo analítico; comparado por simulação com o despacho dinâmico |
| Sequência de talhões | CP-SAT com `AddCircuit` por máquina, deslocamentos e liberação | Ótimo (ou viável com gap informado) no modelo de sequenciamento; validado por simulação |
| Capacidade de recebimento | Bisseção sobre simulações | **Heurístico** — tabela com todos os pontos avaliados |

O modelo analítico de fluxo usa: taxa efetiva da colheitadeira (incluindo descarga do tanque), ciclo do caminhão = enchimento + manobra + ida + descarga + volta, e capacidade diária de recebimento. Ele **não** representa filas, variabilidade nem falhas discretas — por isso todo resultado é re-simulado. Os testes comparam o CP-SAT com força bruta em instâncias pequenas.

## Dados, calibração e limitações

* Os cenários de exemplo são **sintéticos** e estão marcados em todas as telas e relatórios.
* Dados próprios podem ser importados (CSV/Excel) com validação de colunas, tipos, unidades, faixas, duplicidades e consistência.
* Observações reais (duração, t/dia, ritmo de colheita, tempos de viagem, descarga, fila...) são comparadas com a simulação. A calibração ajusta um fator por métrica (seção áurea) e salva **uma nova operação**, marcando os parâmetros como `calibrado`; os originais são preservados.
* O AgroRitmo **não** afirma representar fielmente uma fazenda sem calibração e validação com observações independentes.
* Simplificações conhecidas: posições de talhões esquemáticas (deslocamento = distância em linha reta × 1,3); sem transbordo (graneleiro) intermediário; secador/armazenagem não modelados além da recepção; turnos que cruzam a meia-noite não suportados; caminhões não falham no meio de uma viagem; produtividade de cada talhão é a informada (sem variação espacial).
