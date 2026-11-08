# -*- coding: utf-8 -*-

from odoo import api, models


class ReportLotLabel(models.AbstractModel):
    """Valores de la etiqueta: permite imprimir varias copias de cada número
    de serie (asistente de etiqueta sustituta) sin duplicar registros."""

    _name = "report.rms_stock_lot_label_print.report_lot_label_10x5_document"
    _description = "Etiqueta código de barras de número de serie"

    @api.model
    def _get_report_values(self, docids, data=None):
        copies = max(int((data or {}).get("copies") or 1), 1)
        return {
            "doc_ids": docids,
            "doc_model": "stock.lot",
            "docs": self.env["stock.lot"].browse(docids),
            "copies": copies,
        }
