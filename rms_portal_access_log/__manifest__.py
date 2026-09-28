{
    'name': 'RMS Portal Access Log',
    'version': '19.0.1.4.3',
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

        Cada lunes envía por email un informe semanal (clientes que han
        entrado, % de interés, fichas más vistas y búsquedas sin resultado)
        a los usuarios con el permiso "Recibe el informe semanal del portal".

        Solo se registran usuarios de portal (share=True); la actividad de
        usuarios internos no se registra aquí.
    """,
    'author': 'Antigravity',
    'depends': ['portal', 'mail', 'sale', 'account', 'rms_portal_profiles', 'rms_portal_catalog', 'rms_portal_projects'],
    'data': [
        'security/portal_access_log_security.xml',
        'security/ir.model.access.csv',
        'views/portal_access_log_views.xml',
        'views/portal_activity_views.xml',
        'views/portal_weekly_report_templates.xml',
        'data/portal_weekly_report_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
