from odoo import models, api
from odoo.osv import expression

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        domain = self.env['product.product']._split_search_words(domain)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        domain = self._split_search_words(domain)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

    @api.model
    def _split_search_words(self, domain):
        if not domain:
            return domain
        
        domain_list = list(domain) if hasattr(domain, '__iter__') else domain
        
        # Odoo 18/19 usa objetos SQL() u operadores internos ('any!') en algunas consultas.
        # Si detectamos alguno, devolvemos el dominio original intacto para evitar crasheos de seguridad.
        for leaf in domain_list:
            if isinstance(leaf, (tuple, list)) and len(leaf) == 3:
                if type(leaf[2]).__name__ == 'SQL' or leaf[1] not in ('=', '!=', '<=', '<', '>', '>=', '=?', '=like', '=ilike', 'like', 'not like', 'ilike', 'not ilike', 'in', 'not in', 'child_of', 'parent_of'):
                    return domain

        changed = False
        new_domain = []
        for leaf in domain_list:
            if isinstance(leaf, (tuple, list)) and len(leaf) == 3:
                field, operator, value = leaf
                if isinstance(value, str) and operator in ('ilike', 'like', '=ilike') and ' ' in value:
                    words = value.split()
                    if len(words) > 1:
                        # Reemplaza la hoja por un AND con todas las palabras para ese campo
                        leaf_domain = expression.AND([[(field, operator, w)] for w in words])
                        new_domain.extend(leaf_domain)
                        changed = True
                        continue
            new_domain.append(leaf)
            
        if changed:
            return expression.normalize_domain(new_domain)
        return domain

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # Override específico para el desplegable (Many2one) de la línea de pedido
        if name and ' ' in name and operator in ('ilike', 'like', '=ilike'):
            words = name.split()
            if len(words) > 1:
                product_ids = None
                for word in words:
                    res = super().name_search(name=word, domain=domain, operator=operator, limit=limit)
                    ids = {r[0] for r in res}
                    if product_ids is None:
                        product_ids = ids
                    else:
                        product_ids &= ids
                    
                    if not product_ids:
                        break
                
                if product_ids:
                    # Obtenemos los nombres usando la primera búsqueda para mantener el formato
                    first_res = super().name_search(name=words[0], domain=domain, operator=operator, limit=limit)
                    return [r for r in first_res if r[0] in product_ids]
                return []
                
        return super().name_search(name, domain, operator, limit)
