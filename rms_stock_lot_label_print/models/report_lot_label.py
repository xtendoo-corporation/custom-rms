# -*- coding: utf-8 -*-

from odoo import api, models


class ReportLotLabel(models.AbstractModel):
    """Valores de la etiqueta: permite imprimir varias copias de cada número
    de serie (asistente de etiqueta sustituta) sin duplicar registros."""

    _name = "report.rms_stock_lot_label_print.report_lot_label_10x5_document"
    _description = "Etiqueta código de barras de número de serie"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        copies = max(int(data.get("copies") or 1), 1)
        # Si llegan datos (copias) Odoo puede no mandar los ids en la URL:
        # se toman de los datos o del contexto para no imprimir en blanco.
        docids = docids or data.get("doc_ids") or data.get("context", {}).get("active_ids") \
            or self.env.context.get("active_ids") or []
        return {
            "doc_ids": docids,
            "doc_model": "stock.lot",
            "docs": self.env["stock.lot"].browse(docids),
            "copies": copies,
        }
