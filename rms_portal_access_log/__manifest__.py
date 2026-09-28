{
    'name': 'RMS Portal Access Log',
    'version': '19.0.1.3.0',
    'category': 'Sales',
    'summary': 'Registra los accesos al portal y qué mira cada cliente (fichas, precios, presupuestos, facturas).',
    'description': """
        Guarda un histórico de accesos al portal de clientes: quién entra,
        cuándo y desde qué IP. A diferencia del log de login estándar de
        Odoo (que solo conserva el último acceso de cada usuario), este
        histórico no se purga automáticamente.

        Además registra la actividad dentro del portal: pantallas visitadas,
        marcas y fichas del catálogo abiertas, consultas de precio,
        búsquedas, productos añadidos al presupuesto y presupuestos, pedidos,
        facturas o proyectos consultados. El informe "Intereses por cliente"
        resume qué fichas mira más cada contacto.

        Solo se registran usuarios de portal (share=True); la actividad de
        usuarios internos no se registra aquí.
    """,
    'author': 'Antigravity',
    'depends': ['portal', 'sale', 'account', 'rms_portal_profiles', 'rms_portal_catalog', 'rms_portal_projects'],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_access_log_views.xml',
        'views/portal_activity_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
