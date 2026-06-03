from odoo import models, fields, api

class RmsPartnerRole(models.Model):
    _name = 'rms.partner.role'
    _description = 'Roles de Contacto'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código Interno', required=True)
    color = fields.Integer(string='Índice de Color', default=0)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    rms_role_ids = fields.Many2many('rms.partner.role', string="Roles del Contacto")

    is_role_invoice = fields.Boolean(string="Contacto de facturación", compute="_compute_rms_roles", store=True)
    is_role_delivery = fields.Boolean(string="Dirección de entrega", compute="_compute_rms_roles", store=True)
    is_role_pricelist = fields.Boolean(string="Listas de precios", compute="_compute_rms_roles", store=True)
    is_role_technical = fields.Boolean(string="Técnicos", compute="_compute_rms_roles", store=True)
    is_role_general = fields.Boolean(string="Comunicación general", compute="_compute_rms_roles", store=True)

    @api.depends('rms_role_ids')
    def _compute_rms_roles(self):
        for partner in self:
            codes = partner.rms_role_ids.mapped('code')
            partner.is_role_invoice = 'invoice' in codes
            partner.is_role_delivery = 'delivery' in codes
            partner.is_role_pricelist = 'pricelist' in codes
            partner.is_role_technical = 'technical' in codes
            partner.is_role_general = 'general' in codes

    # Campos específicos por categoría
    custom_invoice_address = fields.Text(string="Dirección de Facturación")
    custom_delivery_address = fields.Text(string="Dirección de Envío")
    role_pricelist_notes = fields.Char(string="Notas de Tarifas / Precios")
    technical_notes = fields.Text(string="Notas Técnicas")
    general_notes = fields.Text(string="Notas de Comunicación General")

    @api.onchange('rms_role_ids')
    def _onchange_multi_role(self):
        """
        Mantiene el campo 'type' nativo siempre como 'contact'.
        Esto asegura que Odoo genere mágicamente el avatar con la inicial y aplique 
        las clases de CSS correctas.
        """
        for partner in self:
            partner.type = 'contact'

    def address_get(self, adr_pref=None):
        """
        Sobrescribe el método nativo para soportar múltiples roles por contacto.
        """
        if adr_pref is None:
            adr_pref = ['contact']

        res = super(ResPartner, self).address_get(adr_pref)

        for pref in adr_pref:
            for child in self.child_ids:
                if pref == 'invoice' and child.is_role_invoice:
                    res[pref] = child.id
                    break
                elif pref == 'delivery' and child.is_role_delivery:
                    res[pref] = child.id
                    break
                elif pref == 'contact' and child.is_role_general:
                    res[pref] = child.id
                    break
                elif pref == 'pricelist' and child.is_role_pricelist:
                    res[pref] = child.id
                    break
                elif pref == 'technical' and child.is_role_technical:
                    res[pref] = child.id
                    break

        return res
