# -*- coding: utf-8 -*-
{
    'name': 'RMS Web Redirect',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'summary': 'Root menu shortcuts that open external websites (Sala IN, CLUB).',
    'description': """
        Adds root-level menu items that open external URLs in a new tab:
        - Sala IN: http://192.168.11.41:8080/#/demos
        - CLUB: https://club.rmsproaudio.com/admin
        Visible only to administrators (Settings group).
    """,
    'author': 'Custom RMS',
    'depends': ['base', 'web'],
    'data': [
        'views/web_redirect_menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
