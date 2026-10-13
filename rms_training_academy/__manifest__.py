# -*- coding: utf-8 -*-
{
    'name': 'RMS Academia Odoo',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Formación interna paso a paso (de básico a avanzado) sobre todo lo que ofrece el Odoo de RMS-Proaudio, con control de progreso por empleado.',
    'description': """
Academia interna de formación sobre el Odoo de RMS-Proaudio.

- Rutas formativas (Primeros pasos, Clientes, Ventas, Inventario, Gastos,
  RRHH, Portal, Documentación, Administración) con lecciones ordenadas de
  nivel Básico a Avanzado.
- Cada lección incluye objetivo, ruta de menú, pasos numerados con el
  resultado esperado, consejos y errores frecuentes.
- Test de comprobación opcional por lección (con nota mínima para aprobar).
- Control de progreso: cada empleado ve qué tiene pendiente, en curso y
  completado; el Responsable de formación ve el progreso de todos (lista,
  tabla dinámica y gráfico).
- Integración con "RMS AI Help Assistant": si está instalado, el asistente
  de IA consulta estas lecciones para responder "cómo se hace X" con los
  pasos oficiales de la empresa.
    """,
    'author': 'Custom RMS',
    'depends': ['base', 'mail'],
    'data': [
        'security/training_security.xml',
        'security/ir.model.access.csv',
        'wizard/training_quiz_wizard_views.xml',
        'views/training_lesson_views.xml',
        'views/training_path_views.xml',
        'views/training_progress_views.xml',
        'views/training_menus.xml',
        'data/training_content_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
