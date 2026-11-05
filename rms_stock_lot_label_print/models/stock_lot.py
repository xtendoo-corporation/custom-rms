# -*- coding: utf-8 -*-

import base64
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

REPLACEMENT_REASONS = [
    ("no_label", "Sin caja / etiqueta original (nº de serie grabado en el equipo)"),
    ("damaged", "Etiqueta original dañada o ilegible"),
    ("multi", "Caja con varios equipos"),
    ("other", "Otro motivo"),
]


class StockLot(models.Model):
    _inherit = "stock.lot"

    rms_label_barcode_image = fields.Binary(
        string="Código de barras (etiqueta)",
        compute="_compute_rms_label_barcode_image",
    )
    rms_replacement_label = fields.Boolean(
        string="Etiqueta sustituta",
        copy=False,
        help="Se ha impreso una etiqueta propia para este número de serie "
             "porque la original del fabricante falta o no se puede leer.",
    )
    rms_replacement_reason = fields.Selection(
        REPLACEMENT_REASONS, string="Motivo de la etiqueta sustituta", copy=False,
    )
    rms_label_printed_date = fields.Datetime(
        string="Última impresión de etiqueta", copy=False, readonly=True,
    )

    def _compute_rms_label_barcode_image(self):
        Report = self.env["ir.actions.report"]
        for lot in self:
            if not lot.name:
                lot.rms_label_barcode_image = False
                continue
            try:
                barcode = Report.barcode(
                    "Code128", lot.name, width=600, height=180, humanreadable=0
                )
                lot.rms_label_barcode_image = base64.b64encode(barcode)
            except Exception:
                _logger.exception(
                    "No se pudo generar el código de barras para el número de serie %s",
                    lot.name,
                )
                lot.rms_label_barcode_image = False
