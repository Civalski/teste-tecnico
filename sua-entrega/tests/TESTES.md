# Documentação dos testes

A suíte usa `unittest` e verifica as regras críticas do ETL, desde a leitura dos campos até a geração dos CSVs finais.

## Como executar

Na raiz do projeto:

```powershell
python -m unittest discover -s sua-entrega/tests -v
```

## Parsing e normalização

- `test_normalize_null_markers`: confirma que campos vazios e marcadores como `NaN`, `NULL` e `N/A` viram `None`, preservando valores válidos. É importante para tratar ausências de forma consistente, sem confundi-las com texto real.
- `test_parse_brazilian_integer`: valida números inteiros no formato brasileiro, incluindo milhar, zero e saldo negativo. Evita totais errados por interpretação incorreta de ponto e vírgula.
- `test_fractional_and_invalid_numbers_fail`: rejeita unidades fracionárias e textos numéricos inválidos. Garante que dados incompatíveis com a regra de estoque falhem de forma explícita.
- `test_parse_supported_dates`: aceita os dois formatos de data previstos, padroniza a saída e rejeita datas inexistentes. Protege os cálculos de validade.
- `test_normalize_short_code`: completa códigos curtos com zeros à esquerda e rejeita códigos não numéricos. Mantém o agrupamento correto dos produtos.

## Consolidação e regras de negócio

- `test_description_sales_and_coverage`: verifica descrição canônica, soma dos saldos, vendas sem duplicação por lote e cálculo da cobertura. Protege os principais números do consolidado.
- `test_each_nullable_field_marks_product_as_incomplete`: confirma que a ausência de cada campo opcional sinaliza o produto e identifica campo e CD. Torna problemas de qualidade visíveis.
- `test_one_incomplete_record_marks_whole_product`: garante que um registro incompleto marque o produto consolidado inteiro. Evita que uma ausência seja ocultada pelo agrupamento.
- `test_divergent_sales_for_same_product_and_cd_fail`: interrompe o processamento quando o mesmo produto e CD possuem vendas divergentes. Impede uma escolha silenciosa que alteraria o total de vendas e a cobertura.
- `test_negative_balance_is_preserved_in_consolidation`: confirma que saldos negativos continuam nos saldos por CD e no total. Preserva o dado de origem para análise operacional.
- `test_negative_balance_generates_operational_options`: verifica a anomalia e as ações sugeridas para saldo negativo, sem assumir sua causa. Apoia uma decisão humana segura.
- `test_expiry_buckets_are_exclusive_and_only_eligible_stock_is_available`: testa os limites das faixas de validade e garante que estoque vencido, sem validade ou sem lote não entre no disponível. Evita dupla contagem e disponibilidade indevida.
- `test_integer_output_serialization_removes_decimal_suffix`: confirma que saldos e vendas são publicados como inteiros e que indicadores usam o formato esperado. Mantém o contrato dos CSVs de saída.
- `test_supported_input_dates_have_same_anomaly_output_format`: garante que os dois formatos aceitos na entrada produzam a mesma data padronizada nas anomalias. Mantém a saída consistente.

## Validação dos arquivos de entrada

- `test_exact_duplicate_is_removed_and_reported`: remove uma linha exatamente duplicada e registra a anomalia. Evita somar estoque e vendas duas vezes sem esconder o problema da origem.
- `test_missing_column_fails`: rejeita CSV sem as colunas obrigatórias. Evita processar um arquivo com schema incompatível.
- `test_invalid_number_fails`: rejeita texto em campo numérico. Impede que um valor inválido seja convertido ou tratado como zero silenciosamente.
- `test_fractional_balance_fails`: rejeita saldo com unidade fracionária durante a leitura do CSV. Aplica a regra de unidades inteiras também no fluxo completo de entrada.
- `test_invalid_date_fails`: rejeita uma data impossível no arquivo. Impede classificação incorreta de vencimento.
- `test_null_markers_become_none_and_known_values_are_preserved`: verifica nulos, valores válidos, anomalias e reflexos no consolidado. Garante que ausências sejam sinalizadas e excluídas apenas dos cálculos correspondentes.
- `test_missing_code_is_reported_but_not_consolidated`: registra a ausência do código, mas não associa o registro a um produto. Evita criar ou contaminar agrupamentos sem identificador confiável.

## Integração com os dados reais

- `test_real_files_generate_expected_outputs`: executa o ETL sobre os quatro arquivos de `dados/` e confere quantidades, totais, validade, saldo negativo e incompletude em produtos conhecidos. É a proteção final contra regressões que passem nos testes isolados, mas alterem a entrega real.
