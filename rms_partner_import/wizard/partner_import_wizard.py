import base64
import io
import logging
import re
from itertools import islice

try:
    import xlrd
except ImportError:
    xlrd = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PartnerImportWizard(models.TransientModel):
    _name = 'rms.partner.import.wizard'
    _description = 'Wizard for Importing Partners from Excel'

    file = fields.Binary('Archivo Excel', required=True)
    filename = fields.Char('Nombre de Archivo')

    def action_import(self):
        if not self.file:
            raise UserError(_("Por favor, sube un archivo Excel."))

        max_size = 20 * 1024 * 1024
        if len(self.file) > 4 * ((max_size + 2) // 3):
            raise UserError(_("El archivo supera el límite de 20 MB."))
        file_data = base64.b64decode(self.file)
        if len(file_data) > max_size:
            raise UserError(_("El archivo supera el límite de 20 MB."))
        
        # Intentar leer con openpyxl primero
        if openpyxl and self.filename and self.filename.endswith('.xlsx'):
            wb = openpyxl.load_workbook(filename=io.BytesIO(file_data), data_only=True, read_only=True)
            sheet = wb.active
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, ())
            data_rows = list(islice(rows, 50001))
            wb.close()
        elif xlrd and self.filename and self.filename.endswith('.xls'):
            wb = xlrd.open_workbook(file_contents=file_data)
            sheet = wb.sheet_by_index(0)
            if sheet.nrows > 50001:
                raise UserError(_("El archivo supera el límite de 50.000 filas."))
            header = sheet.row_values(0) if sheet.nrows else []
            data_rows = [sheet.row_values(rx) for rx in range(1, sheet.nrows)]
        else:
            raise UserError(_("Formato de archivo no soportado o falta la librería openpyxl/xlrd. Sube un archivo .xlsx"))

        if len(data_rows) > 50000:
            raise UserError(_("El archivo supera el límite de 50.000 filas."))

        # Mapeo de columnas con nombres aproximados (en minúsculas)
        header_map = {str(k).strip().lower(): v for v, k in enumerate(header) if k}
        
        # ¡AQUÍ ESTÁ LA MAGIA! Pasamos no_vat_validation=True y desactivamos el chatter/notificaciones
        Partner = self.env['res.partner'].with_context(
            active_test=False,
            no_vat_validation=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
            tracking_disable=True
        )
        Country = self.env['res.country']
        State = self.env['res.country.state']
        User = self.env['res.users']
        
        # 1. OPTIMIZACIÓN: Cargar todos los países, provincias y comerciales/usuarios en memoria
        country_records = Country.search([])
        country_map = {c.name.strip().lower(): c.id for c in country_records if c.name}
        
        state_records = State.search([])
        state_map = {}
        for s in state_records:
            if s.name:
                key_with_country = (s.name.strip().lower(), s.country_id.id)
                key_without_country = (s.name.strip().lower(), False)
                state_map[key_with_country] = s.id
                if key_without_country not in state_map:
                    state_map[key_without_country] = s.id

        user_records = User.search([])
        user_map = {u.name.strip().lower(): u.id for u in user_records if u.name}

        country_codes = {c.code.upper() for c in country_records if c.code} | {'EL', 'UK'}

        def normalize_name(value):
            return ' '.join((value or '').split()).casefold()

        def normalize_vat(value, country):
            value = re.sub(r'[\s.\-]+', '', value or '').upper()
            # Conservar el país para no fusionar números de países distintos.
            if value[:2] in country_codes:
                return {'EL': 'GR', 'UK': 'GB'}.get(value[:2], value[:2]) + value[2:]
            return (country.code or '').upper() + value if country else value

        def partner_key(vals, country):
            if vals.get('vat'):
                return ('vat', normalize_vat(vals['vat'], country))
            return ('name', normalize_name(vals.get('name')),
                    normalize_name(vals.get('comercial')))

        vals_by_key = {}
        skipped_count = 0
        for row_number, row in enumerate(data_rows, start=2):
            if not row or not any(row):
                continue

            present_fields = set()

            def get_val(*keywords):
                # Coincidencia exacta antes de buscar nombres parciales.
                for exact in (True, False):
                    for kw in keywords:
                        for h_name, idx in header_map.items():
                            # El nombre comercial o del vendedor no suple al nombre.
                            if keywords == ('nombre',) and ('comercial' in h_name or 'vendedor' in h_name):
                                continue
                            matches = kw == h_name if exact else kw in h_name
                            if matches:
                                present_fields.add(keywords)
                                val = row[idx] if idx < len(row) else None
                                return str(val).strip() if val is not None else ''
                return ''

            nif = get_val('nif', 'cif')
            nombre_comercial = get_val('nombre comercial', 'nom. comercial', 'comercial')
            
            nombre = get_val('nombre')

            calle = get_val('calle')
            cp = get_val('postal', 'cp', 'codigo')
            ciudad = get_val('ciudad')
            provincia_name = get_val('provincia')
            pais_name = get_val('pais')
            email = get_val('email')
            vendedor_name = get_val('nombre vendedor', 'vendedor', 'comercial')

            if not nombre:
                skipped_count += 1
                continue

            vals = {'name': nombre, 'company_type': 'company'}
            # Solo las columnas presentes participan en la importación.
            for field, keywords, value in (
                ('street', ('calle',), calle),
                ('zip', ('postal', 'cp', 'codigo'), cp),
                ('city', ('ciudad',), ciudad),
                ('email', ('email',), email),
                ('vat', ('nif', 'cif'), nif),
                ('comercial', ('nombre comercial', 'nom. comercial', 'comercial'), nombre_comercial),
            ):
                if keywords in present_fields and field in Partner._fields:
                    vals[field] = value

            # Mapeo de Vendedor (Comercial)
            user_id = False
            if vendedor_name:
                v_lower = vendedor_name.strip().lower()
                user_id = user_map.get(v_lower)
                if not user_id:
                    # Búsqueda parcial si no hay coincidencia exacta
                    for u_name, u_id in user_map.items():
                        if v_lower in u_name or u_name in v_lower:
                            user_id = u_id
                            break
                if user_id:
                    vals['user_id'] = user_id

            # 2. OPTIMIZACIÓN: Búsqueda de país en diccionario de memoria
            country_id = False
            if pais_name:
                p_lower = pais_name.strip().lower()
                country_id = country_map.get(p_lower)
                if not country_id:
                    # Búsqueda parcial si no hay coincidencia exacta
                    for c_name, c_id in country_map.items():
                        if p_lower in c_name or c_name in p_lower:
                            country_id = c_id
                            break
                if country_id:
                    vals['country_id'] = country_id

            # 3. OPTIMIZACIÓN: Búsqueda de provincia en diccionario de memoria
            if provincia_name:
                s_lower = provincia_name.strip().lower()
                state_id = state_map.get((s_lower, country_id))
                if not state_id:
                    state_id = state_map.get((s_lower, False))
                
                if not state_id:
                    # Búsqueda parcial
                    for (st_name, st_c_id), st_id in state_map.items():
                        if (not st_c_id or st_c_id == country_id) and (s_lower in st_name or st_name in s_lower):
                            state_id = st_id
                            break
                
                if state_id:
                    vals['state_id'] = state_id

            key = partner_key(vals, Country.browse(country_id)
                              if country_id else self.env.company.country_id)
            if key in vals_by_key:
                # La primera fila prevalece; las siguientes solo completan huecos.
                first_vals, first_row = vals_by_key[key]
                for field, value in vals.items():
                    if not first_vals.get(field) and value:
                        first_vals[field] = value
            else:
                vals_by_key[key] = (vals, row_number)

        # La normalización requiere comparar también los valores almacenados con
        # espacios, guiones o puntos; se incluyen los contactos archivados.
        existing_map = {}
        if vals_by_key:
            for partner in Partner.search([]):
                values = {
                    'name': partner.name,
                    'comercial': partner.comercial if 'comercial' in Partner._fields else '',
                }
                keys = [partner_key(values, partner.country_id)]
                if partner.vat:
                    keys.append(partner_key({'vat': partner.vat}, partner.country_id))
                for key in keys:
                    if key in vals_by_key:
                        existing_map.setdefault(key, []).append(partner)

        # Detectar ambigüedades antes de escribir ningún contacto.
        for key, matches in existing_map.items():
            if len(matches) > 1:
                raise UserError(_("Fila %s: varios contactos coinciden con la clave de importación.")
                                % vals_by_key[key][1])

        created_count = 0
        updated_count = 0
        to_create = []
        for key, (vals, row_number) in vals_by_key.items():
            matches = existing_map.get(key)
            if matches:
                # Una celda vacía nunca borra datos al actualizar.
                write_vals = {k: v for k, v in vals.items()
                              if k != 'company_type' and v not in ('', False, None)}
                matches[0].write(write_vals)
                updated_count += 1
            else:
                to_create.append(vals)
                created_count += 1

        # Creación en lote para los nuevos registros
        if to_create:
            Partner.create(to_create)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Importación completada'),
                'message': _('Se han creado %s empresas y actualizado %s empresas exitosamente. Filas sin nombre omitidas: %s.') % (created_count, updated_count, skipped_count),
                'sticky': False,
                'type': 'success',
            }
        }
