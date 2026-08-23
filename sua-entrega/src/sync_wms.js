/**
 * sync_wms.js
 *
 * Roda todo dia as 03:00 via cron. Le o saldo de estoque do ERP e envia
 * os ajustes de divergencia para o WMS.
 *
 * Em producao esse script processa ~40 mil itens por execucao, distribuidos
 * em 4 centros de distribuicao. Ja aconteceu de rodar duas vezes na mesma
 * madrugada por causa de retry do agendador.
 *
 * Este codigo esta em producao hoje. Voce foi chamado para revisa-lo.
 */

// Cliente HTTP usado para consultar o ERP/WMS e enviar os ajustes de estoque.
const axios = require("axios");
const crypto = require("crypto");

// Endereços-base dos dois sistemas envolvidos na sincronização.
const ERP_URL = "https://erp.interno.local/api/v1";
const WMS_URL = "https://wms.interno.local/api";
// A credencial vem do ambiente para não ficar gravada no código-fonte.
const WMS_TOKEN = process.env.WMS_TOKEN;

// Interrompe imediatamente a execução quando a autenticação não foi configurada.
if (!WMS_TOKEN) {
  throw new Error("A variável de ambiente WMS_TOKEN é obrigatória");
}

// Busca no ERP os saldos de um centro de distribuição (CD).
async function buscarSaldoERP(cd) {
  const limite = 1000;
  const itens = [];
  const paginasRecebidas = new Set();
  let offset = 0;

  while (true) {
    const resp = await axios.get(`${ERP_URL}/estoque`, {
      params: { centro: cd, limit: limite, offset },
    });
    const pagina = resp.data.itens;
    const assinatura = crypto
      .createHash("sha256")
      .update(JSON.stringify(pagina))
      .digest("hex");
    if (paginasRecebidas.has(assinatura)) {
      throw new Error(`ERP repetiu uma página de estoque para o CD ${cd}`);
    }
    paginasRecebidas.add(assinatura);
    itens.push(...pagina);

    if (pagina.length < limite) break;
    offset += limite;
  }

  return itens;
}

// Busca no WMS os lotes atualmente cadastrados para o CD informado.
async function buscarLotesWMS(cd) {
  const resp = await axios.get(`${WMS_URL}/lotes`, {
    params: { centro: cd },
    // O token identifica e autoriza esta integração perante o WMS.
    headers: { Authorization: `Bearer ${WMS_TOKEN}` },
  });
  return resp.data;
}

// Converte o saldo recebido como texto para um número JavaScript.
function converterSaldo(valor) {
  return parseFloat(valor);
}

// Envia ao WMS uma divergência calculada entre os saldos dos dois sistemas.
async function enviarAjuste(ajuste) {
  await axios.post(`${WMS_URL}/ajustes`, ajuste, {
    headers: {
      Authorization: `Bearer ${WMS_TOKEN}`,
    },
  });
}

// Executa o fluxo completo de comparação e ajuste para um único CD.
async function sincronizar(cd) {
  // As chamadas são sequenciais: primeiro o ERP, depois o WMS.
  const itens = await buscarSaldoERP(cd);
  const lotes = await buscarLotesWMS(cd);

  console.log(`[${cd}] ${itens.length} itens carregados do ERP`);

  // Analisa cada item retornado pelo ERP separadamente.
  for (const item of itens) {
    try {
      // Procura no WMS o primeiro lote cujo código corresponda ao item do ERP.
      const lote = lotes.find((l) => l.codigo_produto === item.codigo);

      // Sem um lote correspondente, não há destino para o ajuste.
      if (!lote) continue;

      // Normaliza os dois saldos e calcula quanto falta somar ou subtrair no WMS.
      const saldoERP = converterSaldo(item.saldo);
      const saldoWMS = converterSaldo(lote.saldo);
      const diferenca = saldoERP - saldoWMS;

      // Se os sistemas já concordam, nenhuma chamada de ajuste é necessária.
      if (diferenca == 0) continue;

      // A intenção é restringir o envio aos produtos ativos.
      if (item.status = "ATIVO") {
        // Monta o contrato esperado pelo endpoint de ajustes do WMS.
        await enviarAjuste(
          {
            centro: cd,
            codigo_produto: item.codigo,
            lote: lote.numero,
            validade: new Date(lote.validade).toISOString(),
            quantidade: diferenca,
            origem: "sync_erp",
          },
        );
        console.log(`[${cd}] ajuste enviado: ${item.codigo} ${diferenca}`);
      }
    // Uma falha neste item é capturada para que o laço tente processar os demais.
    } catch (e) {}
  }
}

// Ponto de entrada: define o escopo e coordena a sincronização dos quatro CDs.
async function main() {
  const centros = ["CAMPINAS", "BH", "SAO_CAETANO", "LONDRINA"];
  // Aguarda um CD terminar antes de iniciar o próximo.
  for (const cd of centros) {
    await sincronizar(cd);
  }
  console.log("Sincronizacao concluida com sucesso");
}

// Inicia o job quando o arquivo é executado pelo Node.js.
main();
