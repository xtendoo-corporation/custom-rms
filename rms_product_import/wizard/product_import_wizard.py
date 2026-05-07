import base64
import io
import logging
import re
import openpyxl
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ProductImportWizard(models.TransientModel):
    _name = 'product.import.wizard'
    _description = 'Product Import Wizard'

    excel_file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')

    def action_import(self):
        self.ensure_one()
        if not self.excel_file:
            raise UserError(_("Please upload an Excel file."))

        try:
            file_data = base64.b64decode(self.excel_file)
            wb = openpyxl.load_workbook(io.BytesIO(file_data), data_only=True)
            sheet = wb.active
        except Exception as e:
            raise UserError(_("Invalid file. Error: %s") % str(e))

        # Map headers
        header_raw = [cell.value for cell in sheet[1]]
        header = [str(v).strip().lower() if v else '' for v in header_raw]
        try:
            brand_idx = header.index('marca')
            ref_idx = header.index('referencia')
            name_idx = header.index('articulo')
            desc_idx = header.index('descripcion')
            family_idx = header.index('familia')
            subfamily_idx = header.index('subfamilia')
            vendible_idx = header.index('vendible')
        except ValueError as e:
            raise UserError(_("Missing column in Excel: %s") % str(e))

        provider_idx = header.index('proveedor') if 'proveedor' in header else -1
        purchase_price_idx = header.index('precio de compra') if 'precio de compra' in header else -1
        sale_price_idx = header.index('precio de venta') if 'precio de venta' in header else -1

        # Group rows by Clean Reference
        product_groups = {}
        supplier_names = set()

        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            
            original_ref = str(row[ref_idx] or '').strip()
            if not original_ref:
                continue

            clean_ref = original_ref
            estado_val = 'Nuevo'
            if original_ref.startswith('2M-'):
                clean_ref = original_ref[3:].strip()
                estado_val = '2 Mano'
            elif original_ref.startswith('D-'):
                clean_ref = original_ref[2:].strip()
                estado_val = 'Demo'

            if clean_ref not in product_groups:
                product_groups[clean_ref] = []
            
            product_groups[clean_ref].append({
                'original_ref': original_ref,
                'estado_val': estado_val,
                'data': row
            })

            if provider_idx >= 0:
                p_name = str(row[provider_idx] or '').strip()
                if p_name:
                    supplier_names.add(p_name)

        # Statistics
        created_count = 0
        updated_count = 0

        # OPTIMIZATION: Caches to prevent CPU timeout from 1000s of SQL reads
        categ_cache = {}
        attr_cache = {}
        attr_val_cache = {}
        
        # Prefetch templates
        all_codes = list(product_groups.keys())
        existing_tmpls = self.env['product.template'].search([('default_code', 'in', all_codes)])
        tmpl_by_code = {t.default_code: t for t in existing_tmpls if t.default_code}

        # Prefetch partners
        existing_partners = self.env['res.partner'].search([('name', 'in', list(supplier_names))])
        partner_by_name_lower = {p.name.strip().lower(): p for p in existing_partners if p.name}

        for clean_ref, rows in product_groups.items():
            # 1. Identify "Base Row" (preferably 'Nuevo')
            base_row_data = next((r for r in rows if r['estado_val'] == 'Nuevo'), rows[0])
            base_row = base_row_data['data']

            base_sale_price = float(base_row[sale_price_idx] or 0.0) if sale_price_idx >= 0 else 0.0
            base_purchase_price = float(base_row[purchase_price_idx] or 0.0) if purchase_price_idx >= 0 else 0.0

            # 2. Categories (from Base Row)
            brand_name = str(base_row[brand_idx] or '').strip()
            family_name = str(base_row[family_idx] or '').strip()
            subfamily_name = str(base_row[subfamily_idx] or '').strip()
            target_categ = self._get_or_create_categories(brand_name, family_name, subfamily_name, categ_cache)

            # 3. Handle Attributes (Create them if missing)
            attr_estado = self._get_or_create_attribute('Estado', attr_cache)
            attr_2mv = self._get_or_create_attribute('2MV', attr_cache)

            # 4. Create/Update Product Template
            product_tmpl = tmpl_by_code.get(clean_ref)
            
            # Clean base name (remove "2ª Mano" etc.)
            base_name = self._cleanup_base_name(str(base_row[name_idx] or clean_ref).strip())
            
            tmpl_vals = {
                'name': base_name,
                'default_code': clean_ref,
                'description': str(base_row[desc_idx] or '').strip(),
                'list_price': base_sale_price,
                'standard_price': base_purchase_price,
                'categ_id': target_categ.id,
                'purchase_ok': True,
                'sale_ok': True,
            }

            if product_tmpl:
                product_tmpl.write(tmpl_vals)
                updated_count += 1
            else:
                product_tmpl = self.env['product.template'].create(tmpl_vals)
                tmpl_by_code[clean_ref] = product_tmpl
                created_count += 1

            # 5. Ensure Attribute Lines exist for the Template
            all_states_in_group = [r['estado_val'] for r in rows]
            self._update_template_attribute_lines(product_tmpl, attr_estado, all_states_in_group, attr_val_cache)
            
            # 6. Process each Variant specific data
            for r in rows:
                row = r['data']
                estado_val = r['estado_val']
                
                # Attribute Value
                estado_attr_val = self._get_or_create_attribute_value(attr_estado, estado_val, attr_val_cache)
                
                # Find the specific Variant (Product Product)
                variant = self._get_variant_from_template(product_tmpl, estado_attr_val)
                if not variant:
                    continue

                variant_sale_price = float(row[sale_price_idx] or 0.0) if sale_price_idx >= 0 else 0.0
                variant_purchase_price = float(row[purchase_price_idx] or 0.0) if purchase_price_idx >= 0 else 0.0

                # Update Variant individual reference and cost
                variant_vals = {
                    'default_code': clean_ref,
                    'standard_price': variant_purchase_price,
                }
                variant.write(variant_vals)

                # Set Price Extra for the variant
                price_extra = variant_sale_price - base_sale_price
                self._update_attribute_price_extra(product_tmpl, estado_attr_val, price_extra)

                # Handle 2MV attribute
                if str(row[vendible_idx]).strip() == '01':
                    self._get_or_create_attribute_value(attr_2mv, 'Vendible', attr_val_cache)
                    self._update_template_attribute_lines(product_tmpl, attr_2mv, ['Vendible'], attr_val_cache)

                # Update Supplier Info
                if provider_idx >= 0:
                    provider_name = str(row[provider_idx] or '').strip()
                    if provider_name:
                        partner = partner_by_name_lower.get(provider_name.lower())
                        if partner:
                            supplier_info = self.env['product.supplierinfo'].search([
                                ('product_id', '=', variant.id),
                                ('partner_id', '=', partner.id)
                            ], limit=1)
                            if supplier_info:
                                supplier_info.write({'price': variant_purchase_price})
                            else:
                                self.env['product.supplierinfo'].create({
                                    'partner_id': partner.id,
                                    'product_id': variant.id,
                                    'product_tmpl_id': product_tmpl.id,
                                    'price': variant_purchase_price,
                                })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Completed'),
                'message': _('%s product templates processed.') % len(product_groups),
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _cleanup_base_name(self, name):
        patterns = [
            r'\.?\s*2ª\s*Mano\.?',
            r'\s*SEGUNDA\s*MANO',
            r'\s*\(Nuevo\)',
            r'\s*-\s*Nuevo',
            r'\s*Demo',
        ]
        for pattern in patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        return name.strip()

    def _get_or_create_categories(self, brand, family, subfamily, categ_cache):
        cache_key = (brand, family, subfamily)
        if cache_key in categ_cache:
            return categ_cache[cache_key]

        parent_id = False
        if brand:
            brand_categ = self.env['product.category'].search([('name', '=', brand)], limit=1)
            if not brand_categ:
                brand_categ = self.env['product.category'].create({'name': brand})
            parent_id = brand_categ.id
        
        if family:
            family_categ = self.env['product.category'].search([('name', '=', family), ('parent_id', '=', parent_id)], limit=1)
            if not family_categ:
                family_categ = self.env['product.category'].create({'name': family, 'parent_id': parent_id})
            parent_id = family_categ.id
            
        if subfamily:
            subfamily_categ = self.env['product.category'].search([('name', '=', subfamily), ('parent_id', '=', parent_id)], limit=1)
            if not subfamily_categ:
                subfamily_categ = self.env['product.category'].create({'name': subfamily, 'parent_id': parent_id})
            parent_id = subfamily_categ.id
            
        result = self.env['product.category'].browse(parent_id) if parent_id else self.env.ref('product.product_category_all')
        categ_cache[cache_key] = result
        return result

    def _get_or_create_attribute(self, name, attr_cache):
        if name in attr_cache:
            return attr_cache[name]
        attr = self.env['product.attribute'].search([('name', '=', name)], limit=1)
        if not attr:
            attr = self.env['product.attribute'].create({
                'name': name,
                'create_variant': 'always' if name == 'Estado' else 'no_variant'
            })
        attr_cache[name] = attr
        return attr

    def _get_or_create_attribute_value(self, attribute, value_name, attr_val_cache):
        cache_key = (attribute.id, value_name)
        if cache_key in attr_val_cache:
            return attr_val_cache[cache_key]
        val = self.env['product.attribute.value'].search([('attribute_id', '=', attribute.id), ('name', '=', value_name)], limit=1)
        if not val:
            val = self.env['product.attribute.value'].create({'attribute_id': attribute.id, 'name': value_name})
        attr_val_cache[cache_key] = val
        return val

    def _update_template_attribute_lines(self, product_tmpl, attribute, value_names, attr_val_cache):
        line = self.env['product.template.attribute.line'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('attribute_id', '=', attribute.id)
        ], limit=1)
        
        value_ids = []
        for name in value_names:
            value_ids.append(self._get_or_create_attribute_value(attribute, name, attr_val_cache).id)
            
        if line:
            existing_values = line.value_ids.ids
            new_values = list(set(existing_values + value_ids))
            line.write({'value_ids': [(6, 0, new_values)]})
        else:
            self.env['product.template.attribute.line'].create({
                'product_tmpl_id': product_tmpl.id,
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, value_ids)]
            })

    def _get_variant_from_template(self, product_tmpl, attribute_value):
        return self.env['product.product'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('product_template_attribute_value_ids.product_attribute_value_id', '=', attribute_value.id)
        ], limit=1)

    def _update_attribute_price_extra(self, product_tmpl, attribute_value, price_extra):
        ptav = self.env['product.template.attribute.value'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('product_attribute_value_id', '=', attribute_value.id)
        ], limit=1)
        if ptav:
            ptav.write({'price_extra': price_extra})
