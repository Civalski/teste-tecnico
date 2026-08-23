# Entrega — consolidação de estoque

## Como executar

Na raiz do projeto, com Python 3.11 ou superior:

```powershell
python sua-entrega/src/etl.py
```

O comando lê os quatro CSVs de `dados/` e recria `consolidado.csv` e
`anomalias.csv` nesta pasta. O ETL não possui dependências externas.

Para informar caminhos ou outra data de referência:

```powershell
python sua-entrega/src/etl.py --input dados --output sua-entrega --reference-date 2026-08-20
```

## Como testar

```powershell
python -m unittest discover -s sua-entrega/tests -v
```

## Documentação

- `DECISOES.md`: análise e decisões originais do candidato;
- `ETL.md`: regras de entrada, transformação e saída;
- `REVISAO.md`: revisão do cliente de sincronização WMS;
- `tests/TESTES.md`: descrição dos testes automatizados.

O saldo disponível exclui lotes vencidos, sem lote ou com validade ausente. Esses
valores continuam visíveis em colunas próprias, e as divergências técnicas ou
operacionais são registradas em `anomalias.csv`. O relatório também sinaliza
cobertura global de até `0,25` mês, saldo disponível zerado em CD com vendas e a
coexistência de estoque vencido com vendas do produto no mesmo CD. Esse último
alerta exige investigação por lote no WMS e não comprova venda de item vencido.
