"""Initialize ownership from each session, never from the upgrade company."""
import json

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    new = env.ref('rms_product_state.state_new')
    sessions = env['rms.stock.count.session'].search([])
    for session in sessions:
        if not session.default_state_id:
            session.default_state_id = new
        for line in session.line_ids:
            # These fields did not exist before this version. The ORM default
            # would otherwise use the company performing the upgrade.
            values = {
                'company_id': session.company_id.id,
                'product_state_id': line.lot_id.product_state_id.id or session.default_state_id.id,
                'reconciliation_key': json.dumps([
                    line.product_id.id, line.lot_name or '',
                    False if line.product_id.tracking == 'serial' else line.location_id.id,
                ]),
            }
            # We cannot distinguish past manual edits from generated values.
            # Preserve the existing review explicitly on its first rebuild.
            overrides = {key: values[key] for key in ('company_id', 'product_state_id')}
            overrides.update({
                'product_id': line.product_id.id, 'location_id': line.location_id.id,
                'counted_qty': line.counted_qty, 'to_apply': line.to_apply,
            })
            values['review_overrides'] = overrides
            line.with_context(reconciliation_generated=True).write(values)
        session.operator_ids.filtered(lambda op: not op.current_state_id).write({
            'current_state_id': session.default_state_id.id,
        })
    # Historical scans have no recorded operator choice. Leave their state
    # empty instead of inventing evidence; reconciliation falls back to lot.
