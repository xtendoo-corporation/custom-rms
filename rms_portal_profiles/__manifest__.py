{
    'name': 'RMS Portal Profiles',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Segmenta el portal de clientes en perfiles (Cliente, Marketing, Proyectos) con acceso restringido por perfil.',
    'description': """
        Añade un campo "Perfil de portal" en el contacto (Cliente / Colaborador
        de Marketing / Proyectos) y restringe, tanto en el menú como a nivel de
        ruta, qué secciones del portal ve cada perfil:

        - Cliente: Pedidos, Facturas, Direcciones, Conexión y seguridad.
        - Colaborador de Marketing: Proyecto y Tareas nativas de Odoo (solo
          donde esté añadido como colaborador), Conexión y seguridad.
        - Proyectos: "Proyectos" (rms_portal_projects), Conexión y seguridad.
    """,
    'author': 'Antigravity',
    'depends': ['portal', 'sale', 'account', 'project', 'rms_portal_projects', 'rms_portal_catalog'],
    'data': [
        'security/security_groups.xml',
        'views/res_partner_views.xml',
        'views/portal_templates.xml',
        'views/project_sharing_calendar_views.xml',
        'views/catalog_portal_templates.xml',
    ],
    'assets': {
        # El bundle "Proyecto compartido" del portal (project.webclient) solo
        # incluye Kanban/Lista/Formulario a propósito. Añadimos aquí las
        # plantillas/estilos de la vista Calendario genérica de Odoo (su JS ya
        # viaja en el bundle vía el glob **/*.js) para poder ofrecerla al
        # colaborador de Marketing.
        'project.webclient': [
            'web/static/src/views/calendar/**/*',
        ],
    },
    'post_init_hook': 'sync_existing_portal_profiles',
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
