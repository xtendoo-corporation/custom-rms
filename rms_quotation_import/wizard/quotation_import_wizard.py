# -*- coding: utf-8 -*-

import base64
import io
import logging
import datetime
import math
import re
from itertools import islice

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

        if len(self.file) > ((20 * 1024 * 1024 + 2) // 3) * 4:
            raise UserError(_("El archivo supera el límite de 20 MB."))
        file_data = base64.b64decode(self.file)
        if len(file_data) > 20 * 1024 * 1024:
            raise UserError(_("El archivo supera el límite de 20 MB."))
        
        # 1. Parse Excel file
        if openpyxl and self.filename and self.filename.endswith('.xlsx'):
            wb = openpyxl.load_workbook(filename=io.BytesIO(file_data), data_only=True, read_only=True)
            sheet = wb.active
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            data_rows = list(islice(rows, 50001))
            wb.close()
        elif xlrd and self.filename and self.filename.endswith('.xls'):
            wb = xlrd.open_workbook(file_contents=file_data)
            sheet = wb.sheet_by_index(0)
            if sheet.nrows > 50001:
                raise UserError(_("El archivo supera el límite de 50.000 filas."))
            header = sheet.row_values(0) if sheet.nrows else None
            data_rows = [sheet.row_values(rx) for rx in range(1, sheet.nrows)]
        else:
            raise UserError(_("Formato de archivo no soportado o falta la librería openpyxl/xlrd. Sube un archivo .xlsx o .xls"))

        if len(data_rows) > 50000:
            raise UserError(_("El archivo supera el límite de 50.000 filas."))

        if not header:
            raise UserError(_("El archivo Excel está vacío o no contiene cabeceras."))

        # 2. Map headers using lowercased fuzzy search
        header_map = {str(k).strip().lower(): v for v, k in enumerate(header) if k}

        normalized_headers = [str(h).strip().lower() for h in header if h]
        if len(normalized_headers) != len(set(normalized_headers)):
            raise UserError(_("Cabeceras duplicadas: renombre las columnas para que sean inequívocas."))

        def get_row_val(row, *keywords, exclude=None):
            eligible = {name: idx for name, idx in header_map.items()
                        if not exclude or not any(ex in name for ex in exclude)}
            matches = {idx for name, idx in eligible.items() if name in keywords}
            if not matches:
                matches = {idx for name, idx in eligible.items()
                           if any(kw in name for kw in keywords)}
            if len(matches) > 1:
                raise UserError(_("Cabeceras ambiguas para %s: renombre las columnas.") % keywords[0])
            return row[next(iter(matches))] if matches else None

        # Las referencias de pedido y producto deben tener columnas distintas.
        def reference_column(names):
            matches = [i for i, h in enumerate(header)
                       if h and str(h).strip().lower() in names]
            if len(matches) > 1:
                raise UserError(_("Cabeceras ambiguas: renombre las columnas de pedido y producto."))
            return matches[0] if matches else None

        order_column = reference_column({'pedido', 'referencia_pedido', 'referencia pedido',
                                         'presupuesto', 'referencia presupuesto'})
        product_column = reference_column({'referencia_producto', 'referencia producto',
                                           'código producto', 'codigo producto', 'código', 'codigo', 'ref'})
        generic_column = reference_column({'referencia'})
        if generic_column is not None:
            if order_column is None and product_column is not None:
                order_column = generic_column
            elif product_column is None and order_column is not None:
                product_column = generic_column
            else:
                raise UserError(_("Referencia es ambigua: renombre las columnas como Pedido y Referencia producto."))
        if order_column is None:
            raise UserError(_("Falta una columna inequívoca de Pedido o Referencia pedido."))
        has_dedicated_ref_column = product_column is not None

        # Group data into orders
        orders_dict = {}
        
        # Keep track of carry-over values for consecutive lines belonging to the same order
        last_order_ref = ''
        last_partner = ''
        last_date = None
        last_comercial = ''
        last_total = 0.0

        for row_number, row in enumerate(data_rows, start=2):
            if not row or not any(row):
                continue

            # Extract fields
            order_ref_raw = row[order_column]
            order_ref = str(order_ref_raw).strip() if order_ref_raw is not None else ''

            # Try to get CIF/NIF first, then fall back to Cliente/Partner name (excluding columns with CIF/NIF), and finally use the original unified keywords list
            partner_raw = get_row_val(row, 'cif cliente', 'nif', 'cif')
            if partner_raw is None or str(partner_raw).strip() == '':
                partner_raw = get_row_val(row, 'cliente', 'partner', exclude=['cif', 'nif'])
            if partner_raw is None or str(partner_raw).strip() == '':
                partner_raw = get_row_val(row, 'cif cliente', 'cliente', 'partner', 'nif', 'cif')
            partner_val = str(partner_raw).strip() if partner_raw is not None else ''

            date_raw = get_row_val(row, 'fecha creación', 'fecha', 'date')
            comercial_raw = get_row_val(row, 'comercial', 'vendedor', 'salesperson')
            comercial_val = str(comercial_raw).strip() if comercial_raw is not None else ''

            total_raw = get_row_val(row, 'total presupuesto', 'total de documento', 'total_documento', 'total_doc', 'total')
            total_val = self._parse_number(total_raw, row_number, 'Total', default=None)

            if not order_ref:
                if not last_order_ref:
                    raise UserError(_("Fila %s: falta la referencia de pedido inicial.") % row_number)
                order_ref = last_order_ref
            elif order_ref != last_order_ref:
                last_partner = ''
                last_date = None
                last_comercial = ''
                last_total = 0.0
                last_order_ref = order_ref
                if not partner_val:
                    raise UserError(_("Fila %s: el nuevo pedido no tiene cliente.") % row_number)

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

            if total_val is None:
                total_val = last_total
            else:
                last_total = total_val

            # Line level values
            if has_dedicated_ref_column:
                product_ref_raw = row[product_column]
            else:
                product_ref_raw = get_row_val(row, 'producto', 'product')
            product_ref = str(product_ref_raw).strip() if product_ref_raw is not None else ''

            # Search description/name headers
            desc_raw = get_row_val(row, 'definición', 'descripcion', 'artículo', 'description', 'name')
            if desc_raw is None or str(desc_raw).strip() == '':
                # If there is a dedicated code/ref column in the headers, then the generic 'producto' column contains the description
                if has_dedicated_ref_column:
                    desc_raw = get_row_val(row, 'producto', 'product')
            description = str(desc_raw).strip() if desc_raw is not None else ''

            if not product_ref and not description:
                # Skip row if it has neither a product nor a description
                continue

            qty_raw = get_row_val(row, 'cantidad', 'cant', 'qty', 'uom_qty')
            qty = self._parse_number(qty_raw, row_number, 'Cantidad', default=1.0 if product_ref else 0.0)
            if product_ref and qty <= 0:
                raise UserError(_("Fila %s, columna Cantidad: debe ser mayor que cero.") % row_number)
            price_raw = get_row_val(row, 'precio unitario', 'precio', 'price_unit', 'unitario', 'price')
            has_price = price_raw is not None and str(price_raw).strip() != ''
            price = self._parse_number(price_raw, row_number, 'Precio', default=0.0)
            discounts = []
            for number in (1, 2, 3):
                raw = get_row_val(row, 'dto%s' % number, 'dto %s' % number,
                                  'descuento%s' % number, 'discount%s' % number)
                value = self._parse_number(raw, row_number, 'Dto%s' % number, default=0.0)
                if not 0 <= value <= 100:
                    raise UserError(_("Fila %s, columna Dto%s: debe estar entre 0 y 100.") % (row_number, number))
                discounts.append(value)
            d1, d2, d3 = discounts

            # Initialize order in dict
            if order_ref not in orders_dict:
                orders_dict[order_ref] = {
                    'row': row_number,
                    'partner_val': partner_val,
                    'date': date_val,
                    'comercial_val': comercial_val,
                    'total_documento': total_val,
                    'lines': []
                }
            elif total_val > 0.0 and orders_dict[order_ref].get('total_documento', 0.0) == 0.0:
                orders_dict[order_ref]['total_documento'] = total_val

            orders_dict[order_ref]['lines'].append({
                'row': row_number,
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

        existing = self.env['sale.order'].search([
            ('company_id', '=', self.env.company.id), ('name', 'in', list(orders_dict))])
        if existing:
            raise UserError(_("Referencias de pedido ya existentes: %s") % ', '.join(sorted(set(existing.mapped('name')))))

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
            partner = self._find_partner(o_data['partner_val'], partner_cache=partner_cache, row_number=o_data['row'])
            if not partner:
                missing_partners.add('%s (fila %s)' % (o_data['partner_val'], o_data['row']))
                continue

            # 2. Resolve Salesperson
            user_id = self._find_salesperson(o_data['comercial_val'], salesperson_cache=salesperson_cache) or self.env.user.id

            # 3. Resolve Products first so we can check if they are missing and get pricelist rules
            resolved_lines = []
            has_missing = False
            for l in o_data['lines']:
                if l['product_ref']:
                    product = self._find_product_variant(l['product_ref'], product_cache=product_cache, pre_fetched_products=pre_fetched_products, row_number=l['row'])
                    if not product:
                        missing_products.add('%s (fila %s)' % (l['product_ref'], l['row']))
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

    def _parse_number(self, value, row_number, column, default=None):
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        try:
            if isinstance(value, bool):
                raise ValueError()
            if isinstance(value, str):
                value = value.strip()
                if not re.fullmatch(r'[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[0-9]{1,3}(?:\.[0-9]{3})+,[0-9]+)', value):
                    raise ValueError()
                if ',' in value:
                    value = value.replace('.', '').replace(',', '.')
            number = float(value)
            if not math.isfinite(number):
                raise ValueError()
            return number
        except (ValueError, TypeError, OverflowError):
            raise UserError(_("Fila %s, columna %s: número inválido (%s).") % (row_number, column, value))

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

    def _find_partner(self, partner_val, partner_cache=None, row_number=None):
        if not partner_val:
            return False
        partner_val = partner_val.strip()
        
        # Check cache
        if partner_cache is not None and partner_val in partner_cache:
            return partner_cache[partner_val]
            
        Partner = self.env['res.partner']
        partner = False
        
        # 1. Match by VAT/NIF
        partner_res = Partner.search([('vat', '=', partner_val)])
        if partner_res:
            partner = partner_res
        else:
            # Parse "(NOMBRE COMERCIAL) NOMBRE" format
            import re
            match = re.match(r'^\((.*?)\)\s*(.*)$', partner_val)
            search_terms = [partner_val]
            if match:
                comercial_name = match.group(1).strip()
                legal_name = match.group(2).strip()
                if legal_name:
                    search_terms.append(legal_name)
                if comercial_name:
                    search_terms.append(comercial_name)

            # Try to match by each name term
            for term in search_terms:
                if not term:
                    continue
                # 2. Match by exact name (case-insensitive)
                partner_res = Partner.search([('name', '=ilike', term)])
                if partner_res:
                    partner = partner_res
                    break
                # 3. Match by partial name (ilike)
                partner_res = Partner.search([('name', 'ilike', term)])
                if partner_res:
                    partner = partner_res
                    break
                    
        if partner and len(partner) > 1:
            raise UserError(_("Fila %s: cliente ambiguo: %s.") % (row_number, partner_val))
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

    def _find_product_variant(self, original_ref, product_cache=None, pre_fetched_products=None, row_number=None):
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
                
        # Un prefijo exige el estado solicitado incluso con una única variante.
        candidates = {variant.id: variant for variant in variants}
        matching = []
        for variant in candidates.values():
            states = variant.product_template_attribute_value_ids.filtered(
                lambda value: value.attribute_id.name == 'Estado')
            if any(value.product_attribute_value_id.name == estado_val for value in states):
                matching.append(variant)
            elif not states and estado_val == 'Nuevo':
                matching.append(variant)
        if candidates and len(matching) != 1:
            raise UserError(_("Fila %s: referencia %s ambigua o sin variante de estado %s.") %
                            (row_number, original_ref, estado_val))
        variant_res = matching[0] if matching else False

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
