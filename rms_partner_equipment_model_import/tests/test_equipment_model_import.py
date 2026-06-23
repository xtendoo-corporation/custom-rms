import base64
import io

from openpyxl import Workbook

from odoo.tests.common import TransactionCase


class TestEquipmentModelImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.partner"].create(
            {
                "name": "VITEL, S.A.",
                "is_company": True,
            }
        )

    def _xlsx(self, rows, headers=None, preamble=None):
        workbook = Workbook()
        sheet = workbook.active
        for row in preamble or []:
            sheet.append(row)
        sheet.append(
            headers
            or ["Account Lookup: Account Name", "Model: Model Name"]
        )
        for row in rows:
            sheet.append(row)
        stream = io.BytesIO()
        workbook.save(stream)
        return base64.b64encode(stream.getvalue())

    def _run_import(self, rows, headers=None, preamble=None):
        wizard = self.env["equipment.model.import.wizard"].create(
            {
                "excel_file": self._xlsx(
                    rows, headers=headers, preamble=preamble
                ),
                "filename": "equipos.xlsx",
            }
        )
        action = wizard.action_import()
        return self.env["equipment.model.import.history"].browse(action["res_id"])

    def test_import_normalizes_names_and_avoids_duplicates(self):
        history = self._run_import(
            [
                ("  vitel,   s.a.  ", "GALAXY 816"),
                ("VITEL, S.A.", " galaxy   816 "),
                ("VITEL, S.A.", "ULTRA-X20"),
            ]
        )

        self.assertEqual(history.state, "done")
        self.assertEqual(history.company_found_count, 1)
        self.assertEqual(history.model_created_count, 2)
        self.assertEqual(history.association_created_count, 2)
        self.assertEqual(history.association_existing_count, 1)
        self.assertEqual(len(self.company.equipment_model_tag_ids), 2)

    def test_missing_and_ambiguous_companies_are_not_modified(self):
        self.env["res.partner"].create(
            {
                "name": " VITEL, S.A. ",
                "is_company": True,
            }
        )
        history = self._run_import(
            [
                ("VITEL, S.A.", "AMBIGUOUS"),
                ("NO EXISTE, S.L.", "UNKNOWN"),
                ("", "INCOMPLETE"),
            ]
        )

        self.assertEqual(history.company_not_found_count, 1)
        self.assertEqual(history.error_count, 2)
        self.assertEqual(history.model_created_count, 0)
        self.assertFalse(
            self.env["equipment.model.tag"].search(
                [("normalized_name", "in", ["ambiguous", "unknown", "incomplete"])]
            )
        )

    def test_headers_allow_spacing_case_and_previous_title_rows(self):
        history = self._run_import(
            [("VITEL, S.A.", "GALAXY 816")],
            headers=[
                "\ufeff account   lookup: account\nname ",
                " MODEL: MODEL NAME ",
            ],
            preamble=[("Informe de modelos instalados",), ()],
        )

        self.assertEqual(history.state, "done")
        self.assertEqual(history.association_created_count, 1)

    def test_missing_columns_create_failed_history(self):
        history = self._run_import(
            [("VITEL, S.A.", "GALAXY 816")],
            headers=["Empresa", "Modelo"],
        )

        self.assertEqual(history.state, "failed")
        self.assertEqual(history.error_count, 1)
        self.assertIn(
            "No se encontraron las columnas obligatorias", history.log_text
        )
