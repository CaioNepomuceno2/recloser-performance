# Metodologia

Este documento descreve como cada número do README é calculado, as premissas e como interpretá-los.

## 1. Perguntas

1. Que clientes e que rede cada religador protege (zona de proteção)?
2. Como os dispositivos de proteção se comportaram em 2026 e onde há sinal de falta de seletividade?
3. Onde um religador novo evita mais consumidores-hora interrompidos (CHI) e DEC?
4. A priorização teria apontado onde a distribuidora instalou religadores entre 2024 e 2025?

## 2. Dados

| Base | Uso | Período |
|---|---|---|
| BDGD (ANEEL, PRODIST Módulo 10), Energisa MT | `SSDMT` (segmentos MT), `UNSEMT` (chaves e religadores), `UNREMT` (reguladores), `UNTRMT` (trafos MT), `UCBT`/`UCMT` (clientes), `CTMT` (circuitos) | Snapshots de 31/12/2024 e 31/12/2025 |
| Interrupções (ANEEL), harmonizadas pelo `distribution-asset-risk` | Falhas MT por alimentador (taxa e duração) e, em 2026, o elemento que interrompeu | 2022-2026 (jan-jul) |
| `automation-impact` | R$/CHI (compensação e social), fração regulatória do CHI, efeito medido por religador | 2018-2025 |

Falhas consideradas: origem interna, não programadas, com origem na média tensão (mesmo filtro do
`distribution-asset-risk`).

## 3. Grafo e árvore radial (`topologia.py`)

* **Nós:** pontos de acoplamento (PAC). Os PAC de 19 ou 20 caracteres codificam a coordenada em SIRGAS 2000 /
  UTM 21S, em centímetros: os primeiros 8 ou 9 dígitos são o X, os 9 seguintes são o Y, e o sufixo diz o tipo de
  nó. A conferência com a coordenada geográfica das chaves dá erro mediano de 0,00005 m.
* **Arestas:** segmentos (comprimento `COMP`), chaves e religadores fechados (`P_N_OPE = F`) e reguladores. Chaves
  normalmente abertas não entram, porque são os pontos de interligação entre alimentadores.
* **Raiz:** uma raiz virtual ligada ao `PAC_INI` de todos os circuitos. Uma busca em largura dá a árvore. Cada nó
  herda o alimentador do ramo da raiz em que está.
* **Reparo de lacunas:** um componente sem ligação com a raiz é religado ao nó alcançado mais próximo do mesmo
  circuito (`CTMT`), se a distância for de no máximo 500 m. São até 3 ondas. Em 2025 foram 48 religações, com lacuna
  mediana de 1,4 m. A cobertura de clientes passou de 92% para 99,9%.
* **Arestas paralelas:** quando há mais de uma aresta entre o mesmo par de nós, vale a de maior prioridade
  (disjuntor > religador > seccionalizador > fusível > chave > regulador > segmento).
* **Religadores de saída:** um religador a até 2 manobras do `PAC_INI` e sem clientes a jusante na árvore é
  classificado como religador de saída. Ele faz o papel do disjuntor, entre o barramento da subestação e o início do
  alimentador. Esses religadores não entram como religadores de linha.

## 4. Zonas e modelo de confiabilidade (`zonas.py`)

Dispositivos de **nível religador**: saída do alimentador, religadores de linha e seccionalizadores. **Fusível:**
chaves fusíveis (`TIP_UNID` 22 a 27).

Para cada nó `v` (aresta pai → `v`):

* `N(v)`: clientes a jusante, somando trafos (UCBT por `UNI_TR_MT`) e clientes MT (UCMT por PAC);
* `dr(v)`: dispositivo de nível religador mais próximo a montante (pode ser o próprio `v`);
* `dp(v)`: dispositivo de proteção mais próximo a montante, religador ou fusível;
* `λ_v = taxa_f × comp_v`: falhas/ano no trecho. A taxa `taxa_f` por metro é a média anual de falhas MT do
  alimentador `f` dividida pela sua extensão;
* `p_v`: probabilidade de a falta virar interrupção sustentada. Vale 1 sob fusível (toda falta queima o elo) e
  `1 - τ` fora de ramal com fusível (o religamento elimina a fração `τ` de faltas transitórias).

Consumidores interrompidos por ano esperados no alimentador:

```
CI_f = Σ_v λ_v · p_v · N(dp(v))
```

### Calibração
Com a taxa uniforme, `CI_f` reproduz o ordenamento dos alimentadores: Spearman de 0,86 com o CI observado em
2023-2025, em 636 alimentadores. O nível, porém, depende de quanto da falha cai em ramais. Para cada alimentador:

```
fator_CI   = clip(CI_obs / CI_f, 0,2, 5)
duração    = CHI_obs / CI_obs
chi_por_ci = fator_CI · duração
CHI_f      = CI_f · chi_por_ci
```

Assim o modelo reproduz o CHI histórico de cada alimentador. A topologia só decide **como** esse CHI se distribui
entre as zonas.

### Ganho de um religador novo
* **No tronco, nó `c`, com `d = dr(c)`:**

  ```
  ΔCI = (1 - τ) · L(c) · (N(d) - N(c))
  ```

  `L(c)` é a taxa de falhas a jusante de `c` que hoje é eliminada por `d`, ou seja, sem passar por outro religador
  nem por fusível.

* **No lugar de um fusível `f`:**

  ```
  ΔCI = τ · Λ_f · N(f)
  ```

  `Λ_f` é a taxa de falhas eliminadas por esse fusível.

O ganho em CHI é `ΔCI · chi_por_ci`. Os testes conferem que a fórmula bate com a diferença exata de `CI` antes e
depois de instalar (`tests/test_recloser.py`).

## 5. Otimização (`otimizacao.py`)

* **Candidatos:**
  * nós do tronco com pelo menos 50 clientes a jusante e pelo menos 50 clientes protegidos (`N(d) - N(c)`);
  * chaves fusíveis com pelo menos 50 clientes a jusante.

  Em ambos os casos, com menos de 3 religadores em série acima.
* **Guloso:** instala no nó de maior ganho, recalcula o alimentador alterado e repete. A redução de CHI é monótona e
  submodular no conjunto de religadores, porque cada religador a mais reduz o ganho dos outros da mesma zona. Com só um
  limite de quantidade, isso daria ao guloso a garantia clássica de pelo menos `1 - 1/e ≈ 63%` do ótimo. A restrição de
  no máximo 3 religadores em série foge desse caso, então aqui o guloso é uma heurística e a garantia de 63% não está
  demonstrada. Nos testes, com redes pequenas, ele coincide com a força bruta para k = 1 e 2.
* **Regras de comparação**, avaliadas pelo mesmo modelo:
  * dividir ao meio (em km) a zona com mais rede;
  * dividir ao meio (em clientes) a zona com mais clientes;
  * local sorteado (média de 10 sorteios).
* **Valoração:**
  * DEC (min) = `CHI · 60 / 2.126.558` consumidores;
  * R$ social = `CHI · 5,94`;
  * R$ compensação = `CHI · 0,76 · 1,93`, com valores do `automation-impact`;
  * VPL em 20 anos a 8% a.a.;
  * custo de R$ 160 mil por religador, **ilustrativo**.

## 6. Backtest (`04_backtest.py`)

* **Ponto no tempo:** usa a rede de dez/2024 e as falhas de 2022 a 2024.
* **Instalação nova:** religador fechado na BDGD de 2025 cujo código não existia em 2024 e que não tem religador de
  2024 a menos de 100 m. São 363. Desses, 272 ficam a até 50 m de um nó de 2024. Se o ponto cai dentro de um ramal
  com fusível, o religador é tratado como troca do fusível que protege o ramal.
* **Métricas:**
  * percentil do ganho do ponto real entre os candidatos;
  * AUC por alimentador para "recebeu religador", com o modelo (maior ganho), a extensão, os clientes e o CHI
    histórico;
  * CHI evitado pelas instalações reais contra o mesmo número de religadores escolhido pelo guloso;
  * CHI por religador real contra o efeito medido por diferenças em diferenças no `automation-impact`.

## 7. Sinal de seletividade (`03_desempenho_2026.py`)

Para alimentadores com saída por disjuntor, pelo menos um religador de linha e pelo menos 10 aberturas de disjuntor
ou religador em 2026:

* **Fração esperada:** taxa de falhas fora de ramais com fusível na zona da saída, dividida pela taxa total fora de
  ramais com fusível;
* **Fração observada:** aberturas do disjuntor / (disjuntor + religador);
* **Teste:** binomial unilateral (observada > esperada), com p-valores ajustados por Benjamini-Hochberg. Um
  alimentador é "suspeito" com p ajustado < 0,05.

## 8. Premissas

| Premissa | Valor | Fonte | Efeito |
|---|---|---|---|
| Faltas transitórias eliminadas pelo religamento (`τ`) | 0,5 | Faixa típica de redes aéreas (premissa) | 0,3 a 0,7 muda a razão modelo/regra entre 4,5× e 6,9× |
| Taxa de falhas uniforme por km no alimentador | — | Simplificação | Dados de ocorrência por trecho a substituem |
| Fator de calibração por alimentador | entre 0,2 e 5 | Evita extremos | Sem calibração: razão de 7,3× |
| Mínimo de clientes por candidato | 50 | Premissa | 25 ou 100: razão de 5,5× / 4,7× |
| Religadores em série | máx. 3 | Simplificação da coordenação | Substituir por estudo de proteção |
| Custo do religador | R$ 160 mil | Ilustrativo, igual ao `automation-impact` | Só afeta VPL e payback |
| R$/CHI | 5,94 (social), 1,93 (compensação, sobre CHI regulatório) | `automation-impact` | Só afeta a valoração |

## 9. Como interpretar

* **"53 min de DEC com 100 religadores":** é a redução de CHI esperado no modelo calibrado, convertida em DEC. É uma
  estimativa do potencial dos locais, não uma promessa. O backtest sugere que o modelo é conservador em nível,
  porque o efeito medido em campo para instalações típicas é cerca de 3× o modelado.
* **"5× a regra por extensão":** compara locais com a mesma régua. É o resultado mais robusto e aparece em todos os
  cenários de sensibilidade.
* **"AUC 0,76 da extensão":** descreve a prática, ou seja, onde a distribuidora instalou. Não diz que a prática está
  errada: religadores em linhas longas também reduzem tempo de deslocamento e patrulha, efeito que o modelo não
  captura.
* **"20 de 52 alimentadores suspeitos":** é uma lista para a engenharia de proteção olhar primeiro, não um laudo.
