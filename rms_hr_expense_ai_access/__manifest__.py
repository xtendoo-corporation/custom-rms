{
    'name': 'RMS HR Expense AI Access',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Expenses',
    'summary': 'Permite a los comerciales usar el importador de gastos con IA sin ser aprobadores',
    'description': """
        El módulo de terceros xtendoo_hr_expense_ai restringe su asistente
        "Importar con IA" (modelo hr.expense.ai.wizard) al grupo
        Gastos/Todos los aprobadores. Este módulo añade una regla de acceso
        adicional, sin tocar el código de xtendoo_hr_expense_ai, para que el
        grupo de Comerciales (custom.comerciales) también pueda usar ese
        asistente sobre sus propios gastos, sin concederles ningún permiso
        de aprobación.
    """,
    'author': 'Antigravity',
    'depends': ['hr_expense', 'xtendoo_hr_expense_ai'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
