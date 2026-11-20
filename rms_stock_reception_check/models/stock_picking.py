# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    rms_reception_required = fields.Boolean(
        string="Recepción de proveedor obligatoria",
        help="Si se marca, un albarán de entrada de proveedor que lleve productos con nº de serie "
             "no se puede validar a mano desde el albarán: hay que darle entrada desde "
             "«Recepción de proveedor» (lista con la pistola). Los albaranes que solo llevan "
             "productos por cantidad se validan como siempre. Un responsable de inventario puede "
             "saltarse la recepción en un albarán concreto con «Validar sin recepción»: tiene que "
             "escribir el motivo y queda en el historial del albarán. Por defecto está apagada.")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    rms_reception_mandatory = fields.Boolean(
        string="Recepción obligatoria", compute="_compute_rms_reception_mandatory",
        help="El tipo de operación exige recepción de proveedor y el albarán lleva productos con nº de serie.")

    @api.depends("picking_type_id.rms_reception_required", "picking_type_id.code", "location_id.usage",
                 "move_ids.product_id.tracking", "move_ids.state")
    def _compute_rms_reception_mandatory(self):
        for picking in self:
            picking.rms_reception_mandatory = bool(
                picking.picking_type_id.rms_reception_required
                and picking.picking_type_id.code == "incoming"
                and picking.location_id.usage == "supplier"
                and any(m.state != "cancel" and m.product_id.tracking == "serial" for m in picking.move_ids))

    def button_validate(self):
        if not self.env.context.get("rms_reception_validated"):
            for picking in self:
                if picking.state not in ("done", "cancel") and picking.rms_reception_mandatory:
                    raise UserError(_(
                        "Este albarán de entrada lleva productos con nº de serie y los albaranes de «%s» "
                        "se dan de entrada desde «Recepción de proveedor». Un responsable de inventario "
                        "puede validarlo sin recepción indicando el motivo.", picking.picking_type_id.name))
        return super().button_validate()

    def action_rms_skip_reception(self):
        self.ensure_one()
        self._rms_require_reception_manager()
        return {
            "type": "ir.actions.act_window", "name": _("Validar sin recepción"),
            "res_model": "rms.reception.skip.wizard", "view_mode": "form", "target": "new",
            "context": {"default_picking_id": self.id},
        }

    def _rms_require_reception_manager(self):
        if not (self.env.su or self.env.user.has_group("stock.group_stock_manager")):
            raise AccessError(_("Esto solo lo puede decidir un responsable de inventario."))

    def _rms_validate_skipping_reception(self, reason):
        self.ensure_one()
        self._rms_require_reception_manager()
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("Escribe el motivo para validar sin recepción."))
        if self.state in ("done", "cancel"):
            raise UserError(_("Este albarán ya está cerrado."))
        self.message_post(body=_(
            "Validado SIN recepción de proveedor por %(user)s el %(date)s. Motivo: %(reason)s",
            user=self.env.user.name, date=fields.Datetime.to_string(fields.Datetime.now()), reason=reason))
        return self.with_context(rms_reception_validated=True).button_validate()


class RmsReceptionSkipWizard(models.TransientModel):
    _name = "rms.reception.skip.wizard"
    _description = "Validar sin recepción"

    picking_id = fields.Many2one("stock.picking", string="Albarán", required=True, readonly=True)
    reason = fields.Text(string="Motivo", required=True)

    def action_confirm(self):
        self.ensure_one()
        return self.picking_id._rms_validate_skipping_reception(self.reason)
