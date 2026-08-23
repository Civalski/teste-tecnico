# Documentação do `etl.py`

O `etl.py` automatiza a consolidação dos arquivos de estoque exportados pelos quatro centros de distribuição. Ele substitui o trabalho manual de reunir planilhas, padronizar dados e calcular os totais por produto.

## Problemas que ele resolve

- reúne os estoques de Campinas, Belo Horizonte, São Caetano e Londrina em uma única visão;
- normaliza códigos de produto com menos de sete dígitos e números no formato brasileiro;
- aceita datas nos formatos `DD/MM/AAAA` e `AAAA-MM-DD` e usa `DD/MM/AAAA` nas saídas que exibem validade;
- converte campos vazios e os marcadores `NaN`, `NULL`, `None`, `N/A` e `NA` para `None`, o nulo nativo do Python;
- evita a soma duplicada de registros idênticos;
- soma no estoque disponível somente lotes identificados e não vencidos, mas mantém os demais saldos em colunas de controle;
- separa, sem dupla contagem, os saldos vencidos, com validade pendente e a vencer nas faixas de até 7, 8–30, 31–60 e 61–90 dias;
- escolhe uma descrição canônica quando o mesmo produto possui descrições diferentes;
- calcula a cobertura de estoque em meses usando `saldo total / vendas do mês anterior`;
- identifica problemas como lote ausente, saldo negativo, produto vencido ou próximo do vencimento, vendas zeradas e formatos divergentes.

## Como funciona

O processamento segue três etapas:

Esses blocos principais também estão sinalizados por comentários no código para facilitar a leitura e a manutenção.

1. **Extração e validação:** lê os quatro CSVs, confere o schema e valida códigos, datas e valores numéricos. Datas válidas são mantidas como `datetime.date` durante o processamento. `saldo` e `vendas_mes_ant` podem usar separador de milhar e terminar em `,00`, mas devem representar unidades inteiras; valores realmente fracionários são rejeitados. Ausências viram `None` e geram anomalias, sem serem presumidas como zero. Um registro sem código não pode ser associado a um produto e aparece somente nas anomalias.
2. **Transformação e consolidação:** agrupa os registros por produto, classifica cada saldo em uma única faixa de validade, soma por CD somente os lotes disponíveis, consolida as vendas e calcula a cobertura sobre o saldo disponível.
3. **Publicação:** gera `consolidado.csv` e `anomalias.csv`. Os arquivos são escritos e validados temporariamente antes de substituir as versões anteriores, evitando saídas parcialmente processadas.

## Saídas

- `consolidado.csv`: uma linha por produto, com saldos disponíveis por CD, `saldo_total`, vendas, cobertura e indicadores de incompletude. `saldo_vencido` não entra no disponível. `saldo_validade_pendente` reúne, uma única vez, saldos sem validade ou sem lote; `saldo_sem_lote` permanece como recorte informativo dessa pendência. As colunas `saldo_vence_ate_7_dias`, `saldo_vence_8_a_30_dias`, `saldo_vence_31_a_60_dias` e `saldo_vence_61_a_90_dias` são faixas exclusivas já incluídas no disponível. A data de referência é válida no próprio dia; somente datas anteriores são vencidas. `dados_incompletos` e `campos_incompletos` detalham ausências. Saldos e vendas são publicados como inteiros, sem `,00`;
- `anomalias.csv`: problemas técnicos e operacionais encontrados, acompanhados de gravidade e ação sugerida. Quando uma validade aparece na descrição da anomalia, ela é formatada como `DD/MM/AAAA`.

Para saldo negativo, a ação sugerida primeiro sinaliza as possibilidades de erro na última entrada de estoque ou falha na extração. Como o arquivo não contém o histórico de movimentações nem permite validar sua própria origem, essas hipóteses devem ser verificadas no WMS, sem assumir a causa. Se o saldo estiver correto, permanecem as opções de transferir estoque, dividir em dois envios, aguardar reabastecimento ou cancelar a venda.

Como CSV não possui um tipo nulo, valores `None` são publicados como campos vazios, e não como as strings `NaN` ou `NULL`.
O indicador considera somente ausência: códigos curtos, datas válidas em formato alternativo, saldos negativos e lotes vencidos continuam sendo anomalias, mas não tornam `dados_incompletos` verdadeiro.

## Execução

Na raiz do projeto:

```powershell
python sua-entrega/src/etl.py
```

Também é possível informar diretórios e data de referência:

```powershell
python sua-entrega/src/etl.py --input dados --output sua-entrega --reference-date 2026-08-20
```
