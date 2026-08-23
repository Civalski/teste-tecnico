from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from etl_core import (
    Anomaly,
    CD_FILES,
    CD_SLUGS,
    DATE_OUTPUT_FORMAT,
    ETLError,
    NULLABLE_FIELDS,
    NULL_MARKERS,
    NUMBER_PATTERN,
    REFERENCE_DATE,
    REQUIRED_COLUMNS,
    StockRecord,
    anomalies_for_record as _anomalies_for_record,
    expiry_balance_column,
    format_date,
    normalize_code,
    normalize_description,
    normalize_null,
    parse_brazilian_integer,
    parse_date,
)
from etl_input import read_inputs
from etl_output import ANOMALY_COLUMNS, publish_outputs, serialize_consolidated_rows
from etl_transform import (
    CONSOLIDATED_COLUMNS,
    EXPIRY_BALANCE_COLUMNS,
    INTEGER_OUTPUT_COLUMNS,
    choose_description,
    consolidate,
)


def run(input_dir: Path, output_dir: Path, reference_date: date) -> tuple[int, int]:
    records, input_anomalies = read_inputs(input_dir, reference_date)
    consolidated_rows, consolidation_anomalies = consolidate(records, reference_date)
    anomalies = input_anomalies + consolidation_anomalies
    publish_outputs(output_dir, consolidated_rows, anomalies)
    return len(consolidated_rows), len(anomalies)


def build_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Consolida exportações de estoque dos quatro CDs.")
    parser.add_argument("--input", type=Path, default=project_root / "dados")
    parser.add_argument("--output", type=Path, default=project_root / "sua-entrega")
    parser.add_argument("--reference-date", type=date.fromisoformat, default=REFERENCE_DATE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        products, anomalies = run(args.input, args.output, args.reference_date)
    except (ETLError, OSError) as exc:
        print(f"ERRO: {exc}")
        return 1
    print(f"ETL concluído: {products} produtos e {anomalies} anomalias.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
