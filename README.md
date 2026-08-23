# Teste Técnico — Pessoa Desenvolvedora

Olá! Obrigado pelo interesse na vaga.

Este teste foi montado a partir de um problema real do nosso dia a dia. Não é um exercício de algoritmo: é o tipo de coisa que você faria na primeira semana aqui.

**Prazo:** entrega até segunda-feira, às 12h, por e-mail (link de repositório Git ou .zip).

---

## Sobre o uso de IA

Use a vontade. Copilot, Claude, ChatGPT, o que preferir — aqui dentro a gente usa.

O que a gente avalia não é se você escreveu o código sozinho, e sim se você **entende o que entregou** e se sabe onde a ferramenta erra. Por isso o `DECISOES.md` (item 4) tem uma seção obrigatória sobre isso. **Entrega sem essa seção preenchida não será avaliada.**

Um aviso honesto: este teste tem armadilhas que uma IA sem supervisão não resolve sozinha. Um código bonito que roda sem erro e devolve o número errado pontua menos do que um código simples que devolve o número certo.

---

## Contexto

Somos uma distribuidora de produtos farmacêuticos e de beleza. Temos 4 centros de distribuição: **Campinas, Belo Horizonte, São Caetano e Londrina**.

Cada CD exporta seu saldo de estoque do WMS em CSV. Hoje uma pessoa junta esses 4 arquivos no Excel toda semana, na mão. Queremos automatizar isso.

Os arquivos estão em `dados/`. São exportações reais (anonimizadas), do jeito que saem do sistema. **Não presuma que estão limpos.**

**Data da extração:** 20/08/2026 (use essa data como "hoje" para qualquer cálculo de validade).

### Dicionário de dados

| Coluna | Descrição |
|---|---|
| `codigo` | Código do produto no ERP. Tem 7 dígitos. |
| `descricao` | Descrição do produto conforme o cadastro **daquele CD** |
| `lote` | Número do lote |
| `validade` | Data de validade do lote |
| `saldo` | Quantidade disponível **do lote** |
| `vendas_mes_ant` | Quantidade vendida **do produto**, naquele CD, no mês anterior |

---

## O que entregar

### 1. Consolidação — `consolidado.csv`

Uma linha por produto, com:

- `codigo`
- `descricao`
- saldo por CD (uma coluna para cada um dos 4)
- `saldo_total`
- `vendas_mes_ant_total`
- `cobertura_meses` — quantos meses o saldo atual cobre, no ritmo de venda do mês anterior

### 2. Anomalias — `anomalias.csv`

Ao longo do trabalho você provavelmente vai esbarrar em coisas estranhas nos dados. Registre cada uma:

- `cd`, `codigo`, `lote` (quando aplicável)
- `tipo` — o que é o problema
- `gravidade` — sua classificação
- `acao_sugerida` — o que você faria a respeito

Considere tanto problemas técnicos (do arquivo) quanto problemas operacionais (do estoque). Alguns exigem correção no código; outros são coisas que alguém da operação precisa resolver — e nesse caso o seu trabalho é fazer o problema aparecer, não escondê-lo.

### 3. O código

Linguagem e stack à sua escolha — use o que você domina. Inclua instruções de como rodar.

O que a gente olha: se dá pra entender lendo, se dá pra rodar de novo no mês que vem quando chegarem arquivos novos, e se erra de forma barulhenta em vez de silenciosa.

### 4. `DECISOES.md`

Este arquivo pesa tanto quanto o código. Seções obrigatórias:

**a) Perguntas.** Liste as perguntas que você teria feito antes de começar, se tivesse alguém pra perguntar. Se você não teve nenhuma dúvida ao ler este enunciado, algo está errado — ele é ambíguo de propósito em alguns pontos.

**b) Premissas.** Onde você não tinha resposta, o que você assumiu e por quê.

**c) Anomalias.** Para cada anomalia que encontrou: como você percebeu, e por que tratou daquele jeito.

**d) Uso de IA.** Onde você usou, o que ela acertou, **onde ela errou ou te levou pro caminho errado, e como você percebeu**. Resposta genérica ("usei pra acelerar o boilerplate") não conta. Queremos um caso concreto. Se você não usou IA em nenhum momento, escreva isso e explique o porquê.

**e) Dívida.** O que ficou de fora, e o que você faria com mais uma semana.

### 5. `REVISAO.md` — revisão de código

O arquivo `revisao/sync_wms.js` está rodando em produção hoje. Ele foi escrito às pressas e ninguém revisou.

- Liste os problemas que você encontrar, **ordenados por gravidade para o negócio** — não por ordem de aparição no arquivo.
- Para cada um: qual seria a consequência prática se o problema acontecesse às 3h da manhã de um sábado.
- Separe os problemas que apareceriam num teste local dos que só apareceriam em produção.
- Reescreva **os dois piores**. Só esses dois — não precisa refatorar o arquivo inteiro.

---

## Estrutura sugerida da entrega

```
sua-entrega/
├── README.md          (como rodar)
├── DECISOES.md
├── REVISAO.md
├── consolidado.csv
├── anomalias.csv
└── src/
```

---

## Como avaliamos

| Peso | O que |
|---|---|
| 35% | Os números do `consolidado.csv` estão certos |
| 25% | `DECISOES.md` — qualidade das perguntas, das premissas e da honestidade sobre IA |
| 20% | `REVISAO.md` — priorização e leitura de consequência |
| 20% | Código — clareza, tratamento de erro, dá pra rodar de novo |

Não avaliamos: quantidade de código, cobertura de testes acima do razoável, arquitetura elaborada demais para o tamanho do problema. Solução simples que funciona é melhor que solução sofisticada.

Qualquer dúvida de enunciado, pode perguntar por e-mail — perguntar é bem visto, não o contrário.

Boa sorte!
