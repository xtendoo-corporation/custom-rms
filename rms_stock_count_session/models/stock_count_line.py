# -*- coding: utf-8 -*-

from odoo import api, fields, models

STATUS_SELECTION = [
    ("match", "Coincide"),
    ("partial", "Solo lo vio una parte"),
    ("qty_diff", "Cantidades distintas"),
    ("unexpected", "Nuevo (no estaba en Odoo)"),
    ("missing", "Nadie lo escaneó"),
]


class RmsStockCountLine(models.Model):
    """Una línea del informe de cruce. Se regenera entera cada vez que se
    cierra el recuento o se pulsa 'Regenerar cruce'; lo único que se toca a
    mano es la cantidad final, la ubicación y si se vuelca o no."""

    _name = "rms.stock.count.line"
    _description = "Línea de cruce de recuento"
    _order = "status_sequence, product_id, lot_name, id"

    session_id = fields.Many2one(
        "rms.stock.count.session", string="Recuento", required=True, ondelete="cascade", index=True,
    )
    session_state = fields.Selection(related="session_id.state", string="Estado del recuento")
    product_id = fields.Many2one("product.product", string="Producto", required=True)
    tracking = fields.Selection(related="product_id.tracking", string="Seguimiento")
    lot_id = fields.Many2one("stock.lot", string="Nº de serie / lote en Odoo")
    lot_name = fields.Char(string="Nº de serie / lote")
    location_id = fields.Many2one("stock.location", string="Ubicación", required=True)
    expected_qty = fields.Float(string="En Odoo", digits="Product Unit")
    counted_qty = fields.Float(string="Contado", digits="Product Unit")
    operator_seen_count = fields.Integer(string="Lo vieron")
    operator_total = fields.Integer(string="Operarios")
    seen_by = fields.Char(string="Escaneado por")
    qty_by_operator = fields.Char(string="Cantidad por operario")
    location_mismatch = fields.Boolean(
        string="Ubicaciones distintas",
        help="Los operarios lo escanearon en ubicaciones diferentes.",
    )
    status = fields.Selection(STATUS_SELECTION, string="Resultado", required=True)
    status_sequence = fields.Integer(
        compute="_compute_status_sequence", store=True,
        help="Orden del informe: primero lo que hay que revisar.",
    )
    to_apply = fields.Boolean(
        string="Volcar",
        help="Si está marcado, al volcar el recuento esta línea se pasa a "
             "Inventario físico con la cantidad 'Contado'. Las líneas que "
             "nadie escaneó vienen desmarcadas: márcalas solo si confirmas "
             "que de verdad faltan (se contarán a 0).",
    )

    @api.depends("status")
    def _compute_status_sequence(self):
        order = {"missing": 1, "partial": 2, "qty_diff": 3, "unexpected": 4, "match": 5}
        for line in self:
            line.status_sequence = order.get(line.status, 9)

