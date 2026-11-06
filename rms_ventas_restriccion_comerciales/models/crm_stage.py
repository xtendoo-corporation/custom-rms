# -*- coding: utf-8 -*-

from odoo import fields, models


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    rms_closes_pm_access = fields.Boolean(
        string='Cierra el acceso de Product Managers',
        help='Cuando una oportunidad está en esta etapa, los Product Managers '
             'dejan de ver la ficha de su cliente (si no es cliente suyo). '
             'Marcar en las etapas finales: Entregados, Perdido, Eliminados.',
    )
