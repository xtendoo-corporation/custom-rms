import base64
import io
import logging
import re
from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.equipment_model_tag import normalize_name

try:
    import openpyxl
except ImportError:
    openpyxl = None


_logger = logging.getLogger(__name__)

COMPANY_COLUMN = "Account Lookup: Account Name"
MODEL_COLUMN = "Model: Model Name"
HEADER_SCAN_LIMIT = 20
LEGAL_COMPANY_WORDS = {
    "s",
    "l",
    "sl",
    "slu",
    "sll",
    "srl",
    "a",
    "sa",
    "sau",
    "sc",
    "scp",
    "cb",
    "coop",
    "cooperativa",
    "sociedad",
    "limitada",
    "anonima",
}


class EquipmentModelImportWizard(models.TransientModel):
    _name = "equipment.model.import.wizard"
    _description = "Importar Equipos del Cliente por compañía"

    excel_file = fields.Binary(string="Archivo Excel", required=True)
    filename = fields.Char(string="Nombre del archivo", required=True)
    state = fields.Selection(
        selection=[("upload", "Archivo"), ("preview", "Comprobación")],
        default="upload",
        required=True,
    )
    preview_log = fields.Text(string="Comprobación", readonly=True)
    preview_line_ids = fields.One2many(
        comodel_name="equipment.model.import.preview.line",
        inverse_name="wizard_id",
        string="Empresas con varias candidatas",
    )

    def action_import(self):
        return self.action_preview()

    def action_preview(self):
        self.ensure_one()
        self._check_admin_access()
        try:
            rows, company_index, model_index, header_row_number = self._read_import_rows()
            log_text, values, preview_lines = self._process_rows(
                rows,
                company_index,
                model_index,
                start_row=header_row_number + 1,
                dry_run=True,
            )
        except UserError:
            raise
        except Exception as error:
            _logger.exception("Error reading equipment model import file")
            raise UserError(
                _("No se ha podido leer el archivo Excel: %s") % error
            ) from error

        self.write({
            "state": "preview",
            "preview_log": log_text,
            "preview_line_ids": [(5, 0, 0)] + preview_lines,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Comprobar importación"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_confirm_import(self):
        self.ensure_one()
        self._check_admin_access()
        if self.state != "preview":
            raise UserError(_("Primero debes comprobar el archivo antes de importarlo."))
        missing_selection_lines = self.preview_line_ids.filtered(
            lambda line: not line.skip_import and not line.selected_partner_id
        )
        if missing_selection_lines:
            raise UserError(
                _(
                    "Debes seleccionar una compañía o marcar No importar "
                    "para estas filas antes de confirmar: %s"
                )
                % ", ".join(str(line.row_number) for line in missing_selection_lines)
            )

        selected_partners_by_row = {
            line.row_number: line.selected_partner_id
            for line in self.preview_line_ids
            if not line.skip_import
        }
        skipped_rows = {
            line.row_number
            for line in self.preview_line_ids
            if line.skip_import
        }
        try:
            rows, company_index, model_index, header_row_number = self._read_import_rows()
            log_text, values, _preview_lines = self._process_rows(
                rows,
                company_index,
                model_index,
                start_row=header_row_number + 1,
                dry_run=False,
                selected_partners_by_row=selected_partners_by_row,
                skipped_rows=skipped_rows,
            )
        except UserError:
            raise
        except Exception as error:
            _logger.exception("Error reading equipment model import file")
            return self._create_failed_history(
                _("No se ha podido leer el archivo Excel: %s") % error
            )

        history = self.env["equipment.model.import.history"].create(
            {
                **values,
                "name": _("Importación %s") % self.filename,
                "filename": self.filename,
                "state": "done",
                "log_text": log_text,
                "log_file": base64.b64encode(log_text.encode("utf-8")),
                "log_filename": self._log_filename(),
            }
        )
        return self._history_action(history)

    def _check_admin_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Solo los administradores pueden ejecutar esta importación."))

    def _read_import_rows(self):
        if not self.excel_file:
            raise UserError(_("Debes seleccionar un archivo Excel .xlsx."))
        if not self.filename or not self.filename.lower().endswith(".xlsx"):
            raise UserError(_("Solo se admiten archivos con extensión .xlsx."))
        if not openpyxl:
            raise UserError(
                _("La librería Python openpyxl no está instalada en el servidor.")
            )

        workbook = openpyxl.load_workbook(
            io.BytesIO(base64.b64decode(self.excel_file)),
            read_only=True,
            data_only=True,
        )
        rows = workbook.active.iter_rows(values_only=True)
        header_map = {}
        header_row_number = 0
        detected_headers = []
        required_headers = {
            self._normalize_header(COMPANY_COLUMN),
            self._normalize_header(MODEL_COLUMN),
        }

        for row_number, candidate_row in enumerate(rows, start=1):
            candidate_map = {
                self._normalize_header(value): index
                for index, value in enumerate(candidate_row)
                if self._normalize_header(value)
            }
            if len(candidate_map) > len(detected_headers):
                detected_headers = [
                    self._cell_text(candidate_row, index)
                    for index in candidate_map.values()
                ]
            if required_headers.issubset(candidate_map):
                header_map = candidate_map
                header_row_number = row_number
                break
            if row_number >= HEADER_SCAN_LIMIT:
                break

        if not header_map:
            detected_text = ", ".join(detected_headers) or _("ninguna")
            raise UserError(
                _(
                    "No se encontraron las columnas obligatorias en las "
                    "primeras %(limit)s filas: %(required)s.\n"
                    "Encabezados detectados: %(detected)s"
                )
                % {
                    "limit": HEADER_SCAN_LIMIT,
                    "required": ", ".join((COMPANY_COLUMN, MODEL_COLUMN)),
                    "detected": detected_text,
                }
            )

        return (
            rows,
            header_map[self._normalize_header(COMPANY_COLUMN)],
            header_map[self._normalize_header(MODEL_COLUMN)],
            header_row_number,
        )

    def _process_rows(
        self,
        rows,
        company_index,
        model_index,
        start_row=2,
        dry_run=False,
        selected_partners_by_row=None,
        skipped_rows=None,
    ):
        Partner = self.env["res.partner"].with_context(active_test=False)
        Tag = self.env["equipment.model.tag"].with_context(active_test=False)

        partners_by_name = defaultdict(lambda: Partner)
        partners_word_index = []
        for partner in Partner.search([("is_company", "=", True)]):
            normalized = normalize_name(partner.name)
            if normalized:
                partners_by_name[normalized] |= partner
            match_words = self._company_match_words(partner.name)
            if match_words:
                partners_word_index.append((match_words, partner))

        tags_by_name = {
            tag.normalized_name: tag
            for tag in Tag.search([])
            if tag.normalized_name
        }
        planned_tags = set()
        planned_associations = set()
        selected_partners_by_row = selected_partners_by_row or {}
        skipped_rows = skipped_rows or set()
        preview_lines = []

        companies_found = set()
        companies_not_found = set()
        models_created = set()
        models_existing = set()
        associations_created = 0
        associations_existing = 0
        errors = 0
        ignored_rows = 0
        title = _("COMPROBACIÓN PREVIA") if dry_run else _("IMPORTACIÓN EJECUTADA")
        log_lines = [
            title,
            _("Archivo: %s") % self.filename,
            _("Usuario: %s") % self.env.user.display_name,
            _(
                "Coincidencias sin distinguir mayúsculas/minúsculas "
                "e ignorando formas jurídicas como S.L. o S.A."
            ),
            "",
        ]

        for row_number, row in enumerate(rows, start=start_row):
            if not row or not any(value not in (None, "") for value in row):
                ignored_rows += 1
                log_lines.append(_("Fila %s: vacía; ignorada.") % row_number)
                continue

            company_name = self._cell_text(row, company_index)
            model_name = self._cell_text(row, model_index)
            if not company_name or not model_name:
                errors += 1
                missing = []
                if not company_name:
                    missing.append(COMPANY_COLUMN)
                if not model_name:
                    missing.append(MODEL_COLUMN)
                log_lines.append(
                    _("Fila %(row)s: incompleta; falta %(columns)s.")
                    % {"row": row_number, "columns": ", ".join(missing)}
                )
                continue

            normalized_company = normalize_name(company_name)
            matching_partners, match_type = self._find_matching_partners(
                company_name,
                partners_by_name,
                partners_word_index,
                Partner,
            )
            if not matching_partners:
                companies_not_found.add(normalized_company)
                log_lines.append(
                    _("Fila %(row)s: empresa no encontrada: %(company)s.")
                    % {"row": row_number, "company": company_name}
                )
                continue
            if len(matching_partners) > 1:
                if row_number in skipped_rows:
                    ignored_rows += 1
                    log_lines.append(
                        _(
                            "Fila %(row)s: no importada por decisión manual: "
                            "%(company)s / %(model)s."
                        )
                        % {
                            "row": row_number,
                            "company": company_name,
                            "model": model_name,
                        }
                    )
                    continue
                selected_partner = selected_partners_by_row.get(row_number)
                if selected_partner and selected_partner in matching_partners:
                    matching_partners = selected_partner
                    log_lines.append(
                        _(
                            "Fila %(row)s: empresa seleccionada manualmente: "
                            "Excel '%(excel)s' -> Odoo '%(odoo)s'."
                        )
                        % {
                            "row": row_number,
                            "excel": company_name,
                            "odoo": selected_partner.display_name,
                        }
                    )
                else:
                    errors += 1
                    candidates = ", ".join(matching_partners.mapped("display_name"))
                    log_lines.append(
                        _(
                            "Fila %(row)s: hay %(count)s compañías candidatas para "
                            "%(company)s; selecciona la compañía correcta en la "
                            "comprobación previa. Candidatas: %(candidates)s."
                        )
                        % {
                            "row": row_number,
                            "count": len(matching_partners),
                            "company": company_name,
                            "candidates": candidates,
                        }
                    )
                    if dry_run:
                        preview_lines.append(
                            (
                                0,
                                0,
                                {
                                    "row_number": row_number,
                                    "company_name": company_name,
                                    "model_name": model_name,
                                    "candidate_partner_ids": [
                                        (6, 0, matching_partners.ids)
                                    ],
                                    "candidate_names": "\n".join(
                                        matching_partners.mapped("display_name")
                                    ),
                                },
                            )
                        )
                    continue

            partner = matching_partners
            if match_type == "words":
                log_lines.append(
                    _(
                        "Fila %(row)s: empresa relacionada por palabras: "
                        "Excel '%(excel)s' -> Odoo '%(odoo)s'."
                    )
                    % {
                        "row": row_number,
                        "excel": company_name,
                        "odoo": partner.display_name,
                    }
                )
            companies_found.add(partner.id)
            normalized_model = normalize_name(model_name)
            tag = tags_by_name.get(normalized_model)
            if tag:
                if tag.id not in models_created:
                    models_existing.add(tag.id)
                if not tag.active:
                    if not dry_run:
                        tag.active = True
                    log_lines.append(
                        _("Fila %s: se reactivará el Equipo del Cliente %s.")
                        % (row_number, tag.name)
                        if dry_run
                        else _("Fila %s: se reactivó el Equipo del Cliente %s.")
                        % (row_number, tag.name)
                    )
                tag_key = tag.id
                tag_display_name = tag.name
            else:
                if normalized_model in planned_tags:
                    models_existing.add(normalized_model)
                    log_lines.append(
                        _("Fila %s: el Equipo del Cliente %s ya está previsto en este archivo.")
                        % (row_number, model_name)
                    )
                elif dry_run:
                    planned_tags.add(normalized_model)
                    models_created.add(normalized_model)
                    log_lines.append(
                        _("Fila %s: se creará el Equipo del Cliente: %s.")
                        % (row_number, model_name)
                    )
                else:
                    tag = Tag.create({"name": model_name})
                    tags_by_name[normalized_model] = tag
                    models_created.add(tag.id)
                    log_lines.append(
                        _("Fila %s: Equipo del Cliente creado: %s.") % (row_number, tag.name)
                    )
                tag_key = normalized_model if not tag else tag.id
                tag_display_name = model_name if not tag else tag.name

            association_key = (partner.id, tag_key)
            association_exists = bool(tag and tag in partner.equipment_model_tag_ids)
            if association_exists or association_key in planned_associations:
                associations_existing += 1
                log_lines.append(
                    _("Fila %(row)s: la asociación %(company)s / %(model)s ya existía.")
                    % {
                        "row": row_number,
                        "company": partner.display_name,
                        "model": tag_display_name,
                    }
                )
            else:
                if not dry_run:
                    partner.write({"equipment_model_tag_ids": [(4, tag.id)]})
                planned_associations.add(association_key)
                associations_created += 1
                log_lines.append(
                    _("Fila %(row)s: se creará la asociación %(company)s / %(model)s.")
                    % {
                        "row": row_number,
                        "company": partner.display_name,
                        "model": tag_display_name,
                    }
                    if dry_run
                    else _("Fila %(row)s: asociación creada: %(company)s / %(model)s.")
                    % {
                        "row": row_number,
                        "company": partner.display_name,
                        "model": tag_display_name,
                    }
                )

        summary = [
            "",
            _("RESUMEN"),
            _("Empresas encontradas: %s") % len(companies_found),
            _("Empresas no encontradas: %s") % len(companies_not_found),
            _("Equipos del Cliente a crear: %s") % len(models_created)
            if dry_run
            else _("Equipos del Cliente creados: %s") % len(models_created),
            _("Equipos del Cliente ya existentes: %s") % len(models_existing),
            _("Asociaciones a crear: %s") % associations_created
            if dry_run
            else _("Asociaciones creadas: %s") % associations_created,
            _("Asociaciones ya existentes: %s") % associations_existing,
            _("Errores: %s") % errors,
            _("Filas vacías ignoradas: %s") % ignored_rows,
        ]
        log_text = "\n".join(log_lines + summary)
        values = {
            "company_found_count": len(companies_found),
            "company_not_found_count": len(companies_not_found),
            "model_created_count": len(models_created),
            "model_existing_count": len(models_existing),
            "association_created_count": associations_created,
            "association_existing_count": associations_existing,
            "error_count": errors,
            "ignored_row_count": ignored_rows,
        }
        return log_text, values, preview_lines

    @classmethod
    def _find_matching_partners(
        cls, company_name, partners_by_name, partners_word_index, empty_partner
    ):
        normalized_company = normalize_name(company_name)
        exact_matches = partners_by_name.get(normalized_company, empty_partner)
        if exact_matches:
            return exact_matches, "exact"

        company_words = cls._company_match_words(company_name)
        if not company_words:
            return empty_partner, "none"

        subset_matches = empty_partner
        partial_matches = empty_partner
        for partner_words, partner in partners_word_index:
            common_words = company_words & partner_words
            if not common_words:
                continue
            if company_words <= partner_words or partner_words <= company_words:
                subset_matches |= partner
            else:
                partial_matches |= partner

        if subset_matches:
            return subset_matches, "words"
        return partial_matches, "words" if partial_matches else "none"

    @staticmethod
    def _company_match_words(value):
        return {
            word
            for word in re.findall(r"\w+", normalize_name(value))
            if word and word not in LEGAL_COMPANY_WORDS
        }

    def _create_failed_history(self, message):
        log_text = "%s\n\n%s" % (_("IMPORTACIÓN FALLIDA"), message)
        history = self.env["equipment.model.import.history"].create(
            {
                "name": _("Importación fallida %s") % (self.filename or ""),
                "filename": self.filename,
                "state": "failed",
                "error_count": 1,
                "log_text": log_text,
                "log_file": base64.b64encode(log_text.encode("utf-8")),
                "log_filename": self._log_filename(),
            }
        )
        return self._history_action(history)

    def _history_action(self, history):
        return {
            "type": "ir.actions.act_window",
            "name": _("Resultado de la importación"),
            "res_model": "equipment.model.import.history",
            "res_id": history.id,
            "view_mode": "form",
            "target": "current",
        }

    def _log_filename(self):
        base_name = (self.filename or "importacion").rsplit(".", 1)[0]
        return "%s_log.txt" % base_name

    @staticmethod
    def _cell_text(row, index):
        if index >= len(row) or row[index] is None:
            return ""
        return " ".join(str(row[index]).split())

    @staticmethod
    def _normalize_header(value):
        return " ".join(
            str(value or "").replace("\ufeff", "").split()
        ).casefold()


class EquipmentModelImportPreviewLine(models.TransientModel):
    _name = "equipment.model.import.preview.line"
    _description = "Línea de comprobación de importación de Equipos del Cliente"
    _order = "row_number, id"

    wizard_id = fields.Many2one(
        comodel_name="equipment.model.import.wizard",
        required=True,
        ondelete="cascade",
    )
    row_number = fields.Integer(string="Fila", readonly=True)
    company_name = fields.Char(string="Empresa en Excel", readonly=True)
    model_name = fields.Char(string="Equipo del Cliente", readonly=True)
    candidate_partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="equipment_import_preview_partner_rel",
        column1="line_id",
        column2="partner_id",
        string="Candidatas",
        readonly=True,
    )
    candidate_names = fields.Text(string="Candidatas", readonly=True)
    selected_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Empresa correcta",
    )
    skip_import = fields.Boolean(string="No importar")
