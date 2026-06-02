{
    'name': 'Partner Multi Role',
    'version': '1.0',
    'category': 'Sales/CRM',
    'summary': 'Permite múltiples roles dinámicos para los contactos hijos',
    'description': """
    Añade un sistema de checkboxes en los contactos hijos para activar roles de forma simultánea.
    Dependiendo del rol seleccionado (Facturación, Envío, Lista de precios, Cuestiones Técnicas, etc.),
    el formulario despliega dinámicamente los campos requeridos para concentrar toda la información
    en una única ficha de contacto.
    """,
    'author': 'Xtendoo',
    'website': 'https://xtendoo.es',
    'depends': ['base', 'contacts'],
    'data': [
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
