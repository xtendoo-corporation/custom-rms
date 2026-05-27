# -*- coding: utf-8 -*-

import base64
import io
import logging
import datetime

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import xlrd
except ImportError:
    xlrd = None

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class QuotationImportWizard(models.TransientModel):
    _name = 'rms.quotation.import.wizard'
    _description = 'Wizard for Importing Quotations from Excel'

    file = fields.Binary('Archivo Excel', required=True)
    filename = fields.Char('Nombre de Archivo')

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Por favor, sube un archivo Excel."))

        file_data = base64.b64decode(self.file)
        
        # 1. Parse Excel file
        if openpyxl and self.filename and self.filename.endswith('.xlsx'):
            wb = openpyxl.load_workbook(filename=io.BytesIO(file_data), data_only=True)
            sheet = wb.active
            rows = sheet.iter_rows(values_only=True)
            header = next(rows)
            data_rows = list(rows)
        elif xlrd and self.filename and self.filename.endswith('.xls'):
            wb = xlrd.open_workbook(file_contents=file_data)
            sheet = wb.sheet_by_index(0)
            header = sheet.row_values(0)
            data_rows = [sheet.row_values(rx) for rx in range(1, sheet.nrows)]
        else:
            raise UserError(_("Formato de archivo no soportado o falta la librería openpyxl/xlrd. Sube un archivo .xlsx o .xls"))

        if not header:
            raise UserError(_("El archivo Excel está vacío o no contiene cabeceras."))

        # 2. Map headers using lowercased fuzzy search
        header_map = {str(k).strip().lower(): v for v, k in enumerate(header) if k}

        def get_row_val(row, *keywords):
            for kw in keywords:
                for h_name, idx in header_map.items():
                    if kw in h_name:
                        val = row[idx]
                        return val
            return None

        # Group data into orders
        orders_dict = {}
        
        # Keep track of carry-over values for consecutive lines belonging to the same order
        last_order_ref = ''
        last_partner = ''
        last_date = None
        last_comercial = ''
        last_total = 0.0

        for row in data_rows:
            if not row or not any(row):
                continue

            # Extract fields
            order_ref_raw = get_row_val(row, 'referencia', 'pedido', 'referencia_pedido', 'presupuesto')
            order_ref = str(order_ref_raw).strip() if order_ref_raw is not None else ''

            partner_raw = get_row_val(row, 'cif cliente', 'cliente', 'partner', 'nif', 'cif')
            partner_val = str(partner_raw).strip() if partner_raw is not None else ''

            date_raw = get_row_val(row, 'fecha creación', 'fecha', 'date')
            comercial_raw = get_row_val(row, 'comercial', 'vendedor', 'salesperson')
            comercial_val = str(comercial_raw).strip() if comercial_raw is not None else ''

            total_raw = get_row_val(row, 'total presupuesto', 'total de documento', 'total_documento', 'total_doc', 'total')
            try:
                total_val = float(total_raw) if total_raw is not None else 0.0
            except ValueError:
                total_val = 0.0

            # Carry over values if blank BEFORE skipping any check on product/description!
            if not order_ref:
                order_ref = last_order_ref
            else:
                last_order_ref = order_ref

            if not partner_val:
                partner_val = last_partner
            else:
                last_partner = partner_val

            if date_raw is None:
                date_val = last_date
            else:
                date_val = self._parse_date(date_raw)
                last_date = date_val

            if not comercial_val:
                comercial_val = last_comercial
            else:
                last_comercial = comercial_val

            if total_val == 0.0:
                total_val = last_total
            else:
                last_total = total_val

            # Line level values
            product_ref_raw = get_row_val(row, 'producto', 'referencia_producto', 'ref', 'código', 'product')
            product_ref = str(product_ref_raw).strip() if product_ref_raw is not None else ''

            desc_raw = get_row_val(row, 'definición', 'descripcion', 'artículo', 'description', 'name')
            description = str(desc_raw).strip() if desc_raw is not None else ''

            if not product_ref and not description:
                # Skip row if it has neither a product nor a description
                continue

            qty_raw = get_row_val(row, 'cantidad', 'cant', 'qty', 'uom_qty')
            try:
                qty = float(qty_raw) if qty_raw is not None else (1.0 if product_ref else 0.0)
            except ValueError:
                qty = 1.0 if product_ref else 0.0

            price_raw = get_row_val(row, 'precio unitario', 'precio', 'price_unit', 'unitario', 'price')
            has_price = False
            price = 0.0
            if price_raw is not None and str(price_raw).strip() != '':
                try:
                    price = float(price_raw)
                    has_price = True
                except ValueError:
                    price = 0.0

            d1_raw = get_row_val(row, 'dto1', 'dto 1', 'descuento1', 'discount1')
            try:
                d1 = float(d1_raw) if d1_raw is not None else 0.0
            except ValueError:
                d1 = 0.0

            d2_raw = get_row_val(row, 'dto2', 'dto 2', 'descuento2', 'discount2')
            try:
                d2 = float(d2_raw) if d2_raw is not None else 0.0
            except ValueError:
                d2 = 0.0

            d3_raw = get_row_val(row, 'dto3', 'dto 3', 'descuento3', 'discount3')
            try:
                d3 = float(d3_raw) if d3_raw is not None else 0.0
            except ValueError:
                d3 = 0.0

            # Initialize order in dict
            if order_ref not in orders_dict:
                orders_dict[order_ref] = {
                    'partner_val': partner_val,
                    'date': date_val,
                    'comercial_val': comercial_val,
                    'total_documento': total_val,
                    'lines': []
                }
            elif total_val > 0.0 and orders_dict[order_ref].get('total_documento', 0.0) == 0.0:
                orders_dict[order_ref]['total_documento'] = total_val

            orders_dict[order_ref]['lines'].append({
                'product_ref': product_ref,
                'qty': qty,
                'price': price,
                'has_price': has_price,
                'discount1': d1,
                'discount2': d2,
                'discount3': d3,
                'description': description
            })

        if not orders_dict:
            raise UserError(_("No se encontraron líneas de pedido válidas para importar en el archivo."))

        # Process each order
        DiscountProduct = self.env['product.product']
        discount_product = DiscountProduct.search([('default_code', '=', 'DESCUENTO')], limit=1)
        if not discount_product:
            discount_product = DiscountProduct.search([('type', '=', 'service')], limit=1)
        if not discount_product:
            discount_product = DiscountProduct.create({
                'name': 'Descuento Comercial',
                'type': 'service',
                'default_code': 'DESCUENTO',
                'list_price': 0.0,
            })

        # PERFORMANCE OPTIMIZATION: Collect unique values and pre-fetch them in bulk
        unique_partners = set()
        unique_comerciales = set()
        unique_products = set()
        for ref, o_data in orders_dict.items():
            if o_data.get('partner_val'):
                unique_partners.add(o_data['partner_val'].strip())
            if o_data.get('comercial_val'):
                unique_comerciales.add(o_data['comercial_val'].strip())
            for line in o_data.get('lines', []):
                if line.get('product_ref'):
                    unique_products.add(line['product_ref'].strip())

        # Bulk pre-fetch Partners
        partner_cache = {}
        if unique_partners:
            partners = self.env['res.partner'].search([
                '|', ('vat', 'in', list(unique_partners)), ('name', 'in', list(unique_partners))
            ])
            for p in partners:
                if p.vat:
                    partner_cache[p.vat.strip()] = p
                if p.name:
                    partner_cache[p.name.strip()] = p

        # Bulk pre-fetch Comerciales
        salesperson_cache = {}
        if unique_comerciales:
            users = self.env['res.users'].search([
                '|', ('name', 'in', list(unique_comerciales)), ('partner_id.name', 'in', list(unique_comerciales))
            ])
            for u in users:
                if u.name:
                    salesperson_cache[u.name.strip()] = u.id
                if u.partner_id and u.partner_id.name:
                    salesperson_cache[u.partner_id.name.strip()] = u.id

        # Bulk pre-fetch Products
        product_cache = {}
        pre_fetched_products = {}
        if unique_products:
            clean_refs = set()
            for ref in unique_products:
                clean_ref = ref
                if ref.startswith('2M-'):
                    clean_ref = ref[3:].strip()
                elif ref.startswith('D-'):
                    clean_ref = ref[2:].strip()
                clean_refs.add(clean_ref)
                clean_refs.add(ref)

            products = self.env['product.product'].search([
                '|', ('default_code', 'in', list(clean_refs)), ('barcode', 'in', list(clean_refs))
            ])
            for p in products:
                if p.default_code:
                    pre_fetched_products.setdefault(p.default_code.strip(), []).append(p)
                if p.barcode:
                    pre_fetched_products.setdefault(p.barcode.strip(), []).append(p)
        order_model = self.env['sale.order'].with_context(
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
            tracking_disable=True
        )
        created_orders = self.env['sale.order']
        missing_partners = set()
        missing_products = set()

        for ref, o_data in orders_dict.items():
            # 1. Resolve Customer
            partner = self._find_partner(o_data['partner_val'], partner_cache=partner_cache)
            if not partner:
                missing_partners.add(o_data['partner_val'])
                continue

            # 2. Resolve Salesperson
            user_id = self._find_salesperson(o_data['comercial_val'], salesperson_cache=salesperson_cache) or self.env.user.id

            # 3. Resolve Products first so we can check if they are missing and get pricelist rules
            resolved_lines = []
            has_missing = False
            for l in o_data['lines']:
                if l['product_ref']:
                    product = self._find_product_variant(l['product_ref'], product_cache=product_cache, pre_fetched_products=pre_fetched_products)
                    if not product:
                        missing_products.add(l['product_ref'])
                        has_missing = True
                        continue
                    resolved_lines.append((product, l))
                else:
                    # Note/Section/Description-only line
                    resolved_lines.append((False, l))

            if has_missing:
                continue

            # 4. Apply Excel-provided Discounts (Dto1 and Dto2) and leave Dto3 in 0
            pricelist = partner.property_product_pricelist
            order_date = o_data['date'] or fields.Datetime.now()
            
            lines_with_discounts = []
            for product, l in resolved_lines:
                if product:
                    # Determine base price before discounts
                    excel_price = l['price']
                    has_price = l.get('has_price', False)
                    price_unit = excel_price if has_price else product.list_price
                    
                    lines_with_discounts.append((product, {
                        'qty': l['qty'],
                        'price': price_unit,
                        'discount1': l['discount1'],
                        'discount2': l['discount2'],
                        'discount3': l['discount3'],
                        'pricelist_item_id': False,
                        'description': l['description'],
                    }))
                else:
                    # Keep note line as is
                    lines_with_discounts.append((False, l))

            # 5. Calculate Discount amount to square the budget total
            sum_intermediate = 0.0
            for product, l in lines_with_discounts:
                if product:
                    sum_intermediate += l['qty'] * l['price'] * (1.0 - l['discount1']/100.0) * (1.0 - l['discount2']/100.0) * (1.0 - l['discount3']/100.0)
            
            target_total = o_data['total_documento']
            discount_line_vals = {}
            if target_total > 0.0 and sum_intermediate > 0.0:
                # Determine if target_total includes VAT
                if target_total > sum_intermediate * 1.05:
                    untaxed_target = target_total / 1.21
                else:
                    untaxed_target = target_total
                
                if sum_intermediate > untaxed_target:
                    discount_amount = round(sum_intermediate - untaxed_target, 2)
                    if discount_amount >= 0.01:
                        discount_line_vals = {
                            'product_id': discount_product.id,
                            'name': _('Descuento comercial para cuadrar presupuesto'),
                            'product_uom_qty': 1.0,
                            'price_unit': -discount_amount,
                        }

            # 6. Create Sale Order (Quotation)
            order_vals = {
                'name': ref,  # Set the quotation number exactly as in the Excel sheet
                'partner_id': partner.id,
                'pricelist_id': pricelist.id if pricelist else False,
                'date_order': order_date,
                'user_id': user_id,
                'client_order_ref': ref,
            }

            order = order_model.create(order_vals)
            created_orders |= order

            # 7. Create Lines
            line_model = self.env['sale.order.line'].with_context(
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notrack=True,
                tracking_disable=True
            )
            line_fields = line_model._fields
            
            for product, l in lines_with_discounts:
                if product:
                    line_vals = {
                        'order_id': order.id,
                        'product_id': product.id,
                        'product_uom_qty': l['qty'],
                        'price_unit': l['price'],
                        'name': l['description'] or product.get_product_multiline_description_sale(),
                    }
                    
                    # Apply Discounts (Dto1, Dto2, and Dto3)
                    if 'discount1' in line_fields:
                        line_vals['discount1'] = l['discount1']
                        line_vals['discount2'] = l['discount2']
                        if 'discount3' in line_fields:
                            line_vals['discount3'] = l['discount3']
                        
                        # Set Odoo's standard combined discount field to avoid it being recalculated incorrectly
                        combined_disc = (1.0 - (1.0 - l['discount1']/100.0) * (1.0 - l['discount2']/100.0) * (1.0 - l.get('discount3', 0.0)/100.0)) * 100.0
                        line_vals['discount'] = round(combined_disc, 4)
                    elif 'discount' in line_fields:
                        combined_disc = (1.0 - (1.0 - l['discount1']/100.0) * (1.0 - l['discount2']/100.0) * (1.0 - l.get('discount3', 0.0)/100.0)) * 100.0
                        line_vals['discount'] = round(combined_disc, 4)
                        
                    line_model.create(line_vals)
                else:
                    # Note/Description-only line
                    line_vals = {
                        'order_id': order.id,
                        'display_type': 'line_note',
                        'name': l['description'],
                    }
                    line_model.create(line_vals)

            # 8. Create Adjustment Discount Line if necessary
            if discount_line_vals:
                # Retrieve the tax ids from the first product line to apply them to the discount line
                tax_ids = []
                for line in order.order_line:
                    if line.tax_ids:
                        tax_ids = line.tax_ids.ids
                        break
                
                discount_line_vals.update({
                    'order_id': order.id,
                })
                if tax_ids:
                    discount_line_vals['tax_ids'] = [(6, 0, tax_ids)]
                
                line_model.create(discount_line_vals)



        # Handle errors/notifications
        if missing_partners or missing_products:
            error_msg = []
            if missing_partners:
                error_msg.append(_("Clientes no encontrados (CIF o Nombre): %s") % ", ".join(list(missing_partners)))
            if missing_products:
                error_msg.append(_("Referencias de producto no encontradas: %s") % ", ".join(list(missing_products)))
            
            raise UserError("\n".join(error_msg))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Importación Completada'),
                'message': _('Se han creado %d presupuestos exitosamente.') % len(created_orders),
                'sticky': False,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _parse_date(self, date_val):
        if not date_val:
            return False
        if isinstance(date_val, (int, float)):
            # Excel date serial
            if openpyxl:
                return openpyxl.utils.datetime.from_excel(date_val)
            return False
        if isinstance(date_val, (datetime.datetime, datetime.date)):
            return date_val
        if isinstance(date_val, str):
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y', '%m/%d/%Y'):
                try:
                    return datetime.datetime.strptime(date_val.strip(), fmt)
                except ValueError:
                    continue
        return False

    def _find_partner(self, partner_val, partner_cache=None):
        if not partner_val:
            return False
        partner_val = partner_val.strip()
        
        # Check cache
        if partner_cache is not None and partner_val in partner_cache:
            return partner_cache[partner_val]
            
        Partner = self.env['res.partner']
        partner = False
        
        # 1. Match by VAT/NIF
        partner_res = Partner.search([('vat', '=', partner_val)], limit=1)
        if partner_res:
            partner = partner_res
        else:
            # 2. Match by exact name (case-insensitive)
            partner_res = Partner.search([('name', '=ilike', partner_val)], limit=1)
            if partner_res:
                partner = partner_res
            else:
                # 3. Match by partial name (ilike)
                partner_res = Partner.search([('name', 'ilike', partner_val)], limit=1)
                if partner_res:
                    partner = partner_res
                    
        if partner_cache is not None:
            partner_cache[partner_val] = partner
        return partner

    def _find_salesperson(self, comercial_val, salesperson_cache=None):
        if not comercial_val:
            return False
        comercial_val = comercial_val.strip()
        
        # Check cache
        if salesperson_cache is not None and comercial_val in salesperson_cache:
            return salesperson_cache[comercial_val]
            
        User = self.env['res.users']
        user_id = False
        
        # 1. Match by User name
        user = User.search([('name', '=ilike', comercial_val)], limit=1)
        if user:
            user_id = user.id
        else:
            # 2. Match by Partner name
            user = User.search([('partner_id.name', '=ilike', comercial_val)], limit=1)
            if user:
                user_id = user.id
                
        if salesperson_cache is not None:
            salesperson_cache[comercial_val] = user_id
        return user_id

    def _find_product_variant(self, original_ref, product_cache=None, pre_fetched_products=None):
        if not original_ref:
            return False
        original_ref = original_ref.strip()
        
        # Check cache
        if product_cache is not None and original_ref in product_cache:
            return product_cache[original_ref]
            
        clean_ref = original_ref
        estado_val = 'Nuevo'
        
        if original_ref.startswith('2M-'):
            clean_ref = original_ref[3:].strip()
            estado_val = '2 Mano'
        elif original_ref.startswith('D-'):
            clean_ref = original_ref[2:].strip()
            estado_val = 'Demo'
            
        # Get variants from pre-fetched pool if available, otherwise search DB
        variants = []
        if pre_fetched_products is not None:
            variants = pre_fetched_products.get(clean_ref) or []
            if not variants:
                variants = pre_fetched_products.get(original_ref) or []
                
        if not variants:
            # Fallback to DB search
            Product = self.env['product.product']
            variants = Product.search([('default_code', '=', clean_ref)])
            if not variants:
                variants = Product.search([('default_code', '=', original_ref)])
                
        variant_res = False
        if variants:
            if len(variants) == 1:
                variant_res = variants[0]
            else:
                # 3. If multiple variants, filter by 'Estado' attribute
                for variant in variants:
                    for ptav in variant.product_template_attribute_value_ids:
                        if ptav.attribute_id.name == 'Estado' and ptav.product_attribute_value_id.name == estado_val:
                            variant_res = variant
                            break
                    if variant_res:
                        break
                        
                # 4. Fallback to 'Nuevo' variant
                if not variant_res and estado_val != 'Nuevo':
                    for variant in variants:
                        for ptav in variant.product_template_attribute_value_ids:
                            if ptav.attribute_id.name == 'Estado' and ptav.product_attribute_value_id.name == 'Nuevo':
                                variant_res = variant
                                break
                        if variant_res:
                            break
                            
                # 5. Last resort fallback
                if not variant_res:
                    variant_res = variants[0]
                    
        if product_cache is not None:
            product_cache[original_ref] = variant_res
        return variant_res

    def _calculate_discount3(self, lines_data, target_total):
        if not target_total or target_total <= 0.0:
            return 0.0
            
        sum_intermediate = 0.0
        for product, line in lines_data:
            if not product:
                continue
            qty = line['qty']
            price = line['price']
            d1 = line['discount1']
            d2 = line['discount2']
            sum_intermediate += qty * price * (1.0 - d1/100.0) * (1.0 - d2/100.0)
            
        if sum_intermediate <= 0.0:
            return 0.0
            
        # Determine if target_total includes VAT
        # Check if the target total from Excel is greater than the intermediate total.
        # Since a discount is reductive, untaxed target total is <= intermediate total.
        # If target_total is significantly greater, it has tax (standard 21% in Spain).
        if target_total > sum_intermediate * 1.05:
            untaxed_target = target_total / 1.21
        else:
            untaxed_target = target_total
            
        if untaxed_target >= sum_intermediate:
            return 0.0
            
        discount3 = (1.0 - (untaxed_target / sum_intermediate)) * 100.0
        return max(0.0, min(100.0, round(discount3, 4)))
