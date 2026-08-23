# Revisão do `sync_wms.js`

Problemas ordenados pelo impacto no negócio. **Local** significa que pode ser reproduzido com APIs simuladas; **produção** depende do contrato ou do ambiente real.

## Problemas encontrados

### Token exposto

- **Gravidade: Crítico**
- **Problema e consequência prática às 3h de sábado:** quem obtiver a credencial pode consultar ou alterar o WMS sem autorização.
- **Detecção:** local; rotação em produção.

### Paginação ausente no ERP original

- **Gravidade: Crítico**
- **Problema e consequência prática às 3h de sábado:** somente 1.000 de cerca de 40 mil itens seriam lidos; grande parte do estoque amanheceria desatualizada.
- **Detecção:** local.
- **Risco relacionado no WMS:** `buscarLotesWMS` faz uma única requisição. Isso somente caracteriza paginação ausente se o endpoint `/lotes` for paginado ou limitar a resposta; o contrato precisa ser confirmado antes de alterar o código.

### Execução duplicada

- **Gravidade: Crítico**
- **Problema e consequência prática às 3h de sábado:** um retry pode repetir ajustes, deixar o saldo incorreto e liberar ou bloquear vendas indevidamente.
- **Detecção:** local; confirmação em produção.

### Lote errado

- **Gravidade: Crítico**
- **Problema e consequência prática às 3h de sábado:** a busca considera apenas o produto e pode ajustar outro lote, comprometendo saldo, validade e separação.
- **Detecção:** local.

### Atribuição no status

- **Gravidade: Crítico**
- **Problema e consequência prática às 3h de sábado:** `item.status = "ATIVO"` ativa o item durante a condição e permite ajustar produtos inativos.
- **Detecção:** local.

### Erros escondidos

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** o `catch` vazio oculta rejeições e deixa parte do estoque sem sincronização ou alerta.
- **Detecção:** local.

### Sucesso incorreto

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** após falhas ocultas, o job informa sucesso e adia a reação da equipe até clientes serem afetados.
- **Detecção:** local.

### Item sem lote ignorado

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** a divergência permanece sem ajuste nem registro para investigação.
- **Detecção:** local.

### Saldo inválido

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** `NaN` ou número brasileiro interpretado incorretamente pode gerar ajuste errado ou rejeitado.
- **Observação:** a comparação ocorre depois de uma subtração, portanto apenas trocar `==` por `===` não trataria `NaN`; a correção funcional exigiria validar os saldos com `Number.isFinite` antes do envio.
- **Detecção:** local.

### Data inválida ou ambígua

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** pode ajustar a validade errada ou perder o item silenciosamente.
- **Detecção:** local.

### Sem timeout

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** uma API travada pode impedir o processamento dos CDs seguintes.
- **Detecção:** local; limites reais em produção.

### Respostas não validadas

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** contratos incompletos podem interromper ou corromper o processamento sem diagnóstico claro.
- **Detecção:** local.

### Processamento sequencial

- **Gravidade: Alto**
- **Problema e consequência prática às 3h de sábado:** cerca de 40 mil itens podem prolongar o job, aumentar dados defasados e sobrepor outra execução.
- **Detecção:** local; capacidade real em produção.

### Códigos sem normalização

- **Gravidade: Médio**
- **Problema e consequência prática às 3h de sábado:** espaços, tipos diferentes ou zeros à esquerda podem impedir a associação ERP/WMS.
- **Detecção:** local.

### `main()` sem tratamento global

- **Gravidade: Médio**
- **Problema e consequência prática às 3h de sábado:** uma falha encerra o job sem indicar claramente o CD e o progresso alcançado.
- **Detecção:** local.

## Dois piores reescritos

1. **Token exposto:** a credencial foi removida do código e passou a ser lida da variável de ambiente `WMS_TOKEN`. O arquivo `.env.example` apenas documenta o nome esperado; o script não carrega arquivos `.env` diretamente. Em produção, ainda é necessário rotacionar o token antigo e removê-lo do histórico.
2. **Paginação:** o ERP é consultado em páginas de 1.000 itens com `limit` e `offset`; uma página repetida interrompe o job para evitar loop infinito. O contrato ainda precisa ser confirmado com a API real.

Os demais problemas foram apenas documentados, respeitando o limite do teste.

## Evidências e limites da revisão

Foi validado localmente que o arquivo possui sintaxe JavaScript válida com
`node --check`. A leitura do código também permite identificar os defeitos que
independem do contrato das APIs, como atribuição no `status`, `catch` vazio e
busca do primeiro lote apenas pelo produto.

Ainda seria necessário simular as respostas do ERP e do WMS para verificar se o código:

- busca todas as páginas de produtos;
- escolhe o lote correto;
- trata corretamente o status e os dados inválidos;
- informa quando ocorre uma falha.

Essas simulações não fazem parte da entrega atual. Mesmo depois delas, somente um teste com o ERP e o WMS reais pode confirmar como essas APIs funcionam na prática, incluindo paginação, novas tentativas após falhas (`retry`), tempo máximo de espera (`timeout`), autenticação e troca do token de acesso.
