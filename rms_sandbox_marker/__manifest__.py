# -*- coding: utf-8 -*-
{
    'name': 'RMS Marca visual de Sandbox',
    'version': '19.0.1.1.0',
    'category': 'Hidden/Tools',
    'summary': 'Deja clarísimo que se está en la base de pruebas (sandbox).',
    'description': """
Marca visual de la base de pruebas
==================================

Instalar SOLO en ``rms-sandbox``. Además, el código comprueba el nombre de
la base de datos: si no contiene "sandbox" no muestra nada, así que en
producción nunca se ve aunque se instalara por error.

Qué muestra (para todos los usuarios):

- Barra de menú con rayas rojas.
- Fondo rosado detrás de las vistas.
- Marco rojo alrededor de toda la pantalla (no tapa ni bloquea botones).
- Etiqueta fija "SANDBOX · PRUEBAS" arriba en el centro.
    """,
    'author': 'Custom RMS',
    'license': 'LGPL-3',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'rms_sandbox_marker/static/src/sandbox_marker.js',
            'rms_sandbox_marker/static/src/sandbox_marker.xml',
            'rms_sandbox_marker/static/src/sandbox_marker.scss',
        ],
    },
    'installable': True,
    'application': False,
}
