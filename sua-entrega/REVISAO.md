# Revisão do `sync_wms.js`

Problemas ordenados pelo impacto no negócio. **Local** significa que pode ser reproduzido com APIs simuladas; **produção** depende do contrato ou do ambiente real.

## Problemas encontrados

| Gravidade | Problema e consequência prática às 3h de sábado | Detecção |
|---|---|---|
| Crítico | **Token exposto:** quem obtiver a credencial pode consultar ou alterar o WMS sem autorização. | Local; rotação em produção |
| Crítico | **Paginação ausente:** somente 1.000 de cerca de 40 mil itens seriam lidos; grande parte do estoque amanheceria desatualizada. | Local |
| Crítico | **Execução duplicada:** um retry pode repetir ajustes, deixar o saldo incorreto e liberar ou bloquear vendas indevidamente. | Local; confirmação em produção |
| Crítico | **Lote errado:** a busca considera apenas o produto e pode ajustar outro lote, comprometendo saldo, validade e separação. | Local |
| Crítico | **Atribuição no status:** `item.status = "ATIVO"` ativa o item durante a condição e permite ajustar produtos inativos. | Local |
| Alto | **Erros escondidos:** o `catch` vazio oculta rejeições e deixa parte do estoque sem sincronização ou alerta. | Local |
| Alto | **Sucesso incorreto:** após falhas ocultas, o job informa sucesso e adia a reação da equipe até clientes serem afetados. | Local |
| Alto | **Item sem lote ignorado:** a divergência permanece sem ajuste nem registro para investigação. | Local |
| Alto | **Saldo inválido:** `NaN` ou número brasileiro interpretado incorretamente pode gerar ajuste errado ou rejeitado. | Local |
| Alto | **Data inválida ou ambígua:** pode ajustar a validade errada ou perder o item silenciosamente. | Local |
| Alto | **Sem timeout:** uma API travada pode impedir o processamento dos CDs seguintes. | Local; limites reais em produção |
| Alto | **Respostas não validadas:** contratos incompletos podem interromper ou corromper o processamento sem diagnóstico claro. | Local |
| Alto | **Processamento sequencial:** cerca de 40 mil itens podem prolongar o job, aumentar dados defasados e sobrepor outra execução. | Local; capacidade real em produção |
| Médio | **Códigos sem normalização:** espaços, tipos diferentes ou zeros à esquerda podem impedir a associação ERP/WMS. | Local |
| Médio | **`main()` sem tratamento global:** uma falha encerra o job sem indicar claramente o CD e o progresso alcançado. | Local |

## Dois piores reescritos

1. **Token exposto:** a credencial foi removida do código e passou a ser lida da variável de ambiente `WMS_TOKEN`. O arquivo `.env.example` apenas documenta o nome esperado; o script não carrega arquivos `.env` diretamente. Em produção, ainda é necessário rotacionar o token antigo e removê-lo do histórico.
2. **Paginação:** o ERP é consultado em páginas de 1.000 itens com `limit` e `offset`; uma página repetida interrompe o job para evitar loop infinito. O contrato ainda precisa ser confirmado com a API real.

Os demais problemas foram apenas documentados, respeitando o limite do teste.

## O que pode ser testado aqui

Com `axios` simulado, é possível testar paginação, seleção de lote, status, dados inválidos e falhas. Sem os sistemas reais, não é possível confirmar o contrato de paginação, retry, timeout, autenticação ou rotação do token em produção.
