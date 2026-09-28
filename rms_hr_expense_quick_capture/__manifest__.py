# -*- coding: utf-8 -*-
{
    'name': 'RMS HR Expense Quick Capture',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Expenses',
    'summary': 'Crear un gasto al momento haciendo una foto del ticket con el móvil, con la misma IA que el correo',
    'description': """
        Añade una app "Foto de Gasto": una pantalla propia, sin la barra
        de Odoo, con un único botón grande para hacer la foto del ticket.
        Al tocarlo se abre directamente la cámara del móvil; en cuanto se
        hace la foto, se sube sola y se crea un hr.expense en borrador a
        nombre del usuario que ha entrado, disparando al momento (sin
        esperar al cron) el mismo motor de IA que ya usa el correo de
        gastos (rms_hr_expense_ai_email), reutilizando su lógica de
        extracción, categorización y aviso de fallo — sin reimplementar
        nada.

        Pensada para guardarse como acceso directo en la pantalla de
        inicio del móvil: mínimo número de toques (abrir → foto → listo).
    """,
    'author': 'Custom RMS',
    'depends': ['hr_expense', 'xtendoo_hr_expense_ai', 'rms_hr_expense_ai_email'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_expense_quick_capture_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_hr_expense_quick_capture/static/src/quick_capture/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
