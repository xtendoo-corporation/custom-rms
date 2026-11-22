# -*- coding: utf-8 -*-
import logging

import psycopg2

from odoo import api, fields, models
from odoo.exceptions import ConcurrencyError

_logger = logging.getLogger(__name__)

_CLIENT_UID_INDEX = "rms_reception_scan_reception_client_uid_uniq"

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
    client_uid = fields.Char(
        string="Id. de lectura en el dispositivo", index=True, readonly=True, copy=False,
        help="Evita duplicar una lectura si el aparato la reenvía tras perder la conexión.",
    )

    def init(self):
        """Índice único parcial (reception_id, client_uid). Se crea a mano para
        que una base con duplicados antiguos no rompa la actualización: en ese
        caso se avisa en el registro y sigue valiendo la comprobación previa."""
        cr = self.env.cr
        cr.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (_CLIENT_UID_INDEX,))
        if cr.fetchone():
            return
        cr.execute("""
            SELECT 1 FROM rms_reception_scan WHERE client_uid IS NOT NULL
             GROUP BY reception_id, client_uid HAVING count(*) > 1 LIMIT 1
        """)
        if cr.fetchone():
            _logger.warning(
                "rms_reception_scan: hay lecturas antiguas con el mismo client_uid; "
                "no se crea el índice único %s.", _CLIENT_UID_INDEX)
            return
        cr.execute(
            "CREATE UNIQUE INDEX %s ON rms_reception_scan (reception_id, client_uid) "
            "WHERE client_uid IS NOT NULL" % _CLIENT_UID_INDEX)

    @api.model
    def _create_scan(self, vals):
        """Crea la lectura. Si otra petición con el mismo client_uid (la misma
        lectura reenviada mientras la primera seguía en curso) se ha
        adelantado, se repite la llamada entera: en el reintento ya se ve la
        fila guardada y se contesta con su mismo veredicto."""
        if not vals.get("client_uid"):
            return self.create(vals)
        try:
            with self.env.cr.savepoint():
                return self.create(vals)
        except psycopg2.errors.UniqueViolation as exc:
            if getattr(exc.diag, "constraint_name", "") != _CLIENT_UID_INDEX:
                raise
            raise ConcurrencyError("Lectura reenviada a la vez: %s" % vals["client_uid"]) from exc

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
            # Un código de producto leído vale para la caja siguiente.
            "sets_context": self.verdict == "product_code" and bool(self.product_id),
        }
