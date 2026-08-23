import csv
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path


DELIVERY_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DELIVERY_DIR.parent
sys.path.insert(0, str(DELIVERY_DIR / "src"))

import etl  # noqa: E402


HEADER = "codigo;descricao;lote;validade;saldo;vendas_mes_ant\n"


class ParsingTests(unittest.TestCase):
    def test_normalize_null_markers(self):
        for value in (None, "", "  ", "NaN", "NULL", "None", "N/A", "na"):
            self.assertIsNone(etl.normalize_null(value))
        self.assertEqual(etl.normalize_null(" L2401 "), "L2401")

    def test_parse_brazilian_integer(self):
        self.assertEqual(etl.parse_brazilian_integer("1.250,00", "saldo"), 1250)
        self.assertEqual(etl.parse_brazilian_integer("-35,00", "saldo"), -35)
        self.assertEqual(etl.parse_brazilian_integer("0,00", "saldo"), 0)

    def test_fractional_and_invalid_numbers_fail(self):
        with self.assertRaises(etl.ETLError):
            etl.parse_brazilian_integer("1,50", "saldo")
        with self.assertRaises(etl.ETLError):
            etl.parse_brazilian_integer("1,2x", "saldo")

    def test_parse_supported_dates(self):
        self.assertEqual(etl.parse_date("20/08/2026"), (date(2026, 8, 20), "DD/MM/AAAA"))
        self.assertEqual(etl.parse_date("2026-08-20"), (date(2026, 8, 20), "AAAA-MM-DD"))
        self.assertEqual(etl.format_date(date(2026, 8, 20)), "20/08/2026")
        with self.assertRaises(etl.ETLError):
            etl.parse_date("31/02/2026")

    def test_normalize_short_code(self):
        self.assertEqual(etl.normalize_code("74500"), "0074500")
        self.assertEqual(etl.normalize_code("0074500"), "0074500")
        with self.assertRaises(etl.ETLError):
            etl.normalize_code("ABC")


class ConsolidationTests(unittest.TestCase):
    @staticmethod
    def record(cd, description, balance, sales):
        return etl.StockRecord(
            cd=cd,
            codigo="0000001",
            codigo_original="0000001",
            descricao=description,
            lote="L1",
            validade=date(2027, 1, 1),
            saldo=balance,
            vendas_mes_ant=sales,
        )

    def test_description_sales_and_coverage(self):
        records = [
            self.record("Campinas", "PRODUTO TESTE", 10, 20),
            self.record("Campinas", "PRODUTO TESTE", 5, 20),
            self.record("BH", "Produto alternativo", 5, 20),
        ]
        rows, anomalies = etl.consolidate(records)
        self.assertEqual(anomalies, [])
        self.assertEqual(rows[0]["descricao"], "PRODUTO TESTE")
        self.assertEqual(rows[0]["saldo_campinas"], 15)
        self.assertEqual(rows[0]["saldo_total"], 20)
        self.assertEqual(rows[0]["vendas_mes_ant_total"], 40)
        self.assertEqual(rows[0]["cobertura_meses"], "0.50")
        self.assertFalse(rows[0]["dados_incompletos"])
        self.assertEqual(rows[0]["campos_incompletos"], "")

    def test_description_is_normalized_to_uppercase_without_dashes(self):
        records = [self.record("Campinas", "protetor solar - fps 50", 10, 20)]

        rows, _ = etl.consolidate(records)

        self.assertEqual(rows[0]["descricao"], "PROTETOR SOLAR FPS 50")

    def test_each_nullable_field_marks_product_as_incomplete(self):
        complete = self.record("Campinas", "Produto", 10, 20)
        for field in ("descricao", "lote", "validade", "saldo", "vendas_mes_ant"):
            with self.subTest(field=field):
                rows, _ = etl.consolidate([replace(complete, **{field: None})])
                self.assertTrue(rows[0]["dados_incompletos"])
                self.assertEqual(rows[0]["campos_incompletos"], f"{field} (Campinas)")

    def test_one_incomplete_record_marks_whole_product(self):
        records = [
            self.record("Campinas", "Produto", 10, 20),
            replace(self.record("BH", "Produto", 5, 20), validade=None),
        ]

        rows, _ = etl.consolidate(records)

        self.assertTrue(rows[0]["dados_incompletos"])
        self.assertEqual(rows[0]["campos_incompletos"], "validade (BH)")

    def test_divergent_sales_for_same_product_and_cd_fail(self):
        records = [
            self.record("Campinas", "Produto", 10, 20),
            self.record("Campinas", "Produto", 5, 21),
        ]
        with self.assertRaises(etl.ETLError):
            etl.consolidate(records)

    def test_negative_balance_is_preserved_in_consolidation(self):
        records = [
            self.record("Londrina", "Produto", -35, 10),
            self.record("Campinas", "Produto", 0, 10),
            self.record("São Caetano", "Produto", 20, 10),
            self.record("BH", "Produto", 100, 10),
        ]

        rows, anomalies = etl.consolidate(records)

        self.assertEqual(rows[0]["saldo_londrina"], -35)
        self.assertEqual(rows[0]["saldo_sao_caetano"], 20)
        self.assertEqual(rows[0]["saldo_bh"], 100)
        self.assertEqual(rows[0]["saldo_total"], 85)
        self.assertEqual(anomalies, [])

    def test_negative_balance_generates_operational_options(self):
        record = self.record("Londrina", "Produto", -35, 10)

        anomalies = etl._anomalies_for_record(record, date(2026, 8, 20))

        self.assertEqual(anomalies[0].tipo, "Saldo negativo (-35)")
        self.assertEqual(
            anomalies[0].acao_sugerida,
            "Verificar possível erro na última entrada de estoque ou falha na extração; "
            "se o saldo estiver correto, "
            "transferir estoque, dividir em dois envios, aguardar reabastecimento ou cancelar a venda",
        )

    def test_expiry_buckets_are_exclusive_and_only_eligible_stock_is_available(self):
        reference_date = date(2026, 8, 20)
        records = [
            replace(self.record("Campinas", "Produto", 1, 100), validade=date(2026, 8, 19)),
            replace(self.record("Campinas", "Produto", 2, 100), validade=reference_date),
            replace(self.record("BH", "Produto", 3, 100), validade=date(2026, 8, 27)),
            replace(self.record("BH", "Produto", 5, 100), validade=date(2026, 8, 28)),
            replace(self.record("São Caetano", "Produto", 7, 100), validade=date(2026, 9, 19)),
            replace(self.record("São Caetano", "Produto", 11, 100), validade=date(2026, 9, 20)),
            replace(self.record("Londrina", "Produto", 13, 100), validade=date(2026, 10, 19)),
            replace(self.record("Londrina", "Produto", 17, 100), validade=date(2026, 10, 20)),
            replace(self.record("Campinas", "Produto", 19, 100), validade=date(2026, 11, 18)),
            replace(self.record("BH", "Produto", 23, 100), validade=date(2026, 11, 19)),
            replace(self.record("BH", "Produto", 29, 100), validade=None),
            replace(self.record("Campinas", "Produto", 31, 100), lote=None),
            replace(
                self.record("Campinas", "Produto", 37, 100),
                lote=None,
                validade=None,
            ),
        ]

        rows, _ = etl.consolidate(records, reference_date)
        row = rows[0]

        self.assertEqual(row["saldo_vencido"], 1)
        self.assertEqual(row["saldo_vence_ate_7_dias"], 5)
        self.assertEqual(row["saldo_vence_8_a_30_dias"], 12)
        self.assertEqual(row["saldo_vence_31_a_60_dias"], 24)
        self.assertEqual(row["saldo_vence_61_a_90_dias"], 36)
        self.assertEqual(row["saldo_validade_pendente"], 97)
        self.assertEqual(row["saldo_sem_lote"], 68)
        self.assertEqual(row["saldo_total"], 100)
        self.assertEqual(row["saldo_campinas"], 21)
        self.assertEqual(row["saldo_bh"], 31)
        self.assertEqual(row["saldo_sao_caetano"], 18)
        self.assertEqual(row["saldo_londrina"], 30)
        self.assertEqual(row["cobertura_meses"], "0.25")

    def test_integer_output_serialization_removes_decimal_suffix(self):
        row = {
            "codigo": "0000001",
            "descricao": "Produto",
            "saldo_campinas": etl.parse_brazilian_integer("0,00", "saldo"),
            "saldo_bh": etl.parse_brazilian_integer("640,00", "saldo"),
            "saldo_sao_caetano": etl.parse_brazilian_integer("1.250,00", "saldo"),
            "saldo_londrina": etl.parse_brazilian_integer("-35,00", "saldo"),
            "saldo_total": 1855,
            "saldo_sem_lote": 0,
            "saldo_vencido": 0,
            "saldo_vence_ate_7_dias": 0,
            "saldo_vence_8_a_30_dias": 0,
            "saldo_vence_31_a_60_dias": 0,
            "saldo_vence_61_a_90_dias": 0,
            "saldo_validade_pendente": 0,
            "vendas_mes_ant_total": etl.parse_brazilian_integer(
                "1.250,00", "vendas_mes_ant"
            ),
            "cobertura_meses": "1.48",
            "dados_incompletos": False,
            "campos_incompletos": "",
        }

        serialized = etl.serialize_consolidated_rows([row])[0]

        self.assertEqual(serialized["saldo_campinas"], "0")
        self.assertEqual(serialized["saldo_bh"], "640")
        self.assertEqual(serialized["saldo_sao_caetano"], "1250")
        self.assertEqual(serialized["saldo_londrina"], "-35")
        self.assertEqual(serialized["saldo_sem_lote"], "0")
        self.assertEqual(serialized["vendas_mes_ant_total"], "1250")
        self.assertEqual(serialized["dados_incompletos"], "false")
        self.assertEqual(serialized["campos_incompletos"], "")

    def test_supported_input_dates_have_same_anomaly_output_format(self):
        anomaly_types = []
        for raw_date in ("31/08/2026", "2026-08-31"):
            parsed_date, _ = etl.parse_date(raw_date)
            record = self.record("Campinas", "Produto", 10, 20)
            record = etl.StockRecord(
                **{**record.__dict__, "validade": parsed_date}
            )
            anomaly_types.append(
                etl._anomalies_for_record(record, date(2026, 8, 20))[0].tipo
            )

        self.assertEqual(
            anomaly_types,
            [
                "Lote vence entre 8 e 30 dias (31/08/2026)",
                "Lote vence entre 8 e 30 dias (31/08/2026)",
            ],
        )


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.input_dir = Path(self.temp_dir.name)
        for index, filename in enumerate(etl.CD_FILES.values(), start=1):
            code = f"{index:07d}"
            (self.input_dir / filename).write_text(
                HEADER + f"{code};PRODUTO {index};L1;31/12/2027;10,00;5,00\n",
                encoding="utf-8",
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_duplicate_is_removed_and_reported(self):
        path = self.input_dir / "estoque_bh.csv"
        original = path.read_text(encoding="utf-8")
        data_row = original.splitlines()[1]
        path.write_text(original + data_row + "\n", encoding="utf-8")
        records, anomalies = etl.read_inputs(self.input_dir, date(2026, 8, 20))
        self.assertEqual(len(records), 4)
        self.assertEqual([item.tipo for item in anomalies], ["Registro duplicado"])

    def test_missing_column_fails(self):
        path = self.input_dir / "estoque_bh.csv"
        path.write_text("codigo;descricao\n0000001;PRODUTO\n", encoding="utf-8")
        with self.assertRaises(etl.ETLError):
            etl.read_inputs(self.input_dir, date(2026, 8, 20))

    def test_invalid_number_fails(self):
        path = self.input_dir / "estoque_bh.csv"
        path.write_text(
            HEADER + "0000001;PRODUTO;L1;31/12/2027;dez;5,00\n", encoding="utf-8"
        )
        with self.assertRaises(etl.ETLError):
            etl.read_inputs(self.input_dir, date(2026, 8, 20))

    def test_fractional_balance_fails(self):
        path = self.input_dir / "estoque_bh.csv"
        path.write_text(
            HEADER + "0000001;PRODUTO;L1;31/12/2027;1,50;5,00\n", encoding="utf-8"
        )
        with self.assertRaises(etl.ETLError):
            etl.read_inputs(self.input_dir, date(2026, 8, 20))

    def test_invalid_date_fails(self):
        path = self.input_dir / "estoque_bh.csv"
        path.write_text(
            HEADER + "0000001;PRODUTO;L1;31/02/2027;10,00;5,00\n", encoding="utf-8"
        )
        with self.assertRaises(etl.ETLError):
            etl.read_inputs(self.input_dir, date(2026, 8, 20))

    def test_null_markers_become_none_and_known_values_are_preserved(self):
        path = self.input_dir / "estoque_bh.csv"
        path.write_text(
            HEADER
            + "0099999;NULL;NaN;N/A;100,00;NULL\n"
            + "0099999;PRODUTO;L2;31/12/2027;NaN;20,00\n",
            encoding="utf-8",
        )

        records, anomalies = etl.read_inputs(self.input_dir, date(2026, 8, 20))
        bh_records = [record for record in records if record.cd == "BH"]
        self.assertIsNone(bh_records[0].descricao)
        self.assertIsNone(bh_records[0].lote)
        self.assertIsNone(bh_records[0].validade)
        self.assertIsNone(bh_records[0].vendas_mes_ant)
        self.assertIsNone(bh_records[1].saldo)
        self.assertIsInstance(bh_records[1].validade, date)
        self.assertIn("Lote ausente", [item.tipo for item in anomalies])
        self.assertIn("Saldo ausente", [item.tipo for item in anomalies])

        rows, _ = etl.consolidate(records)
        row = next(item for item in rows if item["codigo"] == "0099999")
        self.assertEqual(row["saldo_bh"], 0)
        self.assertEqual(row["saldo_sem_lote"], 100)
        self.assertEqual(row["saldo_validade_pendente"], 100)
        self.assertEqual(row["saldo_total"], 0)
        self.assertEqual(row["vendas_mes_ant_total"], 20)
        self.assertTrue(row["dados_incompletos"])
        self.assertEqual(
            row["campos_incompletos"],
            "descricao (BH) | lote (BH) | validade (BH) | vendas_mes_ant (BH) | saldo (BH)",
        )

    def test_missing_code_is_reported_but_not_consolidated(self):
        path = self.input_dir / "estoque_bh.csv"
        path.write_text(
            HEADER + "NaN;PRODUTO;L1;31/12/2027;10,00;5,00\n",
            encoding="utf-8",
        )

        records, anomalies = etl.read_inputs(self.input_dir, date(2026, 8, 20))

        self.assertFalse(any(record.cd == "BH" for record in records))
        self.assertIn("Código ausente", [item.tipo for item in anomalies])


class RealDataIntegrationTests(unittest.TestCase):
    def test_real_files_generate_expected_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            products, anomalies = etl.run(
                PROJECT_ROOT / "dados", Path(temp_dir), date(2026, 8, 20)
            )
            self.assertEqual(products, 10)
            self.assertEqual(anomalies, 14)

            with (Path(temp_dir) / "consolidado.csv").open(
                encoding="utf-8", newline=""
            ) as source:
                rows = {row["codigo"]: row for row in csv.DictReader(source, delimiter=";")}

            self.assertEqual(rows["0074500"]["saldo_bh"], "850")
            self.assertEqual(rows["0074500"]["saldo_total"], "3605")
            self.assertEqual(rows["0074500"]["saldo_vencido"], "90")
            self.assertEqual(rows["0074500"]["cobertura_meses"], "0.36")
            self.assertEqual(rows["0074500"]["vendas_mes_ant_total"], "9990")
            self.assertTrue(
                all(
                    row["descricao"] == row["descricao"].upper()
                    and "-" not in row["descricao"]
                    for row in rows.values()
                )
            )
            self.assertEqual(rows["0067890"]["saldo_londrina"], "-35")
            self.assertEqual(rows["0067890"]["saldo_bh"], "550")
            self.assertEqual(rows["0067890"]["saldo_total"], "515")
            self.assertEqual(rows["0102440"]["saldo_sem_lote"], "610")
            self.assertEqual(rows["0102440"]["saldo_validade_pendente"], "610")
            self.assertEqual(rows["0102440"]["saldo_vencido"], "45")
            self.assertEqual(rows["0102440"]["saldo_total"], "520")
            self.assertEqual(rows["0102440"]["dados_incompletos"], "true")
            self.assertEqual(rows["0102440"]["campos_incompletos"], "lote (Campinas)")
            self.assertEqual(rows["0067890"]["dados_incompletos"], "false")
            self.assertEqual(rows["0067890"]["campos_incompletos"], "")


if __name__ == "__main__":
    unittest.main()
