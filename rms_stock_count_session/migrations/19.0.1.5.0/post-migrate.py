from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rules = env["rms.scan.rule"].with_context(active_test=False)
    xmlid = "rms_stock_count_session.scan_rule_sony_product_code"
    rule = env.ref(xmlid, raise_if_not_found=False)
    if not rule:
        rule = rules.search([("pattern", "=", r"P-?\d{8}-?[0-9A-Z]"),
                             ("action", "=", "product_code")], limit=1)
    if not rule:
        rule = rules.create({
            "sequence": 10, "name": "Sony: número de pieza P-xxxxxxxx-x",
            "brand": "Sony", "pattern": r"P-?\d{8}-?[0-9A-Z]",
            "action": "product_code", "example": "P81672643J",
        })
    if not env.ref(xmlid, raise_if_not_found=False):
        env["ir.model.data"].create({
            "module": "rms_stock_count_session", "name": "scan_rule_sony_product_code",
            "model": "rms.scan.rule", "res_id": rule.id, "noupdate": True,
        })
