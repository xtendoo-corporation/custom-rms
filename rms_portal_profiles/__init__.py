from . import models
from . import controllers
from . import wizard


def sync_existing_portal_profiles(env):
    partners = env['res.partner'].search([('user_ids.share', '=', True)])
    partners._sync_portal_profile_groups()
