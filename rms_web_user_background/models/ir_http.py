import hashlib

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        info['rms_background_url'] = False
        user = self.env.user
        if user._is_internal():
            image = user.rms_background_image
            if image:
                checksum = hashlib.sha256(image).hexdigest()
                info['rms_background_url'] = (
                    f'/web/image/res.users/{user.id}/rms_background_image'
                    f'?unique={checksum}'
                )
        return info
