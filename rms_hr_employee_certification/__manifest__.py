{
    'name': 'RMS - Certificaciones de Empleado',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Control de certificaciones, formaciones y consentimientos de empleados con renovación periódica',
    'description': """
        Permite llevar un registro de las certificaciones, formaciones y consentimientos
        de cada empleado (por ejemplo, formación anual de PRL, consentimiento de WhatsApp, etc.).

        - Catálogo configurable de tipos de certificación, indicando si requieren renovación
          periódica (con validez en meses) o si son un reconocimiento único (firma/consentimiento).
        - Registro por empleado de cada certificación obtenida, con fecha de obtención,
          caducidad calculada automáticamente y documento adjunto opcional.
        - Estado automático (Vigente / Próxima a caducar / Caducada / Registrada) según la fecha
          de caducidad y el aviso configurado en el tipo de certificación.
        - Aviso automático (actividad) al responsable cuando una certificación está próxima a
          caducar o ha caducado.
        - Grupo de seguridad "Gestor de Certificaciones de Empleado": solo sus miembros (más
          los Administradores) pueden añadir, modificar o eliminar certificaciones; el resto
          de usuarios puede consultarlas (RRHH ve todas, cada empleado ve solo las suyas).

        NOTA: el botón inteligente en la ficha del empleado (views/hr_employee_views.xml) está
        deshabilitado temporalmente en el manifest porque la ficha de empleado de esta instancia
        tiene una vista heredada (probablemente de Studio) que referencia un campo `skill_id`
        inexistente, lo que bloquea la instalación de cualquier vista nueva sobre
        hr.view_employee_form. Reactivar esa línea en 'data' una vez corregida esa vista.
    """,
    'author': 'Xtendoo',
    'website': 'https://xtendoo.es',
    'depends': ['hr', 'mail'],
    'data': [
        'security/hr_certification_groups.xml',
        'security/ir.model.access.csv',
        'security/hr_employee_certification_security.xml',
        'data/hr_certification_type_data.xml',
        'data/ir_cron_data.xml',
        'views/hr_certification_type_views.xml',
        'views/hr_employee_certification_views.xml',
        # 'views/hr_employee_views.xml',  # deshabilitado: ver NOTA arriba (campo skill_id roto en hr.view_employee_form)
        'views/hr_menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
