# Decisões técnicas

Este documento registra as perguntas, premissas e decisões adotadas durante a consolidação dos estoques. Na ausência de confirmação das regras de negócio, preservei os dados originais, sinalizei as anomalias e evitei realizar correções ou movimentações operacionais automaticamente.

**a) Perguntas.**

1. Existem produtos fracionados que justifiquem tratar saldo como número flutuante?
2. Como deve ser tratado saldo negativo?
3. É padrão começar com 0 o código ou há exceções?
4. Como tratar campos obrigatórios ausentes?
5. Qual descrição usar quando o mesmo código apresenta descrições diferentes entre CDs?

**b) Premissas.**

1. Não existem produtos fracionados; esses campos representam números inteiros apenas, e o decimal só acrescenta ruído.
2. Saldo negativo representa uma venda que precisa de uma ação: fazer transferência de estoque, dois envios, aguardar entrada de reabastecimento ou cancelar a venda. Também pode ser um erro gerado na entrada de estoque ou alguma falha durante a extração dos dados. Essas causas também são consideradas, mas faltam dados para tomar uma ação melhor.
3. É padrão o código ter sete números. O README.md instrui que obrigatoriamente devem ser sete dígitos, então incluir o zero faz parte da etapa de normalização do fluxo de ETL.
4. Para campos obrigatórios ausentes, não presumir zero nem fabricar informações: preservar os dados conhecidos, marcar o registro como incompleto e gerar uma anomalia.
5. Quando o mesmo código apresenta descrições diferentes, considero que o código do ERP identifica o produto. Escolho a descrição que tem maior recorrência, sem criar produtos separados, pois pequenas diferenças de descrição entre CDs não devem duplicar o estoque consolidado.

**Premissa adicional:** mantive todas as colunas obrigatórias solicitadas e acrescentei colunas de controle para saldos vencidos, sem lote, com validade pendente e próximos do vencimento. Essas colunas tornam os estoques indisponíveis ou críticos visíveis sem misturá-los ao saldo disponível.

**c) Anomalias.**

Comecei a ler os dados para compreender a estrutura. Identifiquei anomalias referentes à validade de produtos, falta de lote, códigos incompletos, valores nulos e saldos negativos. Como complemento, enviei para a IA fazer uma varredura mais avançada, e ela encontrou mais uma anomalia de formatação de data. Em situação real, seria necessário mascarar dados sensíveis antes de enviá-los à IA; como já estão mascarados, não vou incluir isso no fluxo que o script vai rodar.

Vou tratar as anomalias da seguinte forma:

### Valores nulos
Encontrei valores nulos somente em lotes, eles devem ser convertidos de NaN para None, é necessário fazer isso para evitar que o sistema entenda que NaN é um lote. Também vou criar uma coluna para registrar de forma separada as unidades de produtos sem lote. Embora só tenha dados vazios para lote nessa amostra de dados, vou aplicar a mesma lógica para qualquer coluna que tenha valores ausentes.

### Códigos incompletos
Acrescentei um zero à esquerda, seguindo o padrão dos outros produtos. Fiz isso para normalizar a estrutura e atender à exigência do README.md.

### Lotes vencidos
Comparei a validade dos lotes com a data da extração e encontrei dois lotes vencidos. Não incluí esses saldos no estoque disponível, mas preservei as quantidades em uma coluna separada. Também registrei uma anomalia de alta gravidade, pois esses produtos devem ser bloqueados e separados para descarte conforme o procedimento da empresa.

### Registros duplicados
Encontrei em BH duas linhas exatamente iguais para o mesmo produto e lote. Removi a repetição antes de somar os saldos para evitar uma contagem duplicada, mas registrei a anomalia porque a origem dessa duplicidade precisa ser investigada.

### Produtos próximos do vencimento
Comparei a validade dos lotes com a data da extração e encontrei produtos próximos do vencimento. Mantive esses produtos no saldo disponível porque ainda estão válidos, mas separei as quantidades por faixa de dias e registrei uma anomalia para priorizar a expedição ou transferência.

### Saldo negativo
Encontrei um saldo negativo no CD de Londrina. Preservei o valor no consolidado porque não tenho informações suficientes para corrigir ou transferir esse saldo automaticamente. Registrei uma anomalia de alta gravidade para verificar se houve erro na última entrada de estoque ou falha na extração. Caso o saldo esteja correto, será necessário transferir estoque, dividir em dois envios, aguardar o reabastecimento ou cancelar a venda.

### Formato de data divergente
Encontrei datas no formato `AAAA-MM-DD` em Londrina, diferente do formato usado nos outros arquivos. Aceitei os dois formatos para não perder registros válidos e normalizei a saída para `DD/MM/AAAA`. Também registrei uma anomalia para que a exportação do CD seja padronizada.

**d) Uso de IA.**
Usei somente o modelo GPT-5 Sol com low reasoning (na minha opinião, tem o melhor custo-benefício atualmente).

O script `etl.py` foi escrito inteiramente pela IA. Começou como um script simples de correção de erros da tabela, e fui acrescentando novas regras. A ideia é funcionar com mais dados em cenários reais; para evitar *overfitting*, as regras de formatação são gerais e servem para dados além da amostra. A documentação do `etl.py` está em `ETL.md` e foi mantida atualizada conforme as instruções do `AGENTS.md`. Eu não quis montar um harness muito avançado para trabalhar com agentes, pois seria *overengineering*, mas em um cenário real eu teria criado.

Tirei muitas dúvidas usando a IA como um assistente de padrões/convenções sobre problemas encontrados.

Usei a IA como ferramenta complementar para tentar encontrar mais anomalias. Em um cenário real, com um banco de dados grande, isso poderia sair caro e demorado; talvez seja viável como auditoria esporádica para aumentar o portfólio de regras usadas no pipeline de ETL.

Sobre erros da IA: ela listou os problemas encontrados no `sync_wms.js` e sugeriu que as duas prioridades de refatoração eram a ausência de idempotência e a atribuição no status. Eu discordei dessa decisão porque, na minha visão, um token secreto exposto é prioridade máxima, e a paginação limitada a 1.000 itens poderia extrair apenas uma parte muito pequena dos dados. O problema do retry também é crítico e já havia acontecido segundo o enunciado.

**e) Dívida e o que faria com mais uma semana**

### O que falta
1 - Corrigir o restante dos problemas encontrados no sync_wms.js - estão listados em REVISAO.md, foram corrigidos apenas 2 problemas.

2 - Possível venda de produto vencido: o lote L2311 de Dipirona consta como vencido no estoque, enquanto houve vendas do produto no mesmo CD. Os dados disponíveis não identificam o lote das saídas, portanto não comprovam a venda do lote vencido. É necessário confirmar no WMS o histórico de movimentações por lote. Enquanto ocorre a investigação, o lote deve permanecer bloqueado e deve ser preparado um plano de devolução ou recolhimento. Caso a venda seja confirmada, acionar os responsáveis e vendedores para contatar os clientes afetados conforme o procedimento sanitário da empresa.

3 - Validar o fluxo com ERP e WMS reais - confirmar paginação, autenticação, timeout, formato das respostas e comportamento de novas tentativas. Os testes locais não comprovam esses contratos em produção.

4 - Criar reconciliação de entrada e saída - comparar quantidade de arquivos/CDs esperados, registros lidos, descartados, duplicados e totais antes/depois da consolidação. Isso ajuda a detectar arquivo incompleto, CD ausente ou extração parcial sem depender apenas das anomalias individuais.

Resumo: existem questões em aberto sobre qual o comportamento padrão para diversas situações relacionadas às anomalias encontradas, as premissas devem ser confirmadas com o time. Também faltam informações que provavelmente estão no banco de dados, mas às quais não tenho acesso. Seria necessário coletar mais informações para confirmar alguns problemas. Por exemplo, o saldo negativo pode ser algum erro de entrada de estoque ou da extração, e esse dado de entrada de estoque não está disponível no teste.

### O que eu faria com mais uma semana
1. Definiria uma sprint e classificaria as prioridades para a próxima semana junto com pessoas do time mais engajadas nas demandas.
2. Solicitaria acesso a mais dados para otimizar o pipeline de ETL e também confirmar a causa de alguns problemas.
3. Consertaria o restante dos problemas do script de sincronização. Ainda há falhas críticas que não alterei, pois o README.md solicitou a correção de apenas duas (entendo que foi para avaliar meu senso de prioridade).
4. Criaria mais regras para tratar possíveis anomalias que poderiam ocorrer, mas que não apareceram nessa amostra.
5. Desenvolveria gatilhos de avisos para a área responsável. Exemplos: produto fora da validade deve notificar, via Jira, Trello, Slack ou qualquer plataforma semelhante, o responsável pelo estoque; estoque próximo de acabar deve notificar o setor de compras (a coluna `cobertura_meses` auxilia nisso); e produtos próximos do vencimento devem notificar o setor de marketing para campanhas promocionais. Existem outras opções de gatilhos, mas seria necessário compreender o que realmente falta e o que já existe.
6. Investigaria e planejaria a correção dos problemas na raiz, por exemplo, na entrada de estoque e no registro de produtos. Esses dois pontos podem estar permitindo que alguns problemas cheguem longe demais. Ainda seria necessário analisar se o problema não foi causado na extração dos dados.
