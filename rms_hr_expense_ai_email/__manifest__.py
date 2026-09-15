# -*- coding: utf-8 -*-
{
    'name': 'RMS HR Expense AI Email Import',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Expenses',
    'summary': 'Un borrador por cada ticket recibido por email y extracción automática con IA reutilizando xtendoo_hr_expense_ai',
    'description': """
        El alias de correo de Gastos (expense@rmsproaudio.com) sólo parseaba
        el asunto del email y amontonaba todos los adjuntos en un único
        hr.expense. Este módulo:

        1. Si un correo entrante trae varios tickets (imagen o PDF), reparte
           los adjuntos en un hr.expense en borrador por cada uno, en vez de
           uno solo con todo amontonado. Conserva la asignación de empleado
           por remitente que ya hace hr_expense.
        2. Para cada gasto así creado, dispara vía cron (para no acoplar la
           llamada a la IA a la recepción del correo/fetchmail) el mismo
           asistente "Importar con IA" del módulo de terceros
           xtendoo_hr_expense_ai (hr.expense.ai.wizard: action_analyze +
           action_apply) sobre el adjunto ya recibido, sin pedir que se
           vuelva a subir a mano.
        3. Deja el gasto en "draft", sin tocar el flujo de aprobación.
        4. Reintenta un número limitado de veces (parámetro de sistema) y,
           si tras agotarlas no se ha podido procesar, dej a constancia en
           el chatter del gasto y marca "Correcciones de IA Pendientes"
           para que administración lo revise a mano.
        5. Usa los campos ya existentes de xtendoo_hr_expense_ai
           (ai_processed, ai_has_corrections) en vez de duplicarlos, y
           rellena la categoría (product_id) por palabras clave sobre el
           default_code existente sólo cuando la IA no la haya asignado ya.

        No modifica la seguridad del alias (sigue restringido a "Empleados
        autenticados") ni el flujo de aprobación de gastos.
    """,
    'author': 'Custom RMS',
    'depends': ['hr_expense', 'xtendoo_hr_expense_ai'],
    'data': [
        'data/ir_cron_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
