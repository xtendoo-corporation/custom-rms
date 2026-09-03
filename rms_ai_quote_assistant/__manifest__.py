# -*- coding: utf-8 -*-
{
    'name': 'RMS AI Quote Assistant',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Asistente de IA (Claude) que crea presupuestos a partir de lenguaje natural.',
    'description': """
Chat de IA que resuelve cliente y productos a partir de una instrucción en
lenguaje natural (p. ej. "hazle un presupuesto a fulanito con 3 X40 y una
Quantum 3"), pide confirmación al usuario y crea un único sale.order usando
exclusivamente los permisos del usuario que lo pide (nunca sudo). Sustituye
al toolkit CLI standalone en ia-presupuestos por una app nativa de Odoo.
    """,
    'author': 'Custom RMS',
    'depends': ['base', 'web', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'views/ai_quote_assistant_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_ai_quote_assistant/static/src/ai_quote_assistant/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
