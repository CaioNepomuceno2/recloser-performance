# Decisões de dados e porta de qualidade para a Energisa MS (EMS)

Este documento foi escrito e commitado **antes de montar a primeira árvore de MS** (`scripts/01_topologia.py` não tinha
rodado em MS) e antes de qualquer resultado de zonas, de posicionamento ou de backtest. Até aqui só rodaram o
extrator das camadas da BDGD (`scripts/00_cache_bdgd.py`) e quatro diagnósticos de dados, que **não calculam nenhum resultado do estudo**:
`diagnostico_pac.py`, `diagnostico_cadastro.py`, `diagnostico_aneel.py` e `diagnostico_instalacoes.py`, mais
`tabelas_docs.py`, que só imprime as tabelas abaixo. As saídas ficam em [`reports/ems/diagnostico/`](../reports/ems/diagnostico/),
e cada tabela vem de um desses arquivos. Execução de 07/11/2026.

Nomes: **MT** é a Energisa Mato Grosso, a distribuidora dos resultados publicados neste repositório; **MS** é a Energisa Mato
Grosso do Sul. As decisões de dados de MS que vêm da base (`distribution-asset-risk`) e as do `automation-impact` estão nos
`docs/decisoes_ems.md` de lá e **não são repetidas** aqui. Os resultados e a metodologia de MT **não mudam**.

> Projeto independente, sem vínculo com a Energisa ou com a ANEEL. Só dados abertos (ANEEL e IBGE).

## Resumo das decisões

| # | Tema | O que os dados de MS mostram | Decisão |
|---|---|---|---|
| 1 | Codificação do PAC | Os PAC de 19 a 20 caracteres são X e Y em centímetros no **SIRGAS 2000 / UTM 21S para o estado todo**, inclusive a leste de 54° W, onde o X passa de 1.000.000 m (seção 2) | A suposição de MT vale em MS. Nada a corrigir na decodificação; a referência vira a chave `crs_pac` (31981) e o casamento a 50 m / 100 m fica como em MT |
| 2 | Nome do circuito | `CTMT.NOME` tem 5 caracteres alfanuméricos (`RBR53`) e as falhas da base usam `0RBR53`. Sem completar com zero, **0% das falhas casam** com o cadastro; completando, 98,6% (seção 4.2) | `alimentador.largura_nome: 6` (em MT fica sem a chave, e o código não muda) |
| 3 | Cadastro | As 7 camadas e todos os campos existem em 2024 e 2025; mapeamento de `TIP_UNID` de MT mantido (seção 3) | Mesmas camadas, mesmos códigos, mesma topologia |
| 4 | Porta de qualidade | MT liga 99,9% dos clientes à saída do alimentador; em MS o cadastro liga 99,8% dos consumidores a um transformador ou PAC (seção 3.3) | **Pré-registrada: mínimo de 95%** de clientes ligados à saída (seção 6). Abaixo disso, só diagnósticos e a causa |
| 5 | Linhas repetidas | `count(*)` igual a `count(distinct *)` em todos os arquivos lidos, exceto 799 linhas (0,054%) nas interrupções de 2018 a 2020 (seção 4.1) | Ler como publicado, como na base |
| 6 | 2026 | Sem nenhum registro em março; elemento identificado de 100% em janeiro a 30% em abril; `DISJUNTOR` é 0,6% das interrupções (seção 4.3) | O sinal de seletividade é **descritivo**, com o número de alimentadores elegíveis ao lado |
| 7 | Instalação nova no backtest | 291 religadores novos pela regra de MT; 79% têm `DAT_CON` em 2024 ou 2025; só 12 códigos de religador somem (seção 5) | Regra de MT como definição principal, uma sensibilidade com `DAT_CON` no período, e a limitação documentada. Nada de pareamento forçado |
| 8 | Efeito do religador | O `valor.json` de MS traz `origem_efeito = "transportado de MT"` | Toda saída que lê esse arquivo repete o rótulo; nada aqui é medida de MS (seção 7) |

## 1. Fonte e snapshots

A BDGD vem do ArcGIS Hub da ANEEL. Os oito itens de 31/12 de MS (2018 a 2025) estão em [`configs/params_ems.yaml`](../configs/params_ems.yaml),
com os ids conferidos pela base. O estudo usa **dois**: 2025 (`ano_atual`: zonas e posicionamento) e 2024 (`ano_backtest`: priorização
contra as instalações de 2025). Os zips são lidos de um cache local **somente leitura** (`bdgd.zips`), nada é baixado, e
`scripts/00_cache_bdgd.py` extrai só os arquivos das 7 camadas usadas (cerca de 1,1 GB por ano, contra 2,1 GB do geodatabase inteiro) para
`data/ems/raw/<ano>`, grava Parquet em `data/ems/bdgd/<ano>` e apaga a extração. Nada disso vai para o git.

| Ano | Item | Título | Zip | SHA-256 do zip |
|---|---|---|---|---|
| 2024 | `b7fad4cd388845a08a01643599ec747b` | Energisa_MS_404_2024-12-31_V11_20250730-1637 | 511 MB | `ed1b4eac221355d757cab571803486fd87724f61cf3028b927f1d3add0e786a7` |
| 2025 | `9a1ce360865f4358b31e9fb2d016aac9` | Energisa_MS_404_2025-12-31_V11_20260830-0339 | 480 MB | `e72ef258c71f450c14d947754bd34084a7fb0f176899cee1f7397a78d12c25e2` |

Os dois snapshots são do modelo V11 (os de 2018 a 2020 são M10, com outros nomes de camada e campo, e não entram neste estudo).
O snapshot de 2023 de 17/12/2024 e o item avulso de 31/10/2022 ficam de fora, como na base. O CRS das camadas é `EPSG:4674` (SIRGAS 2000, graus).

## 2. A codificação do PAC: qual referência, e o casamento a 50 m / 100 m

**Pergunta.** Em MT, `topologia.pac_xy` lê os PAC de 19 a 20 caracteres como X e Y em centímetros no "SIRGAS 2000 / UTM 21S". MS cruza dois
fusos (21S a oeste de 54° W, 22S a leste). A codificação de MS usa o 21S para o estado todo, o fuso natural de cada ponto, ou outra coisa?

**Método** (`scripts/diagnostico_pac.py`, sobre as camadas gravadas por `00_cache_bdgd.py` com `extremos_segmentos`). Decodifica cada PAC e mede a distância, no
plano de cada referência candidata (UTM 20S, 21S, 22S, 23S, e "o fuso natural de cada ponto"), até a geometria da própria BDGD: o ponto de cada
trafo e de cada chave, e o primeiro e o último vértice de cada segmento. Mede ainda o formato dos PAC, se os pontos decodificados caem dentro do
estado (malha do IBGE da UF 50, a mesma da base) e o fator de escala da projeção. Números de 2025 (2024 é igual: `pac_utm_2024.json`,
`pac_utm_resumo.csv`).

**Formato.** Quase todo PAC de trafo e de segmento é coordenada. Os de 20 caracteres são exatamente os de X com 9 dígitos, ou seja, X de 1.000.000 m
para cima (conferido em trafos e em segmentos: `comprimento_20_igual_a_x_acima_de_1e6_m = true`). O X vai de 396.749 m a 1.135.608 m.

| Campo | Registros | Com coordenada (19 ou 20 caracteres) | Registros de 19 e de 20 caracteres |
|---|---|---|---|
| UNTRMT.PAC_1 | 106.660 | 99,90% | 19: 99.920, 20: 6.631 |
| UNSEMT.PAC_1 | 161.148 | 98,20% | 19: 147.732, 20: 10.513 |
| UNSEMT.PAC_2 | 161.148 | 97,75% | 19: 147.056, 20: 10.472 |
| SSDMT.PAC_1 | 1.046.026 | 100,00% | 19: 975.320, 20: 70.706 |
| SSDMT.PAC_2 | 1.046.026 | 100,00% | 19: 975.322, 20: 70.704 |
| CTMT.PAC_INI | 362 | 100,00% | 19: 339, 20: 23 |
| UNREMT.PAC_1 | 316 | 97,78% | 19: 288, 20: 21 |

| Leitura do PAC como | Nós distintos | Longitude | Latitude | Dentro do estado | Dentro, com margem de 0,1° |
|---|---|---|---|---|---|
| UTM 20S | 1.199.536 | -64,00 a -56,95 | -24,04 a -17,30 | 5,78% | 6,19% |
| UTM 21S | 1.199.536 | -58,00 a -50,95 | -24,04 a -17,30 | 99,73% | 99,99% |
| UTM 22S | 1.199.536 | -52,00 a -44,95 | -24,04 a -17,30 | 1,16% | 1,78% |
| UTM 23S | 1.199.536 | -46,00 a -38,95 | -24,04 a -17,30 | 0,00% | 0,00% |

**Distância entre a coordenada do PAC e a geometria.**

| Comparação | Referência | Pontos | Mediana | P99 | Máximo | ≤ 1 m | ≤ 50 m | ≤ 100 m |
|---|---|---|---|---|---|---|---|---|
| PAC do trafo x ponto do trafo | UTM 20S | 106.551 | 626.649 m | 638.391 m | 641.351 m | 0,0% | 0,000% | 0,000% |
| PAC do trafo x ponto do trafo | UTM 21S | 106.551 | < 0,01 m | < 0,01 m | 0,03 m | 100,0% | 100,000% | 100,000% |
| PAC do trafo x ponto do trafo | UTM 22S | 106.551 | 625.044 m | 635.386 m | 637.896 m | 0,0% | 0,000% | 0,000% |
| PAC do trafo x ponto do trafo | UTM 23S | 106.551 | 1.253.946 m | 1.274.269 m | 1.278.630 m | 0,0% | 0,000% | 0,000% |
| PAC do trafo x ponto do trafo | fuso natural de cada ponto (21S / 22S) | 106.551 | < 0,01 m | 633.837 m | 637.896 m | 76,7% | 76,697% | 76,697% |
| PAC da chave x ponto da chave | UTM 20S | 158.245 | 627.033 m | 638.467 m | 641.351 m | 0,0% | 0,000% | 0,000% |
| PAC da chave x ponto da chave | UTM 21S | 158.245 | < 0,01 m | 0,30 m | 119 m | 99,2% | 99,991% | 99,997% |
| PAC da chave x ponto da chave | UTM 22S | 158.245 | 625.212 m | 635.492 m | 637.896 m | 0,0% | 0,000% | 0,000% |
| PAC da chave x ponto da chave | UTM 23S | 158.245 | 1.254.189 m | 1.274.543 m | 1.279.549 m | 0,0% | 0,000% | 0,000% |
| PAC da chave x ponto da chave | fuso natural de cada ponto (21S / 22S) | 158.245 | < 0,01 m | 633.935 m | 637.896 m | 75,5% | 76,137% | 76,143% |
| PAC_1 do segmento x 1o vértice | UTM 20S | 1.046.026 | 627.303 m | 638.802 m | 641.348 m | 0,0% | 0,000% | 0,000% |
| PAC_1 do segmento x 1o vértice | UTM 21S | 1.046.026 | < 0,01 m | 1,53 m | 9,06 m | 95,0% | 100,000% | 100,000% |
| PAC_1 do segmento x 1o vértice | UTM 22S | 1.046.026 | 625.362 m | 635.975 m | 637.895 m | 0,0% | 0,000% | 0,000% |
| PAC_1 do segmento x 1o vértice | UTM 23S | 1.046.026 | 1.254.439 m | 1.275.583 m | 1.279.682 m | 0,0% | 0,000% | 0,000% |
| PAC_1 do segmento x 1o vértice | fuso natural de cada ponto (21S / 22S) | 1.046.026 | < 0,01 m | 634.281 m | 637.892 m | 69,2% | 72,896% | 72,896% |
| PAC_2 do segmento x último vértice | UTM 20S | 1.046.026 | 627.302 m | 638.802 m | 641.351 m | 0,0% | 0,000% | 0,000% |
| PAC_2 do segmento x último vértice | UTM 21S | 1.046.026 | < 0,01 m | < 0,01 m | 11,17 m | 99,8% | 100,000% | 100,000% |
| PAC_2 do segmento x último vértice | UTM 22S | 1.046.026 | 625.361 m | 635.976 m | 637.896 m | 0,0% | 0,000% | 0,000% |
| PAC_2 do segmento x último vértice | UTM 23S | 1.046.026 | 1.254.440 m | 1.275.583 m | 1.279.682 m | 0,0% | 0,000% | 0,000% |
| PAC_2 do segmento x último vértice | fuso natural de cada ponto (21S / 22S) | 1.046.026 | < 0,01 m | 634.282 m | 637.896 m | 72,7% | 72,894% | 72,894% |

**Leitura.**

* **O UTM 21S, para o estado todo, explica os dados.** A distância mediana é menor que 1 cm; todos os trafos ficam a menos de 4 cm do ponto
  da BDGD. Nas chaves, 99,2% ficam a 1 m e só 15 de 158 mil passam de 50 m (5 passam de 100 m, a pior a 119 m). Nos segmentos, 95,0% dos
  PAC_1 ficam a 1 m do primeiro vértice (todos a no máximo 9 m) e 99,8% dos PAC_2 a 1 m do último (todos a no máximo 12 m). Trocar PAC_1 e PAC_2 de lado piora
  tudo (`invertido_ate_1m`, em `pac_utm_2025.json`).
* **Nenhuma outra referência serve.** O 22S e o 20S erram por cerca de 625 km, o 23S por 1.250 km.
* **O "fuso natural" não serve:** acerta só os pontos a oeste de 54° W (77% dos trafos e 73% dos segmentos). A leste (23% dos trafos e 27% dos segmentos) o PAC continua em coordenadas do 21S,
  **estendidas** além do limite usual da zona (X acima de 1.000.000 m, 6% dos PAC de trafo e 7% dos de segmento). Ler um PAC de 20 caracteres como X de 8
  dígitos, ou tratar o X como "UTM de fuso próprio", colocaria esses nós a centenas de quilômetros.
* **Plausibilidade geográfica.** Lidos como 21S, 99,73% dos 1,2 milhão de nós distintos caem dentro do estado (99,99% com margem de 0,1°, que cobre
  a simplificação da malha do IBGE). Lidos como 20S, 22S ou 23S, caem 5,8%, 1,2% e 0%.
* **Escala.** O fator de escala do 21S vai de 0,9996 (57° W) a 1,0046 (50,9° W, 20° S). Estendido até o extremo leste, a distância no plano difere da distância no terreno
  em no máximo 0,5%: 100 m viram 99,5 m e o limite de 500 m do reparo de lacunas, 497,7 m. Isso é desprezível diante dos limites de 50 m e 100 m do
  casamento do backtest, e não se corrige.

**Decisão.** A suposição de MT **vale em MS**: UTM 21S (EPSG:31981), X e Y em centímetros, para o estado todo. Não houve nada a corrigir na
decodificação. Mesmo assim a referência deixa de ser uma constante espalhada pelo código: é a chave `crs_pac` da configuração (padrão 31981), usada em
`04_backtest.py`, `05_otimizacao.py` e `06_figuras.py`, e os testes cobrem PAC de 19 e de 20 caracteres de MS contra o `pyproj`.
O casamento a 50 m (localização do religador novo na rede de 2024) e a 100 m (religador de 2024 por perto) fica como em MT.

## 3. O cadastro de MS (BDGD de 2024 e de 2025)

### 3.1 Camadas, equipamentos e `TIP_UNID`

Os 7 conjuntos de campos que o extrator lê (`SSDMT`, `UNSEMT`, `UNREMT`, `UNTRMT`, `CTMT`, `UCBT_tab`, `UCMT_tab`) existem nos dois snapshots, sem campo faltando.
`DAT_CON` é texto `dd/mm/aaaa` em 100% das chaves.

|  | 2024 | 2025 |
|---|---|---|
| Segmentos de MT (`SSDMT`) | 1.026.928 | 1.046.026 |
| Rede MT (km) | 90.414 | 91.453 |
| Segmentos sem `COMP` (nulo ou zero) | 0 | 0 |
| Chaves e equipamentos (`UNSEMT`) | 137.493 | 161.148 |
| Religadores (`TIP_UNID` 32) | 2.295 | 2.646 |
| Religadores telecomandados | 35,9% | 68,4% |
| Religadores normalmente abertos | 16,2% | 15,8% |
| Chaves fusíveis (22 a 27) | 116.315 | 139.480 |
| Seccionalizadores (35, 36) | 268 | 456 |
| Disjuntores (29, 30, 53) | 140 | 139 |
| Fora do mapeamento (virão como `chave`) | 13,4% | 11,4% |
| Reguladores (`UNREMT`) | 294 | 316 |
| Transformadores MT (`UNTRMT`) | 103.840 | 106.660 |
| Circuitos (`CTMT`) | 359 | 362 |
| Consumidores BT (`UCBT_tab`) | 1.454.750 | 1.400.910 |
| Consumidores MT (`UCMT_tab`) | 6.544 | 6.801 |
| BT com transformador no cadastro | 99,78% | 99,79% |
| MT com PAC na rede | 99,63% | 99,82% |
| Consumidores ligados a um transformador ou PAC | 99,78% | 99,79% |
| `PAC_INI` dos circuitos presente na rede | 100,0% | 100,0% |
| `CTMT` do cliente BT igual ao do seu transformador | 100,00% | 99,91% |
| `UNSEMT.CTMT` existe em `CTMT` | 98,6% | 99,0% |
| `CTMT.NOME`: 5 caracteres | 357 | 362 |
| `CTMT.NOME`: só dígitos | 0% | 0% |
| `CTMT.NOME` repetido (depois de completar a 6) | 0 | 0 |

O mapeamento de `TIP_UNID` é o de MT (32 religador; 22 a 27 chave fusível; 35 e 36 seccionalizador; 29, 30 e 53 disjuntor), conferido pela
base em MS (68% dos religadores telecomandados em 2025, `TUC` 345 só em religadores). Códigos fora do mapeamento (19, 33, 49, 47, 18) viram `chave`: entram
no grafo como arestas sem função de proteção, como em MT. O código 19 é 11% das chaves de MS e nenhum rótulo dele foi encontrado nos dados.

| `TIP_UNID` | Classe no estudo | Equipamentos | Telecomandados | Normalmente abertos |
|---|---|---|---|---|
| 22 | fusivel | 137.850 | 0,0% | 0,0% |
| 19 | chave | 17.447 | 0,0% | 23,4% |
| 32 | religador | 2.646 | 68,4% | 15,8% |
| 27 | fusivel | 1.624 | 0,1% | 0,9% |
| 33 | chave | 453 | 0,0% | 23,2% |
| 36 | seccionalizador | 434 | 0,0% | 0,0% |
| 49 | chave | 420 | 0,0% | 1,7% |
| 29 | disjuntor | 139 | 0,0% | 3,6% |
| 47 | chave | 106 | 0,0% | 3,8% |
| 35 | seccionalizador | 22 | 0,0% | 0,0% |
| 23 | fusivel | 6 | 0,0% | 0,0% |
| 18 | chave | 1 | 0,0% | 0,0% |

**O cadastro de 2025 tem um salto em relação ao de 2024.** Entre os dois snapshots as chaves fusíveis sobem de 116 mil para 139 mil, os seccionalizadores de 268 para 456 e
os religadores telecomandados de 36% para 68% (seção 5). É uma atualização cadastral grande, e vale para qualquer comparação 2024 x 2025.

### 3.2 Nome do circuito e chave do histórico de falhas

Em MT, `CTMT.NOME` tem 6 dígitos. Em MS tem 5 caracteres alfanuméricos (`RBR01`, `CGP02`; em 2024, dois circuitos têm nome de 10 caracteres), nenhum só com dígitos, e não há nome repetido. O
`distribution-asset-risk` usa como chave o **nome completado com zeros à esquerda até 6 caracteres** (`0RBR53`; ver o `saidas_ems.md` de lá).
`dados.historico_alimentador` casa `falhas.alimentador` com `CTMT.NOME`, e **sem completar o nome nenhuma falha casa**: o histórico de todo alimentador ficaria vazio, a taxa de falhas
seria zero e o modelo inteiro seria zero, sem erro nenhum. Por isso `alimentador.largura_nome: 6` é obrigatório na configuração de MS. Em MT a chave não existe,
o código não faz nada com o nome e o resultado é idêntico ao anterior (o histórico de MT tem nomes de 6 e de 8 caracteres, e completar a 6 não mexe em nenhum deles, mas
a escolha mais segura é não tocar).

### 3.3 Clientes do cadastro

Os consumidores de BT entram pelo transformador (`UCBT_tab.UNI_TR_MT` = `UNTRMT.COD_ID`) e os de MT pelo PAC (`UCMT_tab.PAC`). No cadastro,
99,8% dos consumidores se ligam a um transformador ou a um PAC (tabela da seção 3.1), e o circuito do consumidor é o do seu transformador em 99,9% a 100%.
Essa é uma medida do **cadastro**, sem árvore nenhuma; o que a árvore consegue alcançar a partir da saída do alimentador é a porta da seção 6.

## 4. Interrupções e falhas (ANEEL)

### 4.1 Linhas repetidas: `count(*)` contra `count(distinct *)`

Todo arquivo que o estudo lê (as interrupções e as falhas da base, e as camadas da BDGD em Parquet), em
[`duplicatas_arquivos.csv`](../reports/ems/diagnostico/duplicatas_arquivos.csv):

| Arquivo | `count(*)` | `count(distinct *)` | Repetidas | % |
|---|---|---|---|---|
| interrupcoes (todos os anos) | 1.466.882 | 1.466.083 | 799 | 0,054 |
| interrupcoes, só 2026 | 117.890 | 117.890 | 0 | 0,000 |
| interrupcoes, 2026 MT interna não programada (a que 03 lê) | 103.373 | 103.373 | 0 | 0,000 |
| falhas.parquet | 132.345 | 132.345 | 0 | 0,000 |
| BDGD 2024 SSDMT | 1.026.928 | 1.026.928 | 0 | 0,000 |
| BDGD 2024 UNSEMT | 137.493 | 137.493 | 0 | 0,000 |
| BDGD 2024 UNREMT | 294 | 294 | 0 | 0,000 |
| BDGD 2024 UNTRMT | 103.840 | 103.840 | 0 | 0,000 |
| BDGD 2024 CTMT | 359 | 359 | 0 | 0,000 |
| BDGD 2024 UCBT_tab_agg | 84.808 | 84.808 | 0 | 0,000 |
| BDGD 2024 UCMT_tab_agg | 5.028 | 5.028 | 0 | 0,000 |
| BDGD 2025 SSDMT | 1.046.026 | 1.046.026 | 0 | 0,000 |
| BDGD 2025 UNSEMT | 161.148 | 161.148 | 0 | 0,000 |
| BDGD 2025 UNREMT | 316 | 316 | 0 | 0,000 |
| BDGD 2025 UNTRMT | 106.660 | 106.660 | 0 | 0,000 |
| BDGD 2025 CTMT | 362 | 362 | 0 | 0,000 |
| BDGD 2025 UCBT_tab_agg | 84.812 | 84.812 | 0 | 0,000 |
| BDGD 2025 UCMT_tab_agg | 5.786 | 5.786 | 0 | 0,000 |

* As 799 linhas repetidas estão em 2018 a 2020 (a base mede e documenta: 0,28%, 0,24% e 0,05% das linhas nesses anos, menos de 0,03% do CHI). Este estudo usa
  `falhas.parquet` (2023 a 2025 e 2022 a 2024) e as interrupções de 2026, **sem nenhuma linha repetida**. Nada é removido.
* Os arquivos de continuidade da ANEEL (`indicadores-continuidade`, com cada linha duas vezes) **não são lidos aqui**; quem os lê é a base, com o leitor que remove as duplicatas.
  O `valor.json` vem do `automation-impact`, que usa a leitura sem repetidas.

### 4.2 Vínculo das falhas com o cadastro

Parcela do histórico de falhas (a base de MS, 2023 a 2025 para o cadastro de 2025 e 2022 a 2024 para o de 2024, que é a janela de cada análise) que casa com um circuito:

| Cadastro | Falhas de | Chave do nome do circuito | Falhas | Casam | CHI casa | Alimentadores do histórico que casam |
|---|---|---|---|---|---|---|
| 2025 | 2023-2025 | nome do cadastro sem completar | 326.054 | 0,00% | 0,00% | 0 de 358 |
| 2025 | 2023-2025 | nome completado com zeros até 6 | 326.054 | 98,64% | 98,44% | 350 de 358 |
| 2024 | 2022-2024 | nome do cadastro sem completar | 300.938 | 0,00% | 0,00% | 0 de 356 |
| 2024 | 2022-2024 | nome completado com zeros até 6 | 300.938 | 98,67% | 98,65% | 348 de 356 |

### 4.3 2026

O arquivo de 2026 vai de janeiro a julho **sem nenhum registro em março** (achado da base). A parcela de interrupções de MT (internas, não programadas) que
casa com um circuito do cadastro de 2025, e a que traz o elemento que interrompeu:

| Mês de 2026 | Interrupções de MT (internas, não programadas) | Casam com um circuito do cadastro de 2025 | Com elemento identificado |
|---|---|---|---|
| 1 | 25.741 | 82,1% | 100% |
| 2 | 18.130 | 82,1% | 83% |
| 4 | 15.248 | 85,1% | 30% |
| 5 | 16.065 | 85,2% | 70% |
| 6 | 16.001 | 86,4% | 57% |
| 7 | 12.188 | 86,2% | 66% |
| jan-jul (sem março) | 103.373 | 84,2% | 71% |

| Elemento que interrompeu | Interrupções | % |
|---|---|---|
| NAO IDENTIFICADO | 29.487 | 28,5% |
| MEDIDOR | 28.139 | 27,2% |
| RELIGADOR | 19.681 | 19,0% |
| TRANSFORMADOR | 15.348 | 14,8% |
| CHAVE FUSIVEL | 9.514 | 9,2% |
| CHAVE SECCIONADORA | 627 | 0,6% |
| DISJUNTOR | 577 | 0,6% |

* **O elemento (`DISJUNTOR`, `RELIGADOR`...) só vale como descrição, não como medida.** O preenchimento cai de 100% em janeiro a 30% em abril, e `MEDIDOR` e
  `TRANSFORMADOR` somam 42% das interrupções. Aberturas de disjuntor são 0,6%: o teste de seletividade compara disjuntor com religador e
  tem poucos alimentadores elegíveis (os que têm 10 aberturas dos dois).
* **Decisão:** o sinal de seletividade (`03_desempenho_2026.py`) sai como **descrição**, com o número de alimentadores elegíveis ao lado, sem destaque de manchete, e a figura
  de elementos mostra todos os elementos relevantes (não os 4 de MT).

## 5. "Instalação nova" no backtest

O backtest chama de instalação nova o religador **fechado** no cadastro de 2025 cujo `COD_ID` não existia em 2024 e que não tem religador de 2024 a menos de 100 m.
O `automation-impact` mostra que, em MS, o cadastro mistura instalação e remanejamento (entre os snapshots de 2018 a 2024, os religadores ganhos por circuito somam 1.028 contra um saldo de +292). O que dá para medir no
**par 2024 x 2025** (`scripts/diagnostico_instalacoes.py`):

|  | Valor |
|---|---|
| Chaves e equipamentos (`UNSEMT`), 2024 e 2025 | 137.493 e 161.148 |
| Chaves fusíveis, 2024 e 2025 | 116.315 e 139.480 |
| Seccionalizadores, 2024 e 2025 | 268 e 456 |
| Religadores, 2024 e 2025 (saldo) | 2.295 e 2.646 (+351) |
| Religadores telecomandados, 2024 e 2025 | 36% e 68% |
| `COD_ID` de 2025 que já existia em 2024 | 84,2% |
| `COD_ID` de 2024 que continua em 2025 | 98,7% |
| Religadores fechados em 2025 com `COD_ID` de 2024: n e deslocamento mediano | 1.897 e < 0,01 m |
| ... dentro de 1 m / 50 m / 100 m | 94,9% / 98,4% / 98,6% |
| Religadores fechados em 2025 | 2.229 |
| ... com `COD_ID` novo | 332 |
| ... dos quais a menos de 100 m de um religador antigo (não contam como novos) | 41 |
| **Novos pela regra do backtest** (`COD_ID` novo e nenhum religador antigo a menos de 100 m) | **291** |
| ... com `DAT_CON` em 2024 ou 2025 | 231 (79%) |
| ... com `DAT_CON` anterior a 2024 | 60 (21%) |
| Religadores de 2024 que sumiram (`COD_ID` ausente e nenhum religador a menos de 100 m) | 5 |
| ... só `COD_ID` ausente | 12 |
| Novos em circuitos onde sumiu algum religador | 1 |

* **Neste par** o cadastro não mostra o padrão de remanejamento da série longa: o `COD_ID` dos religadores é estável (98,7% continuam), os que o mantêm ficam parados (deslocamento mediano de zero; 1,4% se movem mais de 100 m)
  e só 12 códigos de religador somem (5 sem outro por perto), contra 291 novos. Dos novos, 79% têm `DAT_CON` em 2024 ou 2025 (230 só em 2025).
* **Mesmo assim há limitações.** 21% dos "novos" têm `DAT_CON` anterior a 2024 (equipamento antigo que recebeu código novo, ou foi movido, ou tem data errada); o salto do
  cadastro (seção 3.1) indica uma atualização cadastral grande em 2025; e o cadastro não separa instalação, remanejamento e recadastramento. O `COD_ID` pode ter sido reaproveitado.
* **Decisão (pré-registrada, sem forçar pareamento):**
  1. a **definição principal** é a de MT, sem mudar parâmetro (`raio_novo_m` = 100 m, `raio_localizacao_m` = 50 m), para comparar com MT;
  2. uma **sensibilidade** restringe os novos aos que têm `DAT_CON` em 2024 ou 2025 (`backtest.anos_data_confirmada`). Ela sai ao lado da principal em `backtest.json`, nunca no lugar dela, e o README diz as duas;
  3. se as duas conclusões divergirem, vale dizer isso, e nenhuma é escolhida pelo resultado;
  4. a limitação (instalação x remanejamento x recadastramento) é repetida no README e em `resultados_ems.md`.

## 6. Porta de qualidade pré-registrada

**Regra.** Os resultados de posicionamento (onde instalar os próximos religadores) e o backtest só são publicados se a reconstrução da topologia ligar pelo menos
**95% dos clientes à saída do seu alimentador**. Em MT são 99,9%.

* **Métrica.** `frac_uc_alcancadas` de `qualidade_topologia.json`, calculada por `scripts/01_topologia.py` **depois do reparo de lacunas**: os clientes (consumidores de BT por transformador e de MT
  por PAC) dos nós que a busca em largura alcança a partir das saídas dos circuitos (`CTMT.PAC_INI`), divididos pelos clientes ligados a um transformador ou PAC do cadastro. É a mesma métrica dos 99,9% de MT.
* **Mínimo.** 0,95, na chave `qualidade.min_frac_uc_alcancadas` (em MT a chave não existe e não há porta). A comparação é `>=`.
* **Cada snapshot na sua análise.** A topologia de **2025** libera as saídas de 2025 (`02_diagnostico.py`, `03_desempenho_2026.py`, `05_otimizacao.py` e as figuras). A de **2024** libera o backtest
  (`04_backtest.py`), que prioriza com a rede de 2024. Se só uma passar, só as saídas dela são publicadas. O backtest usa o cadastro de 2025 apenas para a posição dos religadores novos.
* **Sem ajuste.** `topologia.max_gap_m` fica em 500 m e nada (limite, lacuna, ondas de reparo, mapeamento de chaves) é alterado para passar. A decodificação do PAC foi decidida na seção 2, com evidência de geometria e sem olhar a
  cobertura.
* **Aplicação no código.** `config.exigir_porta` lê `qualidade_topologia.json` e **para** `02`, `03`, `04` e `05` quando o ano não passa (o `06_figuras.py` só desenha o que existe). Há teste dos três casos (passa, falha, MT sem porta).
  `01_topologia.py` grava `porta_qualidade.json` com o veredito de cada ano.
* **Se não passar.** Fica só o que não depende da árvore: `reports/ems/diagnostico/` (PAC, cadastro, ANEEL, instalações), `qualidade_topologia.json`, `porta_qualidade.json` e um
  diagnóstico da causa (`scripts/diagnostico_topologia.py`: quanto da perda vem de componentes sem ligação, de circuitos sem saída na rede e de lacunas maiores que o limite). Nenhum local de religador, lista priorizada,
  curva de DEC evitado nem backtest é publicado, e o README e `resultados_ems.md` dizem isso e por quê.
* **Diagnóstico adicional, que não é porta.** `scripts/diagnostico_topologia.py` também mede a cobertura antes do reparo e a parcela dos clientes alcançados cujo circuito na árvore é o circuito do cadastro do seu transformador.

## 7. O que é publicado e como é rotulado

* **Origem do efeito.** O `valor.json` de MS (`../automation-impact/reports/ems/valor.json`) traz `origem_efeito = "transportado de MT"`: a regra de decisão do `automation-impact` não liberou um efeito medido em MS (72
  eventos e 87 controles, contra 60 e 100 exigidos). Só o backtest usa o efeito por religador (`chi_evitado_por_religador`, a comparação com o modelo), mas **toda saída que lê esse arquivo**
  (`backtest.json`, `backtest_instalacoes.csv`, `curva_k.csv`, `sensibilidade.csv`, `lista_priorizada.csv`, `otimizacao.json`, as figuras 01, 02 e 05, o README e `resultados_ems.md`)
  repete o campo `origem_efeito` (coluna nos CSV, campo nos JSON, rodapé nas figuras). Com `exigir_origem_efeito: true`, o script recusa rodar se o `valor.json` não trouxer o campo.
  Se o `automation-impact` passar a medir o efeito em MS, o rótulo muda no arquivo dele e o daqui o acompanha, sem mexer no código.
* **Nada disso é medida de MS.** A comparação do CHI evitado por religador do modelo com o `valor.json` (`fator_did_sobre_modelo`) compara o modelo com o efeito de MT aplicado à exposição de MS: **não valida o modelo**.
  O README de MT diz que o modelo é "conservador" frente ao efeito medido em campo; essa frase **não é repetida** em MS.
* **DEC.** O DEC evitado usa `uc_total` do `valor.json` (consumidores do cadastro de 2024: 1.458.167). O cadastro de 2025 tem 1,41 milhão de consumidores (1.400.910 de BT e 6.801 de MT; tabela da seção 3.1),
  o que muda o DEC em cerca de 3,5%. O número do `valor.json` é mantido para os dois repositórios falarem do mesmo DEC.
* **R$ e premissas.** R$/CHI vêm de MS (`valor.json`). Custo do religador (R$ 160 mil), vida (20 anos) e taxa (8%) são as premissas ilustrativas de MT, sem recalibrar. O tau (0,5), o mínimo de 50 clientes e os 3 religadores em série
  também são os de MT. **Nenhum parâmetro foi calibrado olhando resultado de MS.**
* **Comparação com MT.** Só descritiva (por consumidor e por km), sem afirmar causa.
* **O guloso** é uma heurística com restrição de religadores em série; a garantia de 63% não vale com essa restrição e não é prometida (redação corrigida de MT).

## 8. Suposições de MT encontradas e como foram tratadas

| Onde | Suposição de MT | Tratamento |
|---|---|---|
| `configs/params.yaml` | `interrupcoes_emt.parquet` fixo | `interrupcoes` e `falhas` por configuração; MS usa `interrupcoes_ems.parquet` da base; o padrão segue `interrupcoes_emt.parquet` |
| `topologia.py`, `04`, `05`, `06` | PAC em "UTM 21S", 31981 escrito no código | Medida em MS (seção 2): vale. Vira `crs_pac` na configuração (padrão 31981) |
| `dados.historico_alimentador` | `CTMT.NOME` igual à chave `falhas.alimentador` | `alimentador.largura_nome` (MS: 6); sem a chave nada muda |
| `config.py`, `01` a `06` | `reports/` e `data/processed/` fixos; `config.ROOT / "reports"` | `paths.reports` e `paths.processed`, com padrão igual a MT; MS grava em `reports/ems` e `data/ems/processed` |
| `00_cache_bdgd.py` | baixa do ArcGIS; anos pela linha de comando sem `--config` | `bdgd.zips` lê o cache local; `argparse` com `--config` e anos |
| `pyproject.toml` | `geopandas` não era dependência, e `pyogrio.read_dataframe` exige | `geopandas` incluído (vale para MT também) |
| `06_figuras.py` | título "Energisa MT", proporção do mapa com a latitude de MT (-13°), 4 elementos fixos na figura de 2026 | `nome`, `mapa.lat_aspecto` e `figuras.elementos` na configuração; padrões iguais a MT |
| `03_desempenho_2026.py` | `DISJUNTOR` e `RELIGADOR` como únicos elementos de interesse | Mantido; no `elemento_2026.csv` e na figura entram todos. Sinal descritivo (seção 4.3) |
| `04_backtest.py` | "instalação nova" = `COD_ID` novo e 100 m; texto "184 dos 363 com a data-padrão de 1980" | Regra mantida; em MS não há data-padrão nos religadores (0 com 1920 ou 1980); sensibilidade por `DAT_CON` (seção 5) |
| README e `metodologia.md` | "o modelo é conservador frente ao efeito medido" | Não repetido em MS (seção 7) |
| `valor.json` | sem `origem_efeito` | Campo exigido em MS e repetido nas saídas |

## 9. O que não foi feito

* Nenhum parâmetro do estudo foi recalibrado para MS, e nenhum resultado foi olhado antes deste documento.
* Os snapshots de 2018 a 2023 não foram lidos (o estudo só usa 2024 e 2025). Se alguém rodar outros anos, os snapshots M10 (2018 a 2020) têm outros nomes de camada e campo e **não estão tratados aqui**.
* O painel e o seletor MT/MS não fazem parte deste repositório.

## Como reproduzir os diagnósticos

```bash
python scripts/00_cache_bdgd.py        --config configs/params_ems.yaml     # lê os zips locais; grava data/ems/bdgd/{2024,2025}
python scripts/diagnostico_pac.py      --config configs/params_ems.yaml
python scripts/diagnostico_cadastro.py --config configs/params_ems.yaml
python scripts/diagnostico_aneel.py    --config configs/params_ems.yaml
python scripts/diagnostico_instalacoes.py --config configs/params_ems.yaml
python scripts/tabelas_docs.py         --config configs/params_ems.yaml pac formato_pac cadastro tip_unid duplicatas vinculo cobertura_2026 elementos_2026 instalacoes
```
