from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


# Configuração da entrada, formatos aceitos e campos esperados nos CSVs.
REFERENCE_DATE = date(2026, 8, 20)
DATE_OUTPUT_FORMAT = "%d/%m/%Y"
REQUIRED_COLUMNS = ("codigo", "descricao", "lote", "validade", "saldo", "vendas_mes_ant")
CD_FILES = {
    "Campinas": "estoque_campinas.csv",
    "BH": "estoque_bh.csv",
    "São Caetano": "estoque_sao_caetano.csv",
    "Londrina": "estoque_londrina.csv",
}
CD_SLUGS = {
    "Campinas": "campinas",
    "BH": "bh",
    "São Caetano": "sao_caetano",
    "Londrina": "londrina",
}
NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?$")
NULL_MARKERS = frozenset({"", "nan", "null", "none", "n/a", "na"})
NULLABLE_FIELDS = (
    ("descricao", "Descrição ausente"),
    ("lote", "Lote ausente"),
    ("validade", "Validade ausente"),
    ("saldo", "Saldo ausente"),
    ("vendas_mes_ant", "Vendas do mês anterior ausentes"),
)


class ETLError(ValueError):
    """Erro de entrada que impede gerar uma consolidação confiável."""


@dataclass(frozen=True)
class StockRecord:
    cd: str
    codigo: str
    codigo_original: str
    descricao: str | None
    lote: str | None
    validade: date | None
    saldo: int | None
    vendas_mes_ant: int | None


@dataclass(frozen=True)
class Anomaly:
    cd: str
    codigo: str
    lote: str
    tipo: str
    gravidade: str
    acao_sugerida: str


# Normalização e validação dos valores brutos recebidos do WMS.
def normalize_null(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    return None if value.casefold() in NULL_MARKERS else value


def parse_brazilian_integer(raw_value: str, field: str, location: str = "") -> int:
    value = raw_value.strip()
    if not NUMBER_PATTERN.fullmatch(value):
        raise ETLError(f"{location}: {field} inválido: {raw_value!r}")

    normalized = value.replace(".", "").replace(",", ".")
    try:
        decimal_value = Decimal(normalized)
    except InvalidOperation as exc:
        raise ETLError(f"{location}: {field} inválido: {raw_value!r}") from exc

    if decimal_value != decimal_value.to_integral_value():
        raise ETLError(f"{location}: {field} deve representar unidades inteiras: {raw_value!r}")
    return int(decimal_value)


def parse_date(raw_value: str, location: str = "") -> tuple[date, str]:
    value = raw_value.strip()
    for date_format, label in (("%d/%m/%Y", "DD/MM/AAAA"), ("%Y-%m-%d", "AAAA-MM-DD")):
        try:
            return datetime.strptime(value, date_format).date(), label
        except ValueError:
            pass
    raise ETLError(f"{location}: validade inválida: {raw_value!r}")


def format_date(value: date) -> str:
    return value.strftime(DATE_OUTPUT_FORMAT)


def expiry_balance_column(record: StockRecord, reference_date: date) -> str | None:
    """Classifica o saldo em uma única faixa de validade operacional."""
    if record.lote is None or record.validade is None:
        return "saldo_validade_pendente"

    days_to_expiry = (record.validade - reference_date).days
    if days_to_expiry < 0:
        return "saldo_vencido"
    if days_to_expiry <= 7:
        return "saldo_vence_ate_7_dias"
    if days_to_expiry <= 30:
        return "saldo_vence_8_a_30_dias"
    if days_to_expiry <= 60:
        return "saldo_vence_31_a_60_dias"
    if days_to_expiry <= 90:
        return "saldo_vence_61_a_90_dias"
    return None


def normalize_code(raw_value: str, location: str = "") -> str:
    value = raw_value.strip()
    if not value.isdigit():
        raise ETLError(f"{location}: codigo deve conter somente dígitos: {raw_value!r}")
    if len(value) > 7:
        raise ETLError(f"{location}: codigo possui mais de 7 dígitos: {raw_value!r}")
    return value.zfill(7)


def normalize_description(value: str) -> str:
    return " ".join(value.upper().split())


# Identificação das anomalias operacionais de cada registro válido.
def _anomalies_for_record(record: StockRecord, reference_date: date) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    if len(record.codigo_original) < 7:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                "Código com menos de 7 dígitos",
                "média",
                "Normalizar com zeros à esquerda e corrigir a exportação do CD",
            )
        )
    if record.lote is None:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                "",
                "Lote ausente",
                "alta",
                "Corrigir o cadastro e garantir a rastreabilidade antes de movimentar o estoque",
            )
        )
    if record.saldo is not None and record.saldo < 0:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                f"Saldo negativo ({record.saldo})",
                "alta",
                "Verificar possível erro na última entrada de estoque ou falha na extração; "
                "se o saldo estiver correto, "
                "transferir estoque, dividir em dois envios, aguardar reabastecimento ou cancelar a venda",
            )
        )
    if record.validade is None:
        return anomalies

    days_to_expiry = (record.validade - reference_date).days
    formatted_date = format_date(record.validade)
    if days_to_expiry < 0:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                f"Lote vencido em {formatted_date}",
                "alta",
                "Bloquear o lote e direcioná-lo para segregação e descarte conforme o procedimento operacional",
            )
        )
    elif days_to_expiry <= 7:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                f"Lote vence em até 7 dias ({formatted_date})",
                "alta",
                "Priorizar imediatamente a expedição ou a transferência do lote",
            )
        )
    elif days_to_expiry <= 30:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                f"Lote vence entre 8 e 30 dias ({formatted_date})",
                "média",
                "Priorizar a expedição ou a transferência do lote antes do vencimento",
            )
        )
    elif days_to_expiry <= 60:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                f"Lote vence entre 31 e 60 dias ({formatted_date})",
                "média",
                "Planejar a expedição do lote antes dos estoques com maior prazo",
            )
        )
    elif days_to_expiry <= 90:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo_original,
                record.lote or "",
                f"Lote vence entre 61 e 90 dias ({formatted_date})",
                "baixa",
                "Acompanhar o lote e planejar sua expedição antes do vencimento",
            )
        )
    return anomalies


def read_inputs(input_dir: Path, reference_date: date) -> tuple[list[StockRecord], list[Anomaly]]:
    # Extração dos quatro arquivos, eliminação de duplicatas e validação linha a linha.
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
                            "Corrigir o cadastro; o registro não pode ser consolidado sem identificar o produto",
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
                anomalies.extend(_anomalies_for_record(record, reference_date))
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
                                "Corrigir a origem do dado; o consolidado considera apenas os valores conhecidos",
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
                    "Aceitar explicitamente os dois formatos no processamento e padronizar a exportação do CD",
                )
            )

    return records, anomalies


def choose_description(records: Iterable[StockRecord]) -> str:
    descriptions = [record.descricao for record in records if record.descricao is not None]
    if not descriptions:
        return ""
    normalized_counts = Counter(normalize_description(value) for value in descriptions)
    winning_key = sorted(normalized_counts, key=lambda key: (-normalized_counts[key], key))[0]
    representatives = Counter(value for value in descriptions if normalize_description(value) == winning_key)
    return sorted(representatives, key=lambda value: (-representatives[value], value))[0]


def consolidate(
    records: list[StockRecord],
    reference_date: date = REFERENCE_DATE,
) -> tuple[list[dict[str, str | int | bool]], list[Anomaly]]:
    # Transformação: agrupa por produto e calcula saldos, vendas e cobertura.
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
ANOMALY_COLUMNS = ("cd", "codigo", "lote", "tipo", "gravidade", "acao_sugerida")


def serialize_consolidated_rows(
    rows: Iterable[dict[str, str | int | bool]],
) -> list[dict[str, str | int | bool]]:
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


# Escrita e validação das saídas antes da substituição atômica dos CSVs finais.
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

        for temporary_path, filename in zip(
            temporary_paths, ("consolidado.csv", "anomalias.csv"), strict=True
        ):
            os.replace(temporary_path, output_dir / filename)
        temporary_paths.clear()
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)


def run(input_dir: Path, output_dir: Path, reference_date: date) -> tuple[int, int]:
    # Orquestração do fluxo completo: extrair, consolidar e publicar.
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
