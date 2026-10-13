{
    'name': 'RMS Quotation Import',
    'version': '1.0.1',
    'category': 'Sales/Sales',
    'summary': 'Smart Wizard to import quotations (Sales Orders) from Excel with dynamic variant resolution and automatic discount calculation.',
    'description': """
        Smart Quotation Import Wizard:
        - Upload Excel files (.xlsx, .xls) to import quotations.
        - Automatically resolves product references with legacy prefixes (2M-, D-) to the correct product variant.
        - Robust fuzzy header mapping (pedido, cliente, producto, cantidad, precio, etc.).
        - Groups lines into the same quotation with carry-over of empty order references.
        - Applies line-level discounts (dto1, dto2, dto3) from the Excel and, when the target document total is lower than the lines, adds a negative "Descuento comercial para cuadrar presupuesto" line for the difference.
        - If any customer or product reference is not found, nothing is imported and the missing ones are listed.
    """,
    'author': 'Antigravity',
    'depends': ['sale', 'product', 'stock', 'crm', 'sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/quotation_import_wizard_view.xml',
        'views/sale_order_actions.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
