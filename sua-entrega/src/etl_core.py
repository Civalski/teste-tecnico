"""Tipos, configurações e regras elementares compartilhadas pelo ETL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


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


def normalize_null(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    return None if value.casefold() in NULL_MARKERS else value


def parse_brazilian_integer(raw_value: str, field: str, location: str = "") -> int:
    """Converte um número brasileiro, rejeitando unidades fracionárias."""
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
    """Aceita os dois formatos de data previstos e informa qual foi usado."""
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
    # Traços diferentes representam a mesma separação e não devem criar variantes.
    without_dashes = re.sub(r"[-‐‑‒–—―]+", " ", value.upper())
    return " ".join(without_dashes.split())


def anomalies_for_record(record: StockRecord, reference_date: date) -> list[Anomaly]:
    """Aplica alertas que dependem somente de um registro da origem."""
    anomalies: list[Anomaly] = []
    if len(record.codigo_original) < 7:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo,
                record.lote or "",
                "Código com menos de 7 dígitos",
                "média",
                f"Código recebido: {record.codigo_original}. Normalizar com zeros à esquerda "
                "e corrigir a exportação do CD",
            )
        )
    if record.lote is None:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo,
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
                record.codigo,
                record.lote or "",
                f"Saldo negativo ({record.saldo})",
                "alta",
                "Verificar possível erro na última entrada de estoque ou falha na extração; "
                "se o saldo estiver correto, transferir estoque, dividir em dois envios, "
                "aguardar reabastecimento ou cancelar a venda",
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
                record.codigo,
                record.lote or "",
                f"Lote vencido em {formatted_date}",
                "alta",
                "Bloquear o lote e direcioná-lo para segregação e descarte conforme o "
                "procedimento operacional",
            )
        )
    elif days_to_expiry <= 7:
        anomalies.append(
            Anomaly(
                record.cd,
                record.codigo,
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
                record.codigo,
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
                record.codigo,
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
                record.codigo,
                record.lote or "",
                f"Lote vence entre 61 e 90 dias ({formatted_date})",
                "baixa",
                "Acompanhar o lote e planejar sua expedição antes do vencimento",
            )
        )
    return anomalies
