from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    rms_background_image = fields.Image(
        'Fondo de pantalla', max_width=2560, max_height=1440,
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['rms_background_image']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['rms_background_image']
