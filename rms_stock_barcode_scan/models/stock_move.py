# -*- coding: utf-8 -*-

from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def action_scan_serials(self):
        """Abre el asistente de escaneo por cámara para esta línea de
        movimiento: los números de serie escaneados se añaden
        directamente a esta línea (stock.move.line), igual que si se
        tecleasen a mano en "Operaciones detalladas"."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "rms_stock_barcode_scan.scan",
            "name": "Escanear número de serie",
            "target": "new",
            "context": {"default_move_id": self.id},
        }
