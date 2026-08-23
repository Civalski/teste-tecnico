from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from etl_core import (
    Anomaly,
    CD_FILES,
    ETLError,
    NULLABLE_FIELDS,
    REQUIRED_COLUMNS,
    StockRecord,
    anomalies_for_record,
    normalize_code,
    normalize_null,
    parse_brazilian_integer,
    parse_date,
)


def read_inputs(input_dir: Path, reference_date: date) -> tuple[list[StockRecord], list[Anomaly]]:
    records: list[StockRecord] = []
    anomalies: list[Anomaly] = []

    for cd, filename in CD_FILES.items():
        path = input_dir / filename
        if not path.is_file():
            raise ETLError(f"Arquivo obrigatório não encontrado: {path}")

        seen_rows: set[tuple[str, ...]] = set()
        date_formats: set[str] = set()
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter=";")
            if reader.fieldnames != list(REQUIRED_COLUMNS):
                raise ETLError(
                    f"{path}: colunas inválidas. Esperado {list(REQUIRED_COLUMNS)}, recebido {reader.fieldnames}"
                )

            for line_number, row in enumerate(reader, start=2):
                location = f"{path.name}, linha {line_number}"
                if None in row:
                    raise ETLError(f"{location}: quantidade de colunas inválida")

                values = {column: normalize_null(row[column]) for column in REQUIRED_COLUMNS}
                raw_tuple = tuple(values[column] or "" for column in REQUIRED_COLUMNS)
                if raw_tuple in seen_rows:
                    anomalies.append(
                        Anomaly(
                            cd,
                            values["codigo"] or "",
                            values["lote"] or "",
                            "Registro duplicado",
                            "alta",
                            "Investigar a origem da duplicidade e impedir a dupla contagem do saldo",
                        )
                    )
                    continue
                seen_rows.add(raw_tuple)

                original_code = values["codigo"]
                if original_code is None:
                    anomalies.append(
                        Anomaly(
                            cd,
                            "",
                            values["lote"] or "",
                            "Código ausente",
                            "alta",
                            "Corrigir o cadastro; o registro não pode ser consolidado sem "
                            "identificar o produto",
                        )
                    )
                    continue

                parsed_date = None
                if values["validade"] is not None:
                    parsed_date, date_format = parse_date(values["validade"], location)
                    date_formats.add(date_format)

                record = StockRecord(
                    cd=cd,
                    codigo=normalize_code(original_code, location),
                    codigo_original=original_code,
                    descricao=values["descricao"],
                    lote=values["lote"],
                    validade=parsed_date,
                    saldo=(
                        parse_brazilian_integer(values["saldo"], "saldo", location)
                        if values["saldo"] is not None
                        else None
                    ),
                    vendas_mes_ant=(
                        parse_brazilian_integer(
                            values["vendas_mes_ant"], "vendas_mes_ant", location
                        )
                        if values["vendas_mes_ant"] is not None
                        else None
                    ),
                )
                records.append(record)
                anomalies.extend(anomalies_for_record(record, reference_date))
                for field, label in NULLABLE_FIELDS:
                    if field == "lote":
                        continue
                    if values[field] is None:
                        anomalies.append(
                            Anomaly(
                                cd,
                                original_code,
                                values["lote"] or "",
                                label,
                                "alta",
                                "Corrigir a origem do dado; o consolidado considera apenas "
                                "os valores conhecidos",
                            )
                        )

        if "AAAA-MM-DD" in date_formats:
            anomalies.append(
                Anomaly(
                    cd,
                    "",
                    "",
                    "Formato de data divergente (AAAA-MM-DD)",
                    "baixa",
                    "Aceitar explicitamente os dois formatos no processamento e "
                    "padronizar a exportação do CD",
                )
            )

    return records, anomalies
