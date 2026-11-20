# -*- coding: utf-8 -*-
"""Ajustes de datos para el acceso de los Product Managers a los clientes de
oportunidades abiertas. Los usa el script de migración 19.0.1.12.0."""

import ast
import logging
import unicodedata

_logger = logging.getLogger(__name__)

# Etapas finales: en ellas el Product Manager deja de ver el cliente.
CLOSING_STAGE_WORDS = ('entregad', 'perdid', 'eliminad', 'delivered', 'lost')

# Regla hecha a mano en producción que deja ver todos los contactos a varios
# grupos; se le quita el de Product Managers.
OWN_CONTACTS_RULE_NAME = 'CUSTOM/Contactos propios'
PM_SEE_ALL_MARKER = 'custom.product_managers'


def _plain(text):
    text = unicodedata.normalize('NFKD', text or '')
    return ''.join(ch for ch in text if not unicodedata.combining(ch)).lower()


def mark_pm_closing_stages(env):
    """Marca «Cierra el acceso de Product Managers» en las etapas cuyo nombre
    (en cualquiera de los idiomas instalados) es de cierre. Devuelve las etapas marcadas."""
    Stage = env['crm.stage'].with_context(active_test=False)
    closing = Stage.browse()
    langs = [code for code, _name in env['res.lang'].get_installed()] or ['en_US']
    for stage in Stage.search([]):
        names = {stage.with_context(lang=lang).name for lang in langs}
        if any(word in _plain(name) for name in names for word in CLOSING_STAGE_WORDS):
            closing |= stage
    closing.write({'rms_closes_pm_access': True})
    _logger.info('Etapas que cierran el acceso de Product Managers: %s', closing.mapped('name'))
    return closing


def remove_or_term(domain, marker):
    """Quita de un dominio de la forma ['|', ..., '|', t1, ..., tn] (todo
    términos unidos con OR) los términos cuyo texto contiene `marker`, y un
    '|' por cada uno. Devuelve el dominio nuevo, o None si no tiene esa forma
    o no hay nada que quitar."""
    try:
        node = ast.parse(domain.strip(), mode='eval').body
    except SyntaxError:
        return None
    if not isinstance(node, ast.List):
        return None
    elts = node.elts
    n_ors = 0
    while n_ors < len(elts) and isinstance(elts[n_ors], ast.Constant) and elts[n_ors].value == '|':
        n_ors += 1
    terms = elts[n_ors:]
    if not terms or n_ors != len(terms) - 1 or not all(isinstance(t, ast.Tuple) for t in terms):
        return None
    source = domain.strip()
    texts = [ast.get_source_segment(source, t) for t in terms]
    keep = [t for t in texts if marker not in t]
    if len(keep) == len(texts) or not keep:
        return None
    return '[%s]' % ', '.join(["'|'"] * (len(keep) - 1) + keep)


def drop_pm_see_all(env):
    """Quita a los Product Managers de la regla «CUSTOM/Contactos propios»."""
    rules = env['ir.rule'].with_context(active_test=False).search([
        ('model_id.model', '=', 'res.partner'), ('name', '=', OWN_CONTACTS_RULE_NAME),
    ])
    for rule in rules:
        new_domain = remove_or_term(rule.domain_force or '', PM_SEE_ALL_MARKER)
        if new_domain:
            _logger.info('Regla %s (%s): %s -> %s', rule.id, rule.name, rule.domain_force, new_domain)
            rule.domain_force = new_domain
        elif PM_SEE_ALL_MARKER in (rule.domain_force or ''):
            _logger.warning('Regla %s (%s): formato inesperado, no se modifica: %s',
                            rule.id, rule.name, rule.domain_force)
    return rules
