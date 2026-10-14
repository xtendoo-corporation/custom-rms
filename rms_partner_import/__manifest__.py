{
    'name': 'RMS Partner Import',
    'version': '1.0',
    'category': 'Sales/CRM',
    'summary': 'Bypasses VAT validation during native partner imports.',
    'description': """
        This module overrides the VAT validation process in res.partner.
        It intercepts the validation and bypasses it only when the record 
        is being created/updated via the native Odoo import tool, keeping 
        the validation active for manual creations.
    """,
    'author': 'Antigravity',
    'depends': ['base', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/partner_import_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
}
