# -*- coding: utf-8 -*-
{
    'name': 'RMS Notificar Errores a Soporte (IA)',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Botón "Notificar a soporte" en las ventanas de error de Odoo, con informe automático de la IA (Claude) y aviso en Conversaciones.',
    'description': """
Cuando a un usuario le salta un error de Odoo (fallo de código, error de
validación, inconsistencia entre módulos personalizados...) la ventana del
error muestra un botón "Notificar a soporte". Al pulsarlo:

1. Se guarda una Incidencia de soporte con el error, el traceback técnico,
   la pantalla/registro donde ocurrió y un comentario opcional del usuario.
   Si el mismo error ya está abierto, no se duplica: se suma una ocurrencia.
2. En segundo plano, la IA (Claude) recibe el error junto con el código
   fuente de las funciones implicadas (leído del propio servidor) y de los
   módulos personalizados que extienden el modelo afectado, y redacta un
   informe: qué falla, por qué falla, qué módulo lo provoca, gravedad y
   posibles soluciones (con parche propuesto si aplica).
3. Se publica un aviso en el canal de Conversaciones "Soporte Odoo", al que
   pertenecen automáticamente los usuarios del grupo "Recibe incidencias de
   soporte".

La IA solo diagnostica: nunca modifica código ni datos.
    """,
    'author': 'Custom RMS',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/ir_cron_data.xml',
        'data/discuss_channel_data.xml',
        'views/support_ticket_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_support_error_report/static/src/support_report/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
