# Solução — consolidação de estoque

## Como executar

Na raiz do projeto, com Python 3.11 ou superior instalado:

```powershell
python sua-entrega/src/etl.py
```

O comando lê os quatro arquivos em `dados/` e recria `sua-entrega/consolidado.csv` e
`sua-entrega/anomalias.csv`. Não há dependências externas.

Para usar outros diretórios ou outra data de referência:

```powershell
python sua-entrega/src/etl.py --input dados --output sua-entrega --reference-date 2026-08-20
```

O processo valida o schema, números, datas, códigos e consistência das vendas antes de
publicar as saídas. Em caso de erro, encerra com código diferente de zero e não substitui
os arquivos por conteúdo parcialmente processado.

## Testes

```powershell
python -m unittest discover -s sua-entrega/tests -v
```

A suíte cobre parsing brasileiro, datas, códigos, duplicidade, descrição canônica,
consolidação, cobertura e falhas de entrada, além de validar os totais dos arquivos reais.

Dentro da pasta tests, existe uma documentação em TESTES.md - explicando o que cada teste faz.

## Regras principais

- `saldo` e `vendas_mes_ant` são unidades inteiras; o `,00` da origem é formatação.
- Códigos curtos recebem zeros à esquerda, mas o valor original permanece no relatório de anomalias.
- Duplicatas idênticas são removidas antes da soma.
- `vendas_mes_ant` é somada uma vez por produto e CD, e não uma vez por lote.
- Saldos negativos são preservados no consolidado e sinalizados para verificar possível erro na última entrada ou falha na extração; confirmado o saldo, a operação pode transferir estoque, dividir em dois envios, aguardar reabastecimento ou cancelar a venda.
- Os saldos por CD, o `saldo_total` e a cobertura incluem somente lotes identificados e não vencidos. Estoque vencido ou com validade não verificável fica fora do disponível, mas permanece visível em colunas próprias.
- O consolidado separa os saldos vencidos, com validade pendente e a vencer em até 7, 8–30, 31–60 e 61–90 dias; lotes acima de 90 dias permanecem apenas no saldo disponível.
- A cobertura é arredondada para duas casas; fica vazia quando a venda total é zero.
