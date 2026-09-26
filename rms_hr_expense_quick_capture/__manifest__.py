# -*- coding: utf-8 -*-
{
    'name': 'RMS HR Expense Quick Capture',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Expenses',
    'summary': 'Crear un gasto al momento haciendo una foto del ticket con el móvil, con la misma IA que el correo',
    'description': """
        Añade una app "Foto de Gasto" con un único campo de imagen: al
        elegir o hacer una foto y pulsar "Crear gasto", se crea un
        hr.expense en borrador a nombre del usuario que ha entrado, y se
        dispara al momento (sin esperar al cron) el mismo motor de IA que
        ya usa el correo de gastos (rms_hr_expense_ai_email), reutilizando
        su lógica de extracción, categorización y aviso de fallo — sin
        reimplementar nada.

        Pensada para guardarse como acceso directo en la pantalla de
        inicio del móvil: al entrar en esta acción desde un navegador
        móvil, el selector de imagen ya ofrece la cámara como opción
        nativa del sistema operativo, sin necesidad de JavaScript extra.
    """,
    'author': 'Custom RMS',
    'depends': ['hr_expense', 'xtendoo_hr_expense_ai', 'rms_hr_expense_ai_email'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_expense_quick_capture_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
