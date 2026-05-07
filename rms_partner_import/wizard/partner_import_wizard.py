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
        
        # 1. OPTIMIZACIÓN: Cargar todos los países y provincias en memoria (Diccionarios)
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

        vals_list = []

        for row in data_rows:
            if not row or not any(row):
                continue
            
            def get_val(*keywords):
                for kw in keywords:
                    for h_name, idx in header_map.items():
                        if kw in h_name:
                            val = row[idx]
                            return str(val).strip() if val is not None else ''
                return ''

            nif = get_val('nif', 'cif')
            nombre_comercial = get_val('comercial')
            
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

            if nombre_comercial and 'comercial' in Partner._fields:
                vals['comercial'] = nombre_comercial

            if nif:
                vals['vat'] = nif

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

        # 4. OPTIMIZACIÓN: Creación en lote (Batch Create)
        # En lugar de crear 4500 registros 1 a 1, pasamos la lista completa a Odoo
        # Esto reduce 4500 consultas SQL INSERT a prácticamente 1 consulta gigante.
        if vals_list:
            # Si son 4500, Odoo las gestiona perfectamente en un batch
            Partner.create(vals_list)
        
        imported_count = len(vals_list)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Importación completada'),
                'message': _('Se han importado %s empresas exitosamente.') % imported_count,
                'sticky': False,
                'type': 'success',
            }
        }
