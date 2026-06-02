from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_role_contact = fields.Boolean(string="Contacto general", default=True)
    is_role_invoice = fields.Boolean(string="Facturación")
    is_role_delivery = fields.Boolean(string="Entrega de mercancía")
    is_role_pricelist = fields.Boolean(string="Lista de precios")
    is_role_technical = fields.Boolean(string="Cuestiones técnicas")
    is_role_presentation = fields.Boolean(string="Presentación de productos")

    # Campos específicos por categoría
    custom_invoice_address = fields.Text(string="Dirección de Facturación")
    custom_delivery_address = fields.Text(string="Dirección de Envío")
    role_pricelist_notes = fields.Char(string="Notas de Tarifas / Precios")
    technical_notes = fields.Text(string="Notas Técnicas")
    presentation_requirements = fields.Text(string="Requisitos de Presentación")

    @api.onchange('is_role_contact', 'is_role_invoice', 'is_role_pricelist', 'is_role_technical', 'is_role_delivery', 'is_role_presentation')
    def _onchange_multi_role(self):
        """
        Mantiene el campo 'type' nativo siempre como 'contact'.
        Esto asegura que Odoo asigne la imagen por defecto estándar (avatar) 
        y aplique las clases visuales de CSS correctas en la vista Kanban de contactos hijos.
        La lógica real de roles es manejada por nuestro address_get() y los booleanos.
        """
        for partner in self:
            partner.type = 'contact'

    def address_get(self, adr_pref=None):
        """
        Sobrescribe el método nativo para soportar múltiples roles por contacto.
        """
        if adr_pref is None:
            adr_pref = ['contact']

        # Obtenemos el resultado base nativo
        res = super(ResPartner, self).address_get(adr_pref)

        # Refinamos el resultado usando nuestros campos booleanos personalizados.
        for pref in adr_pref:
            for child in self.child_ids:
                if pref == 'invoice' and child.is_role_invoice:
                    res[pref] = child.id
                    break
                elif pref == 'delivery' and child.is_role_delivery:
                    res[pref] = child.id
                    break
                elif pref == 'contact' and child.is_role_contact:
                    res[pref] = child.id
                    break
                # Soporte para las categorías personalizadas si es que algún otro módulo las usa
                elif pref == 'pricelist' and child.is_role_pricelist:
                    res[pref] = child.id
                    break
                elif pref == 'technical' and child.is_role_technical:
                    res[pref] = child.id
                    break
                elif pref == 'presentation' and child.is_role_presentation:
                    res[pref] = child.id
                    break

        return res

    def _get_default_image_path(self, partner_type, is_company, parent_id):
        """
        Sobrescribe la ruta de la imagen por defecto para que los contactos hijos siempre
        muestren el avatar estándar (persona) en lugar de los iconos de camión (delivery) o
        billetes (invoice), independientemente del tipo nativo subyacente.
        """
        # Si es una empresa, dejamos el comportamiento normal
        if is_company:
            return super(ResPartner, self)._get_default_image_path(partner_type, is_company, parent_id)
        
        # Para contactos individuales, forzamos siempre el avatar gris
        return 'base/static/img/avatar_grey.png'
