{
    'name': 'RMS Portal Access Log',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Registra cada acceso (login) de los usuarios de portal, con fecha, IP y perfil.',
    'description': """
        Guarda un histórico de accesos al portal de clientes: quién entra,
        cuándo y desde qué IP. A diferencia del log de login estándar de
        Odoo (que solo conserva el último acceso de cada usuario), este
        histórico no se purga automáticamente.

        Solo se registran accesos de usuarios de portal (share=True); los
        logins de usuarios internos no se registran aquí.
    """,
    'author': 'Antigravity',
    'depends': ['portal', 'rms_portal_profiles'],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_access_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
