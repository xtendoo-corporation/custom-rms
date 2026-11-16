# -*- coding: utf-8 -*-
from odoo import fields, models

VERDICTS = [
    ("ok", "Verde: coincide"),
    ("probable", "Ámbar: coincidencia probable"),
    ("wrong_model", "Ámbar: modelo distinto"),
    ("ambiguous", "Ámbar: está en varios modelos"),
    ("extra", "Rojo: no está en la lista"),
    ("product_code", "Gris: código de producto"),
    ("ignored", "Gris: ignorado"),
    ("repeat", "Ya leído"),
]


class RmsReceptionScan(models.Model):
    """Registro de TODAS las lecturas (quién, cuándo, qué salió). Nunca se
    borra: deshacer una lectura solo la marca como deshecha."""

    _name = "rms.reception.scan"
    _description = "Lectura de recepción de proveedor"
    _order = "id desc"
    _rec_name = "code"

    reception_id = fields.Many2one(
        "rms.reception", string="Recepción", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="reception_id.company_id", store=True, index=True)
    user_id = fields.Many2one(
        "res.users", string="Operario", required=True, default=lambda self: self.env.user, index=True,
    )
    scanned_at = fields.Datetime(string="Fecha", required=True, default=fields.Datetime.now)
    raw_code = fields.Char(string="Lectura original")
    code = fields.Char(string="Código", required=True)
    verdict = fields.Selection(VERDICTS, string="Resultado", required=True)
    effect = fields.Selection(
        [("none", "Ninguno"), ("line", "Marcó una línea"), ("extra", "Creó un sobrante"), ("qty", "Sumó cantidad")],
        string="Efecto", default="none", required=True,
    )
    quantity = fields.Float(string="Cantidad", default=0.0)
    line_id = fields.Many2one("rms.reception.line", string="Línea", ondelete="set null", index=True)
    product_id = fields.Many2one("product.product", string="Producto")
    message = fields.Char(string="Detalle")
    manual = fields.Boolean(string="Escrito a mano")
    undone = fields.Boolean(string="Deshecha")
    client_uid = fields.Char(string="Id. de lectura en el dispositivo", index=True)

    def _payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "code": self.code,
            "verdict": self.verdict,
            "message": self.message or "",
            "line_id": self.line_id.id or False,
            "product_id": self.product_id.id or False,
            "product_name": self.product_id.display_name or "",
            "user": self.user_id.name,
            "mine": self.user_id == self.env.user,
            "time": fields.Datetime.context_timestamp(self, self.scanned_at).strftime("%H:%M"),
            "undone": self.undone,
            "can_undo": bool(self.effect != "none" and not self.undone),
        }
