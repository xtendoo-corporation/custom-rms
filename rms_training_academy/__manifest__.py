# -*- coding: utf-8 -*-
{
    'name': 'RMS Academia Odoo',
    'version': '19.0.2.0.1',
    'category': 'Productivity',
    'summary': 'Formación interna paso a paso (de básico a avanzado) sobre el Odoo de RMS-Proaudio: catálogo global por aplicación, filtrado según los permisos de cada empleado, con control de progreso.',
    'description': """
Academia interna de formación sobre el Odoo de RMS-Proaudio.

- Catálogo GLOBAL organizado por aplicación (Primeros pasos, Contactos,
  Ventas, Inventario, Gastos, Mapas, Portal, Empleados, Conocimiento,
  Administración), con lecciones de nivel Básico a Avanzado.
- Cada empleado ve solo las lecciones que puede poner en práctica, según
  sus permisos reales en Odoo (menús visibles y grupos). No hay que
  mantener listas por departamento: si a alguien se le da acceso a una
  aplicación, sus lecciones le aparecen solas.
- Cada lección incluye objetivo, ruta de menú, pasos numerados con el
  resultado esperado y consejos. El empleado la marca como completada.
- Control de formación: el Responsable de formación ve el avance de cada
  empleado respecto a las lecciones que le corresponden.
- Integración con "RMS AI Help Assistant": si está instalado, el asistente
  de IA consulta estas lecciones para responder "cómo se hace X".
    """,
    'author': 'Custom RMS',
    'depends': ['base', 'mail'],
    'data': [
        'security/training_security.xml',
        'security/ir.model.access.csv',
        'views/training_lesson_views.xml',
        'views/training_path_views.xml',
        'views/training_progress_views.xml',
        'views/training_user_summary_views.xml',
        'views/training_menus.xml',
        'data/training_content_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
