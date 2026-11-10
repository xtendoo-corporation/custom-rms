# -*- coding: utf-8 -*-

from odoo import models
from odoo.tools.pdf import rotate_pdf

LABEL_REPORT = "rms_stock_lot_label_print.report_lot_label_10x5_document"


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """La etiqueta se maqueta apaisada (50x29 mm) y aquí se gira la página
        90 grados: el PDF queda vertical, 29 mm (ancho de la cinta Brother) x
        50 mm (largo), y se imprime tal cual desde el navegador o el iPhone.
        Se gira la página entera, sin rasterizar: el código de barras no
        pierde resolución (girarlo con CSS en wkhtmltopdf sí la perdía)."""
        content, report_type = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        if report_type == "pdf" and isinstance(content, bytes) and content \
                and self._get_report(report_ref).report_name == LABEL_REPORT:
            content = rotate_pdf(content)
        return content, report_type
