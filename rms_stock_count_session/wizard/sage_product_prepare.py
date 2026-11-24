# -*- coding: utf-8 -*-
"""Preparar en bloque los productos de Odoo a partir de los artículos de Sage
(caso 3: el checklist necesita que cada nº de serie de Sage tenga producto y
que ese producto se siga por nº de serie)."""
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.sage_library import article_parts
from ..models.scan_rule import normalize_code


class SageProductPrepare(models.TransientModel):
    _name = 'rms.sage.product.prepare'
    _description = 'Preparar productos desde Sage'

    line_ids = fields.Many2many('rms.sage.stock.line', string='Líneas de Sage')
    preview = fields.Text(compute='_compute_preview', string='Qué se va a hacer')

    @api.model
    def _groups(self, lines):
        """Agrupa las líneas sin producto por modelo (referencia sin el prefijo
        de estado D-/2M-): las variantes Demo y 2ª mano son el mismo producto."""
        groups = defaultdict(lambda: self.env['rms.sage.stock.line'])
        for line in lines.filtered(lambda l: l.is_current and not l.product_id):
            key = normalize_code(line.model_code or line.article_code)
            if key:
                groups[key] |= line
        return groups

    @api.model
    def _existing_product(self, model):
        Product = self.env['product.template']
        return Product.search([('default_code', '=ilike', model)], limit=2)

    @api.depends('line_ids')
    def _compute_preview(self):
        for wizard in self:
            groups = wizard._groups(wizard.line_ids)
            create = assign = ambiguous = 0
            for key, lines in groups.items():
                found = wizard._existing_product(lines[0].model_code or lines[0].article_code)
                if len(found) == 1:
                    assign += 1
                elif found:
                    ambiguous += 1
                else:
                    create += 1
            tracked = wizard._products_to_track(wizard.line_ids)
            wizard.preview = (
                "Artículos de Sage sin producto: %d\n"
                "  - se crearán como productos nuevos: %d\n"
                "  - se asignarán a un producto que ya tiene esa referencia: %d\n"
                "  - con varias coincidencias (se dejan para asignar a mano): %d\n"
                "Productos que en Sage tienen nº de serie y en Odoo no se siguen por nº de serie: %d"
                % (len(groups), create, assign, ambiguous, len(tracked))
            )

    def action_create_products(self):
        """Crea (o asigna) un producto por cada modelo de Sage sin producto y
        deja apuntada la correspondencia para que las próximas cargas lo
        reconozcan solas."""
        self.ensure_one()
        self.env['product.template'].check_access('create')
        Map = self.env['rms.sage.article.map']
        existing_maps = set(Map.search([]).mapped('article_code'))
        created = assigned = skipped = 0
        resolved = self.env['rms.sage.stock.line']
        unknown_brand = False
        groups = self._groups(self.line_ids)
        Article = self.env['rms.sage.article'].sudo()
        all_codes = set()
        for lines in groups.values():
            all_codes.update(filter(None, lines.mapped('model_code') + lines.mapped('article_code')))
        master_brands = Article._brands_by_article(all_codes)
        master_names = {article.code_normalized: article.name for article in Article.search(
            [('code_normalized', 'in', [normalize_code(code) for code in all_codes])]) if article.name}
        for key, lines in groups.items():
            model = (lines[0].model_code or lines[0].article_code).strip()
            # Primero los enlaces ya hechos (fusiones, alias): la demo o la 2ª
            # mano de un modelo enlazado no debe crear otro producto.
            linked = Map.search([('article_code', 'in', [normalize_code(model)] + [
                normalize_code(c) for c in lines.mapped('article_code')])]).product_tmpl_id.filtered('active')
            found = linked[:1] if len(linked) == 1 else self._existing_product(model)
            if len(found) > 1:
                skipped += 1
                continue
            template = found
            if not template:
                # La marca del maestro de Sage manda; si no está, la de la carga.
                codes = [normalize_code(model)] + [normalize_code(c) for c in lines.mapped('article_code')]
                brand_id = next((master_brands[c] for c in codes if c in master_brands), False)
                brand = self.env['product.category'].browse(brand_id) if brand_id else lines.brand_categ_id[:1]
                if not brand:
                    if not unknown_brand:
                        unknown_brand = self._unknown_brand()
                    brand = unknown_brand
                has_serials = any(line.serial_normalized and line.quantity == 1 for line in lines)
                name = (next((master_names[c] for c in codes if c in master_names), False)
                        or next((line.article_name for line in lines if line.article_name), False) or model)
                template = self.env['product.template'].create(
                    self._new_template_vals(model, name, brand, has_serials))
                created += 1
            else:
                assigned += 1
            for article in set(lines.mapped('article_code')):
                code = normalize_code(article)
                if code and code not in existing_maps:
                    Map.create({'article_code': code, 'product_tmpl_id': template.id})
                    existing_maps.add(code)
            resolved |= self.env['rms.sage.stock.line'].search(
                [('article_normalized', 'in', [normalize_code(a) for a in set(lines.mapped('article_code'))])])
        if resolved:
            resolved._resolve_products()
            refresh = getattr(self.env['rms.stock.count.scan'], '_refresh_sage_suggestions', None)
            if refresh:
                refresh(resolved.filtered('is_current').mapped('serial_normalized'))
        return self._notify(
            "Productos desde Sage",
            "Creados: %d · Asignados a uno existente: %d · Con varias coincidencias (a mano): %d"
            % (created, assigned, skipped))

    # ------------------------------------------------------------------
    # Piezas comunes con "Crear este producto" del escáner del recuento
    # ------------------------------------------------------------------

    @api.model
    def _unknown_brand(self):
        Category = self.env['product.category']
        return (Category.search([('name', '=', 'Sin marca'), ('parent_id', '=', False)], limit=1)
                or Category.create({'name': 'Sin marca'}))

    @api.model
    def _new_template_vals(self, model, name, brand, tracked):
        """Producto nuevo a partir de un artículo de Sage: referencia sin el
        prefijo de marca, categoría de marca de primer nivel, almacenable y
        con nº de serie si en Sage lo lleva."""
        return {
            'name': name, 'default_code': model, 'categ_id': brand.id,
            'type': 'consu', 'is_storable': True,
            'tracking': 'serial' if tracked else 'none',
            'company_id': False,
        }

    @api.model
    def _article_template(self, article, model=None):
        """Producto que ya corresponde a un artículo del maestro de Sage:
        primero los enlaces hechos (alias), después la referencia. Mira
        también los archivados para no crear nunca un duplicado.
        {'model', 'template', 'status': missing | exists | archived | ambiguous}"""
        model = (model or article_parts(self.env, article.code)[0]).strip()
        codes = list({normalize_code(model), normalize_code(article.code)} - {''})
        Template = self.env['product.template'].sudo().with_context(active_test=False)
        found = self.env['rms.sage.article.map'].sudo().search(
            [('article_code', 'in', codes)]).with_context(active_test=False).product_tmpl_id
        if not found:
            found = Template.search([('default_code', '=ilike', model)], limit=3)
        active = found.filtered('active')
        if len(active) == 1:
            return {'model': model, 'template': active, 'status': 'exists'}
        if active:
            return {'model': model, 'template': Template.browse(), 'status': 'ambiguous'}
        if found:
            return {'model': model, 'template': found[:1], 'status': 'archived'}
        return {'model': model, 'template': Template.browse(), 'status': 'missing'}

    @api.model
    def _create_from_article(self, article, by_quantity=False):
        """Crea el producto de un artículo del maestro de Sage que no tiene
        existencias (no hay líneas de las que partir), igual que
        action_create_products: nombre y marca del maestro, alias apuntado y
        líneas de Sage de ese artículo enlazadas. Quien llama comprueba el
        permiso; aquí se crea con sudo()."""
        info = self._article_template(article)
        if info['status'] != 'missing':
            return info['template']
        model = info['model']
        sudo = self.sudo()
        brand_id = self.env['rms.sage.article'].sudo()._brands_by_article([article.code]).get(
            article.code_normalized)
        brand = self.env['product.category'].sudo().browse(brand_id) if brand_id else sudo._unknown_brand()
        template = self.env['product.template'].sudo().create(
            self._new_template_vals(model, article.name or model, brand, not by_quantity))
        Map = self.env['rms.sage.article.map'].sudo()
        code = normalize_code(article.code)
        if code and not Map.search_count([('article_code', '=', code)], limit=1):
            Map.create({'article_code': code, 'product_tmpl_id': template.id})
        lines = self.env['rms.sage.stock.line'].sudo().search(
            ['|', ('article_normalized', '=', code), ('model_normalized', '=', normalize_code(model))])
        if lines:
            lines._resolve_products()
            self.env['rms.stock.count.scan'].sudo()._refresh_sage_suggestions(
                lines.filtered('is_current').mapped('serial_normalized'))
        return template.with_env(self.env)

    @api.model
    def _products_to_track(self, lines):
        """Productos de las líneas que en Sage llevan nº de serie unitario y en
        Odoo no se siguen por nº de serie."""
        serial_lines = lines.filtered(
            lambda l: l.is_current and l.product_id and l.serial_normalized and l.quantity == 1)
        return serial_lines.product_id.product_tmpl_id.filtered(lambda t: t.tracking != 'serial')

    def action_enable_serial_tracking(self):
        """Activa almacenable + seguimiento por nº de serie. Se salta los
        productos que ya tienen existencias sin nº de serie en Odoo (cambiar
        el seguimiento con stock dejaría cantidades sin nº de serie)."""
        self.ensure_one()
        templates = self._products_to_track(self.line_ids)
        if not templates:
            raise UserError("No hay productos que activar en las líneas elegidas.")
        quants = self.env['stock.quant'].sudo().search([
            ('product_id.product_tmpl_id', 'in', templates.ids), ('quantity', '!=', 0),
            ('location_id.usage', '=', 'internal')])
        with_stock = quants.product_id.product_tmpl_id
        todo = templates - with_stock
        if todo:
            todo.write({'is_storable': True, 'tracking': 'serial'})
        message = "Activado el seguimiento por nº de serie en %d productos." % len(todo)
        if with_stock:
            message += " No se han tocado %d con existencias en Odoo: %s" % (
                len(with_stock), ", ".join(with_stock[:10].mapped('display_name')))
        return self._notify("Seguimiento por nº de serie", message)

    def _notify(self, title, message):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': title, 'message': message, 'sticky': True, 'type': 'success',
                           'next': {'type': 'ir.actions.act_window_close'}}}


class SageStockLine(models.Model):
    _inherit = 'rms.sage.stock.line'

    def action_prepare_products(self):
        """Abre el asistente con las líneas seleccionadas (o todas las vigentes
        sin producto si no se ha elegido ninguna)."""
        lines = self or self.search([('is_current', '=', True), ('match_state', '!=', 'ok')])
        return {
            'type': 'ir.actions.act_window', 'name': 'Preparar productos desde Sage',
            'res_model': 'rms.sage.product.prepare', 'view_mode': 'form',
            'views': [(False, 'form')], 'target': 'new',
            'context': {'default_line_ids': [(6, 0, lines.ids)]},
        }
