# -*- coding: utf-8 -*-
{
    'name': 'RMS Carga de arranque del stock',
    'version': '19.0.1.0.2',
    'category': 'Inventory/Inventory',
    'summary': 'Carga inicial del stock en Odoo a partir de lo contado con la pistola y de Sage '
               '(arranque del 7-ene-2027): simulación, revisión de estados, aplicar y deshacer.',
    'description': """
Carga de arranque del stock (reglas acordadas el 20-nov-2026).

Manda lo contado: lo que Sage tiene en una nave contada y nadie encontró va al
almacén fantasma «Pendiente de localizar» (no se puede vender ni valora). Las
naves no contadas entran según Sage, «No verificado». Las altas entran a nombre
de RMS como «Alta por revisar». El estado distinto entre lectura y Sage se
revisa uno a uno. Los depósitos de Sage entran como un depósito por cliente y
empresa. «Preparar» simula, «Aplicar» crea las existencias y «Deshacer carga»
las revierte.
    """,
    'author': 'Custom RMS',
    'license': 'LGPL-3',
    'depends': ['stock', 'stock_account', 'rms_product_state', 'rms_stock_count_session',
                'stock_cession', 'rms_stock_delivery_check'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/partner_data.xml',
        'views/initial_load_views.xml',
        'views/state_review_views.xml',
        'views/stock_views.xml',
        'views/wizard_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
