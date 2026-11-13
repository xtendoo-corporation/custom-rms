# -*- coding: utf-8 -*-

import json
import re
from urllib.parse import quote

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.stock_lot import REPLACEMENT_REASONS

_SPLIT_RE = re.compile(r"[\n,;]+")


class RmsLotLabelWizard(models.TransientModel):
    """Etiqueta sustituta: el equipo tiene el número de serie (grabado en
    la placa, en una pegatina sin código de barras, o en una caja con varios
    equipos) pero no una etiqueta que se pueda escanear. Se escribe el
    número de serie, se da de alta en Odoo si no existe y se imprime una
    etiqueta propia con la referencia del producto y el número de serie en
    código de barras."""

    _name = "rms.lot.label.wizard"
    _description = "Etiqueta sustituta de número de serie"

    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain="[('tracking', '!=', 'none')]",
    )
    default_code = fields.Char(related="product_id.default_code", string="Referencia")
    serial_text = fields.Text(
        string="Números de serie",
        required=True,
        help="Uno por línea. Para una caja con varios equipos, escribe todos.",
    )
    serial_confirm = fields.Char(
        string="Repite el número de serie",
        help="Solo cuando es un único número de serie: evita imprimir una "
             "etiqueta con una errata.",
    )
    serial_count = fields.Integer(compute="_compute_preview")
    product_state_id = fields.Many2one(
        "product.state",
        string="Estado",
        default=lambda self: self.env["product.state"].search([("code", "=", "new")], limit=1),
        help="Solo se aplica a los números de serie nuevos; los que ya existen "
             "conservan su estado.",
    )
    reason = fields.Selection(
        REPLACEMENT_REASONS, string="Motivo", required=True, default="no_label",
    )
    copies = fields.Integer(string="Copias por número de serie", default=1)
    preview = fields.Html(string="Resumen", compute="_compute_preview", sanitize=False)

    @api.model
    def _parse_serials(self, text):
        serials = []
        for chunk in _SPLIT_RE.split(text or ""):
            serial = chunk.strip()
            if serial and serial not in serials:
                serials.append(serial)
        return serials

    @api.depends("serial_text", "product_id")
    def _compute_preview(self):
        Lot = self.env["stock.lot"]
        for wizard in self:
            serials = self._parse_serials(wizard.serial_text)
            wizard.serial_count = len(serials)
            if not serials or not wizard.product_id:
                wizard.preview = False
                continue
            rows = []
            for serial in serials:
                same = Lot.search([
                    ("product_id", "=", wizard.product_id.id), ("name", "=", serial),
                ], limit=1)
                other = Lot.search([
                    ("product_id", "!=", wizard.product_id.id), ("name", "=", serial),
                ], limit=3)
                if same:
                    status = Markup('<span class="text-info">ya existe: se reimprime</span>')
                else:
                    status = Markup('<span class="text-success">nuevo: se dará de alta</span>')
                if other:
                    status += Markup(' · <span class="text-warning">ojo, también existe en %s</span>') % (
                        ", ".join(other.mapped("product_id.display_name"))
                    )
                rows.append(Markup("<li><b>%s</b> — %s</li>") % (escape(serial), status))
            wizard.preview = Markup("<ul class='mb-0'>%s</ul>") % Markup("").join(rows)

    def _check_input(self, serials):
        self.ensure_one()
        if not serials:
            raise UserError("Escribe al menos un número de serie.")
        if self.product_id.tracking == "none":
            raise UserError(
                "%s no lleva seguimiento por número de serie/lote. Cámbialo en la "
                "pestaña Inventario del producto." % self.product_id.display_name
            )
        if len(serials) == 1 and (self.serial_confirm or "").strip() != serials[0]:
            raise UserError(
                "El número de serie repetido no coincide con el primero. Revisa la placa "
                "del equipo y vuelve a escribirlo."
            )
        if self.product_id.tracking == "serial":
            too_long = [s for s in serials if len(s) > 64]
            if too_long:
                raise UserError("Número de serie demasiado largo: %s" % too_long[0])

    def _replacement_company(self):
        """Shared products may have shared lots; callers can select an owner."""
        self.ensure_one()
        return self.product_id.company_id

    def _get_or_create_lots(self, serials):
        Lot = self.env["stock.lot"]
        lots = Lot.browse()
        company = self._replacement_company()
        for serial in serials:
            companies = [company.id, False] if company else self.env.companies.ids + [False]
            matches = Lot.search([
                ("product_id", "=", self.product_id.id),
                ("name", "=", serial),
                ("company_id", "in", companies),
            ])
            if len(matches) > 1:
                raise UserError("El número de serie %s existe en varias empresas. Selecciona únicamente la empresa propietaria antes de imprimir." % serial)
            lot = matches
            if not lot:
                vals = {
                    "product_id": self.product_id.id,
                    "name": serial,
                    "company_id": company.id or False,
                }
                if self.product_state_id:
                    vals["product_state_id"] = self.product_state_id.id
                lot = Lot.create(vals)
            lots |= lot
        lots.write({
            "rms_replacement_label": True,
            "rms_replacement_reason": self.reason,
            "rms_label_printed_date": fields.Datetime.now(),
        })
        return lots

    def action_create_and_print(self):
        self.ensure_one()
        serials = self._parse_serials(self.serial_text)
        self._check_input(serials)
        lots = self._get_or_create_lots(serials)
        self._after_lots_created(lots)
        # El PDF se abre en una pestaña nueva (se ve y se imprime desde ahí,
        # sin descargarlo) con los números de serie en la dirección: con
        # report_action + data Odoo no los manda y la etiqueta salía en blanco.
        report = self.env.ref("rms_stock_lot_label_print.action_report_lot_label_10x5")
        options = json.dumps({"copies": max(self.copies, 1)}, separators=(",", ":"))
        return {
            "type": "ir.actions.act_url",
            "url": "/report/pdf/%s/%s?options=%s" % (
                report.report_name, ",".join(str(lot_id) for lot_id in lots.ids), quote(options)),
            "target": "new",
            "close": True,
        }

    def _after_lots_created(self, lots):
        """Gancho para otros módulos (p. ej. el recuento cruzado registra
        aquí la lectura de los números de serie)."""
        return True
