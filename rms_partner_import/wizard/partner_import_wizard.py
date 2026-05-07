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
        
        imported_count = 0

        for row in data_rows:
            if not row or not any(row):
                continue
            
            def get_val(*keywords):
                # Busca por varias posibles palabras clave (ej: 'nif', 'cif')
                for kw in keywords:
                    for h_name, idx in header_map.items():
                        if kw in h_name:
                            val = row[idx]
                            return str(val).strip() if val is not None else ''
                return ''

            nif = get_val('nif', 'cif')
            nombre_comercial = get_val('comercial')
            # 'nombre' puede chocar con 'nombre_comercial', así que buscamos la columna exacta si es posible
            nombre = ''
            for h_name, idx in header_map.items():
                if h_name == 'nombre':
                    val = row[idx]
                    nombre = str(val).strip() if val is not None else ''
                    break
            
            # Fallback por si la columna no se llama exactamente "nombre"
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

            # Asignamos el nombre comercial al campo 'comercial' si existe en la base de datos
            if nombre_comercial and 'comercial' in Partner._fields:
                vals['comercial'] = nombre_comercial

            # Insertamos el NIF tal cual, sin validar ni poner prefijos
            if nif:
                vals['vat'] = nif

            # Búsqueda de país
            country_id = False
            if pais_name:
                country = Country.search([('name', 'ilike', pais_name)], limit=1)
                if country:
                    country_id = country.id
                    vals['country_id'] = country_id

            # Búsqueda de provincia
            if provincia_name:
                domain = [('name', 'ilike', provincia_name)]
                if country_id:
                    domain.append(('country_id', '=', country_id))
                state = State.search(domain, limit=1)
                if state:
                    vals['state_id'] = state.id

            # Creamos el registro, saltándose las validaciones por el contexto
            Partner.create(vals)
            imported_count += 1

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
