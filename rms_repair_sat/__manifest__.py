# -*- coding: utf-8 -*-
{
    'name': 'RMS SAT (reparaciones y despiece)',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'SAT de RMS sobre Reparaciones de Odoo: fases con días, equipo del cliente '
               'fuera de la valoración, envíos a fábrica, alternativa con piezas de 2ª mano y despiece.',
    'description': """
SAT de RMS (Madrid y Sevilla) sobre la app Reparaciones de Odoo y OCA
=====================================================================

* De serie (repair): orden de reparación, piezas que se descuentan del stock, garantía, presupuesto y factura vía venta, PDF de la reparación.
* OCA: repair_security (grupos), repair_service (horas de técnico), base_repair_config (ajustes).
* Este módulo: fases del SAT con días, ubicaciones SAT Madrid / SAT Sevilla con el equipo del cliente como propietario (sin valoración), envío y vuelta de fábrica, alternativa de 2ª mano en el presupuesto (sección opcional), despiece de equipos en piezas de 2ª mano y creación de reparaciones abiertas desde Sage para el arranque.
    """,
    'author': 'Custom RMS',
    'license': 'LGPL-3',
    'depends': [
        'repair',
        'repair_security',
        'repair_service',
        'base_repair_config',
        'stock_account',
        'mrp',
        'rms_product_state',
        'rms_stock_lot_label_print',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sat_data.xml',
        'views/repair_order_views.xml',
        'views/disassembly_views.xml',
        'views/wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/sat_menus.xml',
        'report/repair_report.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
