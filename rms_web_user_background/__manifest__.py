# -*- coding: utf-8 -*-
{
    'name': 'RMS Fondo de pantalla por usuario',
    'version': '19.0.1.0.0',
    'author': 'RMS Pro Audio',
    'category': 'Hidden/Tools',
    'depends': [
        'web',
        'web_responsive',
    ],
    'data': [
        'views/res_users_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_web_user_background/static/src/js/user_background.esm.js',
            'rms_web_user_background/static/src/scss/user_background.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
