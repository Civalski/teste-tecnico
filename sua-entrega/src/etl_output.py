"""Serialização, validação e publicação segura dos CSVs finais."""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from etl_core import Anomaly, ETLError
from etl_transform import CONSOLIDATED_COLUMNS, INTEGER_OUTPUT_COLUMNS


ANOMALY_COLUMNS = ("cd", "codigo", "lote", "tipo", "gravidade", "acao_sugerida")


def serialize_consolidated_rows(
    rows: Iterable[dict[str, str | int | bool]],
) -> list[dict[str, str | int | bool]]:
    """Converte tipos internos para o contrato textual do CSV consolidado."""
    serialized_rows: list[dict[str, str | int | bool]] = []
    for row in rows:
        serialized = dict(row)
        for column in INTEGER_OUTPUT_COLUMNS:
            value = serialized[column]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ETLError(f"{column} deve ser inteiro na saída: {value!r}")
            serialized[column] = str(value)
        incomplete = serialized["dados_incompletos"]
        if not isinstance(incomplete, bool):
            raise ETLError(f"dados_incompletos deve ser booleano na saída: {incomplete!r}")
        serialized["dados_incompletos"] = str(incomplete).lower()
        serialized_rows.append(serialized)
    return serialized_rows


def _write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _validate_csv(path: Path, columns: tuple[str, ...]) -> None:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter=";")
        if reader.fieldnames != list(columns):
            raise ETLError(f"Saída temporária inválida: {path}")
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ETLError(f"Saída temporária inválida em {path}, linha {line_number}")


def publish_outputs(
    output_dir: Path,
    consolidated_rows: list[dict[str, str | int | bool]],
    anomalies: list[Anomaly],
) -> None:
    """Valida arquivos temporários antes de substituir as duas saídas finais."""
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[Path] = []
    try:
        for filename, columns, rows in (
            (
                "consolidado.csv",
                CONSOLIDATED_COLUMNS,
                serialize_consolidated_rows(consolidated_rows),
            ),
            ("anomalias.csv", ANOMALY_COLUMNS, [asdict(item) for item in anomalies]),
        ):
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{filename}.", suffix=".tmp", dir=output_dir
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            temporary_paths.append(temporary_path)
            _write_csv(temporary_path, columns, rows)
            _validate_csv(temporary_path, columns)

        # A substituição só começa depois que ambos os arquivos foram validados.
        for temporary_path, filename in zip(
            temporary_paths, ("consolidado.csv", "anomalias.csv"), strict=True
        ):
            os.replace(temporary_path, output_dir / filename)
        temporary_paths.clear()
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
