{
    'name': 'RMS Partner Import',
    'version': '1.1',
    'category': 'Sales/CRM',
    'summary': 'Bypasses VAT validation during native partner imports.',
    'description': """
        Omite la validación de NIF/CIF al importar contactos:

        - con el importador nativo de Odoo (Favoritos > Importar registros);
        - con el asistente propio Contactos > Configuración > Importar
          Contactos (RMS).

        El alta y la edición manual desde el formulario siguen validando el
        NIF con normalidad.
    """,
    'author': 'Antigravity',
    'depends': ['base', 'contacts', 'base_import'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/partner_import_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
