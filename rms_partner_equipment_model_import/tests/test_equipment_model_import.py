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

    def _wizard(self, rows, headers=None, preamble=None):
        return self.env["equipment.model.import.wizard"].create(
            {
                "excel_file": self._xlsx(
                    rows, headers=headers, preamble=preamble
                ),
                "filename": "equipos.xlsx",
            }
        )

    def _run_import(self, rows, headers=None, preamble=None):
        wizard = self._wizard(rows, headers=headers, preamble=preamble)
        wizard.action_preview()
        action = wizard.action_confirm_import()
        return self.env["equipment.model.import.history"].browse(action["res_id"])

    def test_preview_does_not_modify_data_until_confirmation(self):
        wizard = self._wizard([("vitel, s.a.", "galaxy 816")])

        action = wizard.action_preview()

        self.assertEqual(action["res_id"], wizard.id)
        self.assertEqual(wizard.state, "preview")
        self.assertIn("COMPROBACIÓN PREVIA", wizard.preview_log)
        self.assertFalse(
            self.env["equipment.model.tag"].search(
                [("normalized_name", "=", "galaxy 816")]
            )
        )
        self.assertFalse(self.company.equipment_model_tag_ids)

    def test_import_normalizes_names_and_avoids_duplicates(self):
        history = self._run_import(
            [
                ("  vitel,   s.a.  ", "GALAXY 816"),
                ("vitel, s.a.", " galaxy   816 "),
                ("VITEL, S.A.", "ULTRA-X20"),
            ]
        )

        self.assertEqual(history.state, "done")
        self.assertEqual(history.company_found_count, 1)
        self.assertEqual(history.model_created_count, 2)
        self.assertEqual(history.association_created_count, 2)
        self.assertEqual(history.association_existing_count, 1)
        self.assertEqual(len(self.company.equipment_model_tag_ids), 2)

    def test_existing_model_match_is_case_insensitive(self):
        existing_model = self.env["equipment.model.tag"].create(
            {"name": "Galaxy 816"}
        )

        history = self._run_import([("vitel, s.a.", "GALAXY 816")])

        self.assertEqual(history.model_created_count, 0)
        self.assertEqual(history.model_existing_count, 1)
        self.assertEqual(self.company.equipment_model_tag_ids, existing_model)

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

    def test_missing_columns_raise_user_error(self):
        wizard = self._wizard(
            [("VITEL, S.A.", "GALAXY 816")],
            headers=["Empresa", "Modelo"],
        )

        with self.assertRaisesRegex(Exception, "No se encontraron las columnas"):
            wizard.action_preview()
