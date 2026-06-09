# -*- coding: utf-8 -*-
{
    'name': 'RMS CRM Hide Company Avatar',
    'version': '1.0',
    'category': 'Sales/CRM',
    'summary': 'Oculta el avatar de la empresa en las tarjetas kanban del pipeline de CRM.',
    'depends': [
        'crm',
        'web',
    ],
    'data': [
        'views/crm_lead_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_crm_hide_company_avatar/static/src/scss/crm_lead_kanban.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
