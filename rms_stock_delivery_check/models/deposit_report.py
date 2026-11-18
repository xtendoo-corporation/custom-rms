from odoo import api, fields, models

DEFAULT_DEPOSIT_TERMS = (
    "El material relacionado en este documento se entrega en depósito y es y seguirá siendo "
    "propiedad de la empresa. El cliente se compromete a custodiarlo, usarlo con diligencia y "
    "responder de cualquier daño o pérdida que sufra mientras esté en su poder. El cliente "
    "devolverá el material cuando la empresa se lo solicite. La firma de este documento "
    "acredita la recepción del material en el estado indicado."
)


class StockCession(models.Model):
    _inherit = 'stock.cession'

    rms_has_returns = fields.Boolean(compute='_compute_rms_has_returns')

    @api.depends('rms_unit_ids.qty_returned')
    def _compute_rms_has_returns(self):
        for cession in self:
            cession.rms_has_returns = any(u.qty_returned > 0 for u in cession.rms_unit_ids)

    def _rms_deposit_terms(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'rms_stock_delivery_check.deposit_terms') or DEFAULT_DEPOSIT_TERMS

    def action_rms_print_delivery(self):
        self.ensure_one()
        return self.env.ref('rms_stock_delivery_check.action_report_deposit_delivery').report_action(self)

    def action_rms_print_return(self):
        """Imprime la devolución: una hoja por cada albarán de vuelta validado."""
        self.ensure_one()
        return self.env.ref('rms_stock_delivery_check.action_report_deposit_return').report_action(self)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_rms_print_deposit_return(self):
        """Imprime solo la devolución de ESTE albarán de vuelta."""
        self.ensure_one()
        return self.env.ref('rms_stock_delivery_check.action_report_deposit_return').report_action(
            self.rms_cession_id, data={'return_picking_id': self.id})


def _sort_key(unit):
    return (unit.product_id.display_name, unit.lot_id.name or '')


class ReportDepositDelivery(models.AbstractModel):
    _name = 'report.rms_stock_delivery_check.report_deposit_delivery'
    _description = 'Informe de entrega en depósito'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['stock.cession'].browse(docids)
        return {
            'doc_ids': docids, 'doc_model': 'stock.cession', 'docs': docs,
            'terms': docs[:1]._rms_deposit_terms() if docs else DEFAULT_DEPOSIT_TERMS,
            # solo lo realmente entregado: albarán de salida validado
            'units_of': lambda c: c.rms_unit_ids.filtered(
                lambda u: u.out_picking_id.state == 'done').sorted(_sort_key),
        }


class ReportDepositReturn(models.AbstractModel):
    _name = 'report.rms_stock_delivery_check.report_deposit_return'
    _description = 'Informe de devolución de depósito'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['stock.cession'].browse(docids)
        only = (data or {}).get('return_picking_id')

        def returns_of(cession):
            """[(albarán de vuelta, unidades devueltas en él)], una hoja por albarán."""
            pickings = cession.rms_unit_ids.return_picking_id.filtered(lambda p: p.state == 'done')
            if only:
                pickings = pickings.filtered(lambda p: p.id == only)
            result = []
            for picking in pickings.sorted(lambda p: (p.date_done or fields.Datetime.now(), p.id)):
                units = cession.rms_unit_ids.filtered(
                    lambda u: u.return_picking_id == picking and u.qty_returned > 0).sorted(_sort_key)
                result.append((picking, units))
            return result

        return {
            'doc_ids': docids, 'doc_model': 'stock.cession', 'docs': docs,
            'returns_of': returns_of,
            'still_out_of': lambda c: c.rms_unit_ids.filtered(lambda u: u.state == 'out').sorted(_sort_key),
        }
