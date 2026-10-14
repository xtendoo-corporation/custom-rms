# -*- coding: utf-8 -*-
{
    'name': 'RMS Comerciales Tasks Shortcut',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Add a root menu item shortcut to My Tasks for the Comerciales group.',
    'description': """
        Adds a root-level shortcut menu to the "My Tasks" view
        restricted to the custom group Ventas: COMERCIALES (custom.comerciales).
    """,
    'author': 'Custom RMS',
    'depends': ['project', 'web_responsive'],
    'data': [
        'views/project_task_menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
