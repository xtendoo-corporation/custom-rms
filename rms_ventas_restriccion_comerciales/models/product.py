# -*- coding: utf-8 -*-

from odoo import api, models

NOTICE_CLASS = 'o_rms_comerciales_notice'
RESTRICTED_GROUPS = '!custom.comerciales'


class ProductRestrictionMixin(models.AbstractModel):
    _name = 'rms.product.comerciales.restriction.mixin'
    _description = 'Restricción de ficha de producto para comerciales'

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        # Un comercial que además puede dar de alta productos (p. ej. también es
        # responsable de compras/almacén) debe poder abrir la ficha que acaba de
        # crear: se anula la restricción de la vista para él.
        if view_type == 'form' and self.env['ir.model.access'].check(
            'product.template', 'create', raise_exception=False
        ):
            for node in arch.xpath('//sheet[@groups="%s"]' % RESTRICTED_GROUPS):
                del node.attrib['groups']
            for node in arch.xpath("//div[contains(concat(' ', @class, ' '), ' %s ')]" % NOTICE_CLASS):
                node.getparent().remove(node)
        return arch, view


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'rms.product.comerciales.restriction.mixin']


class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = ['product.product', 'rms.product.comerciales.restriction.mixin']
