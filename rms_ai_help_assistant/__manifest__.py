# -*- coding: utf-8 -*-
{
    'name': 'RMS AI Help Assistant',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Asistente de IA (Claude) que responde dudas de uso de Odoo y consulta datos reales, en modo solo lectura.',
    'description': """
Chat de IA interno para que cualquier empleado pregunte "cómo se hace X" en
vuestro Odoo (crear un cliente, asignar una lista de precios, etc.) y
también pueda consultar datos reales (tarifa de un cliente, stock de un
producto, estado de un pedido, documentación interna) sin necesidad de sudo
ni de un usuario/API key dedicados: se ejecuta bajo los permisos del propio
usuario que pregunta (self.env, nunca sudo), igual que rms_ai_quote_assistant.

Diseñado deliberadamente para NO poder escribir nada en Odoo: ninguna de sus
herramientas llama a create/write/unlink. Si el usuario pide realizar una
acción, el asistente explica los pasos para hacerla manualmente en la
interfaz; nunca la ejecuta él mismo.
    """,
    'author': 'Custom RMS',
    'depends': ['base', 'web', 'sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'views/ai_help_assistant_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_ai_help_assistant/static/src/ai_help_assistant/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
