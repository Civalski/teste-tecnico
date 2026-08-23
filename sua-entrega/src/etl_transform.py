"""Consolidação dos registros e cálculo dos indicadores de estoque."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from etl_core import (
    Anomaly,
    CD_FILES,
    CD_SLUGS,
    ETLError,
    NULLABLE_FIELDS,
    REFERENCE_DATE,
    StockRecord,
    expiry_balance_column,
    normalize_description,
)


EXPIRY_BALANCE_COLUMNS = (
    "saldo_vencido",
    "saldo_vence_ate_7_dias",
    "saldo_vence_8_a_30_dias",
    "saldo_vence_31_a_60_dias",
    "saldo_vence_61_a_90_dias",
    "saldo_validade_pendente",
)
LOW_COVERAGE_THRESHOLD = Decimal("0.25")
CONSOLIDATED_COLUMNS = (
    "codigo",
    "descricao",
    "saldo_campinas",
    "saldo_bh",
    "saldo_sao_caetano",
    "saldo_londrina",
    "saldo_total",
    "saldo_sem_lote",
    *EXPIRY_BALANCE_COLUMNS,
    "vendas_mes_ant_total",
    "cobertura_meses",
    "dados_incompletos",
    "campos_incompletos",
)
INTEGER_OUTPUT_COLUMNS = (
    "saldo_campinas",
    "saldo_bh",
    "saldo_sao_caetano",
    "saldo_londrina",
    "saldo_total",
    "saldo_sem_lote",
    *EXPIRY_BALANCE_COLUMNS,
    "vendas_mes_ant_total",
)


def choose_description(records: Iterable[StockRecord]) -> str:
    """Escolhe a descrição normalizada mais frequente, com desempate estável."""
    descriptions = [record.descricao for record in records if record.descricao is not None]
    if not descriptions:
        return ""
    normalized_counts = Counter(normalize_description(value) for value in descriptions)
    winning_key = sorted(normalized_counts, key=lambda key: (-normalized_counts[key], key))[0]
    return winning_key


def consolidate(
    records: list[StockRecord],
    reference_date: date = REFERENCE_DATE,
) -> tuple[list[dict[str, str | int | bool]], list[Anomaly]]:
    """Agrupa por produto e produz saldos, vendas, cobertura e anomalias."""
    grouped: dict[str, list[StockRecord]] = defaultdict(list)
    for record in records:
        grouped[record.codigo].append(record)

    result: list[dict[str, str | int]] = []
    anomalies: list[Anomaly] = []
    for code in sorted(grouped):
        product_records = grouped[code]
        canonical_description = choose_description(product_records)
        reported_description_variants: set[tuple[str, str]] = set()
        for record in product_records:
            if record.descricao is None:
                continue
            normalized_description = normalize_description(record.descricao)
            variant_key = (record.cd, normalized_description)
            if (
                normalized_description == canonical_description
                or variant_key in reported_description_variants
            ):
                continue
            reported_description_variants.add(variant_key)
            anomalies.append(
                Anomaly(
                    record.cd,
                    code,
                    record.lote or "",
                    "Descrição divergente da descrição canônica",
                    "média",
                    "Validar o cadastro no ERP; descrição canônica usada no consolidado: "
                    f"{canonical_description}",
                )
            )
        incomplete_details = list(
            dict.fromkeys(
                f"{field} ({record.cd})"
                for record in product_records
                for field, _ in NULLABLE_FIELDS
                if getattr(record, field) is None
            )
        )
        has_incomplete_data = bool(incomplete_details)
        balances = {cd: 0 for cd in CD_FILES}
        balance_without_lot = 0
        expiry_balances = {column: 0 for column in EXPIRY_BALANCE_COLUMNS}
        expired_balances_by_cd = {cd: 0 for cd in CD_FILES}
        sales_by_cd: dict[str, set[int]] = defaultdict(set)
        for record in product_records:
            if record.saldo is not None:
                if record.lote is None:
                    balance_without_lot += record.saldo
                expiry_column = expiry_balance_column(record, reference_date)
                # Disponível: lote válido hoje ou com vencimento futuro conhecido.
                if expiry_column is None or expiry_column.startswith("saldo_vence_"):
                    balances[record.cd] += record.saldo
                if expiry_column is not None:
                    expiry_balances[expiry_column] += record.saldo
                if expiry_column == "saldo_vencido":
                    expired_balances_by_cd[record.cd] += record.saldo
            if record.vendas_mes_ant is not None:
                sales_by_cd[record.cd].add(record.vendas_mes_ant)

        sales_total = 0
        sales_values_by_cd: dict[str, int] = {}
        for cd in CD_FILES:
            values = sales_by_cd.get(cd, set())
            if not values:
                continue
            # Vendas repetidas por lote contam uma vez; divergências não são arbitradas.
            if len(values) != 1:
                raise ETLError(
                    f"Vendas divergentes para produto {code} no CD {cd}: {sorted(values)}"
                )
            sales_value = next(iter(values))
            sales_values_by_cd[cd] = sales_value
            sales_total += sales_value

        balance_total = sum(balances.values())
        coverage_ratio: Decimal | None = None
        if sales_total == 0:
            coverage = ""
            anomalies.append(
                Anomaly(
                    "",
                    code,
                    "",
                    "Venda total igual a zero; cobertura não calculável",
                    "baixa",
                    "Confirmar se o produto está inativo ou se houve falha na exportação de vendas",
                )
            )
        else:
            coverage_ratio = Decimal(balance_total) / Decimal(sales_total)
            coverage_value = coverage_ratio.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            coverage = format(coverage_value, ".2f")

        for cd in CD_FILES:
            sales_value = sales_values_by_cd.get(cd)
            if sales_value is None or sales_value <= 0:
                continue
            if balances[cd] == 0:
                anomalies.append(
                    Anomaly(
                        cd,
                        code,
                        "",
                        "Saldo disponível igual a zero no CD com vendas",
                        "alta",
                        "Verificar o estoque pendente e decidir entre corrigir a "
                        "rastreabilidade, reabastecer, transferir estoque ou ajustar o "
                        "atendimento; o ETL não movimenta saldo automaticamente",
                    )
                )
            if expired_balances_by_cd[cd] > 0:
                anomalies.append(
                    Anomaly(
                        cd,
                        code,
                        "",
                        "Estoque vencido no CD com vendas recentes do produto",
                        "alta",
                        "Consultar no WMS o histórico de movimentações por lote; as vendas "
                        "do produto no CD não comprovam a saída do lote vencido",
                    )
                )

        if coverage_ratio is not None and coverage_ratio <= LOW_COVERAGE_THRESHOLD:
            anomalies.append(
                Anomaly(
                    "",
                    code,
                    "",
                    "Cobertura de estoque igual ou inferior a 0,25 mês",
                    "alta",
                    f"Cobertura calculada: {coverage} mês. Avaliar reabastecimento, transferência "
                    "de estoque ou ajuste do atendimento; nenhuma movimentação é automática",
                )
            )

        row: dict[str, str | int | bool] = {
            "codigo": code,
            "descricao": canonical_description,
        }
        for cd in CD_FILES:
            row[f"saldo_{CD_SLUGS[cd]}"] = balances[cd]
        row.update(
            {
                "saldo_total": balance_total,
                "saldo_sem_lote": balance_without_lot,
                **expiry_balances,
                "vendas_mes_ant_total": sales_total,
                "cobertura_meses": coverage,
                "dados_incompletos": has_incomplete_data,
                "campos_incompletos": " | ".join(incomplete_details),
            }
        )
        result.append(row)

    return result, anomalies
