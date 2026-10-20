# -*- coding: utf-8 -*-

from odoo import fields, models


class RmsLotLabelWizard(models.TransientModel):
    _inherit = "rms.lot.label.wizard"

    count_operator_id = fields.Many2one(
        "rms.stock.count.operator", string="Operario del recuento", readonly=True,
    )

    def _after_lots_created(self, lots):
        """Abierto desde el escáner de un recuento: los números de serie
        etiquetados quedan como leídos por ese operario (no hace falta
        escanear la etiqueta recién impresa)."""
        res = super()._after_lots_created(lots)
        operator = self.count_operator_id
        if not operator or operator.session_id.state != "counting":
            return res
        Scan = self.env["rms.stock.count.scan"]
        location = operator.current_location_id or operator.session_id.location_id
        for lot in lots:
            already = Scan.search_count([
                ("operator_id", "=", operator.id),
                ("scan_type", "=", "serial"),
                ("product_id", "=", lot.product_id.id),
                ("lot_name", "=", lot.name),
            ])
            if already:
                continue
            Scan.create({
                "session_id": operator.session_id.id,
                "operator_id": operator.id,
                "raw_code": lot.name,
                "code": lot.name,
                "scan_type": "serial",
                "product_id": lot.product_id.id,
                "lot_id": lot.id,
                "lot_name": lot.name,
                "location_id": location.id,
                "quantity": 1.0,
                "message": "Etiqueta sustituta impresa: %s · %s" % (
                    lot.product_id.display_name, lot.name,
                ),
            })
        operator.current_product_id = self.product_id
        return res
