import base64
import io
import logging

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

        file_data = base64.b64decode(self.file)
        
        # Intentar leer con openpyxl primero
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
            raise UserError(_("Formato de archivo no soportado o falta la librería openpyxl/xlrd. Sube un archivo .xlsx"))

        # Mapeo de columnas con nombres aproximados (en minúsculas)
        header_map = {str(k).strip().lower(): v for v, k in enumerate(header) if k}
        
        # ¡AQUÍ ESTÁ LA MAGIA! Pasamos no_vat_validation=True al entorno
        Partner = self.env['res.partner'].with_context(no_vat_validation=True)
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

        vals_list = []

        for row in data_rows:
            if not row or not any(row):
                continue
            
            def get_val(*keywords):
                # 1. Coincidencia exacta primero (insensible a mayúsculas/minúsculas)
                for kw in keywords:
                    for h_name, idx in header_map.items():
                        if kw == h_name:
                            val = row[idx]
                            return str(val).strip() if val is not None else ''
                # 2. Coincidencia parcial si no hay exacta
                for kw in keywords:
                    for h_name, idx in header_map.items():
                        if kw in h_name:
                            val = row[idx]
                            return str(val).strip() if val is not None else ''
                return ''

            nif = get_val('nif', 'cif')
            nombre_comercial = get_val('nombre comercial', 'nom. comercial', 'comercial')
            
            nombre = ''
            for h_name, idx in header_map.items():
                if h_name == 'nombre':
                    val = row[idx]
                    nombre = str(val).strip() if val is not None else ''
                    break
            
            if not nombre:
                nombre = get_val('nombre')

            calle = get_val('calle')
            cp = get_val('postal', 'cp', 'codigo')
            ciudad = get_val('ciudad')
            provincia_name = get_val('provincia')
            pais_name = get_val('pais')
            email = get_val('email')
            vendedor_name = get_val('nombre vendedor', 'vendedor', 'comercial')

            if not nombre:
                continue

            vals = {
                'name': nombre,
                'street': calle,
                'zip': cp,
                'city': ciudad,
                'email': email,
                'company_type': 'company',
            }

            if 'comercial' in Partner._fields:
                vals['comercial'] = nombre_comercial

            if nif:
                vals['vat'] = nif

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

            vals_list.append(vals)

        # 4. OPTIMIZACIÓN: Búsqueda masiva de potenciales contactos existentes para evitar duplicaciones
        imported_vats = {v['vat'] for v in vals_list if v.get('vat')}
        imported_names = {v['name'] for v in vals_list if v.get('name')}
        
        existing_domain = []
        if imported_vats:
            existing_domain.append(('vat', 'in', list(imported_vats)))
        if imported_names:
            existing_domain.append(('name', 'in', list(imported_names)))
            
        existing_map = {}
        if existing_domain:
            if len(existing_domain) > 1:
                existing_domain = ['|'] + existing_domain
            
            existing_partners = Partner.search(existing_domain)
            for p in existing_partners:
                p_comercial = p.comercial if 'comercial' in Partner._fields else ''
                key = (
                    (p.vat or '').strip().lower(),
                    (p.name or '').strip().lower(),
                    (p.comercial or '').strip().lower() if 'comercial' in Partner._fields else ''
                )
                if key not in existing_map:
                    existing_map[key] = p

        # 5. Separación en creación o actualización
        created_count = 0
        updated_count = 0
        to_create = []

        for vals in vals_list:
            nif = vals.get('vat', '')
            nombre = vals.get('name', '')
            nombre_comercial = vals.get('comercial', '') if 'comercial' in Partner._fields else ''
            
            key = (
                nif.strip().lower(),
                nombre.strip().lower(),
                nombre_comercial.strip().lower()
            )
            
            existing_partner = existing_map.get(key)
            if existing_partner:
                # Actualizar el contacto existente (excluyendo 'company_type' que ya está configurado)
                write_vals = {k: v for k, v in vals.items() if k != 'company_type'}
                existing_partner.write(write_vals)
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
                'message': _('Se han creado %s empresas y actualizado %s empresas exitosamente.') % (created_count, updated_count),
                'sticky': False,
                'type': 'success',
            }
        }
