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
    descriptions = [record.descricao for record in records if record.descricao is not None]
    if not descriptions:
        return ""
    normalized_counts = Counter(normalize_description(value) for value in descriptions)
    winning_key = sorted(normalized_counts, key=lambda key: (-normalized_counts[key], key))[0]
    representatives = Counter(
        value for value in descriptions if normalize_description(value) == winning_key
    )
    return sorted(representatives, key=lambda value: (-representatives[value], value))[0]


def consolidate(
    records: list[StockRecord],
    reference_date: date = REFERENCE_DATE,
) -> tuple[list[dict[str, str | int | bool]], list[Anomaly]]:
    grouped: dict[str, list[StockRecord]] = defaultdict(list)
    for record in records:
        grouped[record.codigo].append(record)

    result: list[dict[str, str | int]] = []
    anomalies: list[Anomaly] = []
    for code in sorted(grouped):
        product_records = grouped[code]
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
        sales_by_cd: dict[str, set[int]] = defaultdict(set)
        for record in product_records:
            if record.saldo is not None:
                if record.lote is None:
                    balance_without_lot += record.saldo
                expiry_column = expiry_balance_column(record, reference_date)
                if expiry_column is None or expiry_column.startswith("saldo_vence_"):
                    balances[record.cd] += record.saldo
                if expiry_column is not None:
                    expiry_balances[expiry_column] += record.saldo
            if record.vendas_mes_ant is not None:
                sales_by_cd[record.cd].add(record.vendas_mes_ant)

        sales_total = 0
        for cd, values in sales_by_cd.items():
            if len(values) != 1:
                raise ETLError(
                    f"Vendas divergentes para produto {code} no CD {cd}: {sorted(values)}"
                )
            sales_total += next(iter(values))

        balance_total = sum(balances.values())
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
            coverage_value = (Decimal(balance_total) / Decimal(sales_total)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            coverage = format(coverage_value, ".2f")

        row: dict[str, str | int | bool] = {
            "codigo": code,
            "descricao": choose_description(product_records),
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
