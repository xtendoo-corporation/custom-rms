from collections import Counter, defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import format_datetime

REPORT_DAYS = 7
TOP_CLIENTS = 30
TOP_INTERESTS = 20
TOP_CARDS = 10
TOP_SEARCHES = 10
RECIPIENT_GROUP = 'rms_portal_access_log.group_portal_weekly_report'
LEVEL_STYLE = {
    'hot': ('Caliente', '#c0392b'),
    'warm': ('Templado', '#d68910'),
    'cold': ('Frío', '#2e86c1'),
}


class PortalWeeklyReport(models.AbstractModel):
    _name = 'rms.portal.weekly.report'
    _description = 'Informe semanal de actividad en el portal'

    @api.model
    def _get_recipients(self):
        users = self.env['res.users'].sudo().search([('share', '=', False)])
        return users.filtered(lambda u: u.email and u.has_group(RECIPIENT_GROUP))

    @api.model
    def _cron_send_weekly_report(self):
        recipients = self._get_recipients()
        if recipients:
            self._send_report(recipients)

    @api.model
    def action_send_now(self):
        """Envía el informe ahora solo al usuario que lo pide (para probarlo)."""
        self._send_report(self.env.user)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Informe enviado',
                'message': 'Te hemos enviado el informe semanal a %s.' % (self.env.user.email or '-'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _send_report(self, recipients):
        date_to = fields.Datetime.now()
        date_from = date_to - timedelta(days=REPORT_DAYS)
        values = self._prepare_report_values(date_from, date_to)
        body = self.env['ir.qweb']._render('rms_portal_access_log.portal_weekly_report_email', values)
        subject = 'Portal de clientes: resumen semanal (%s clientes, %s calientes)' % (
            values['kpis']['clients'], values['kpis']['hot'],
        )
        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_from': self.env.company.email_formatted or self.env.user.email_formatted,
            'email_to': ','.join(recipients.mapped('email_formatted')),
            'auto_delete': True,
        }).send()

    def _prepare_report_values(self, date_from, date_to):
        env = self.env
        Access = env['rms.portal.access.log'].sudo()
        Activity = env['rms.portal.activity'].sudo()
        Interest = env['rms.portal.interest'].sudo()
        tz = env.user.tz or 'Europe/Madrid'

        def fmt(dt, pattern='dd/MM HH:mm'):
            return format_datetime(env, dt, tz=tz, dt_format=pattern) if dt else ''

        accesses = Access.search([('login_date', '>=', date_from), ('login_date', '<', date_to)])
        activities = Activity.search([('date', '>=', date_from), ('date', '<', date_to)])
        partners = accesses.partner_id | activities.partner_id
        interests = Interest.search([
            ('partner_id', 'in', partners.ids), ('last_date', '>=', date_from),
        ], order='score desc, last_date desc')

        best_interest = {}
        for interest in interests:
            best_interest.setdefault(interest.partner_id, interest)

        accesses_by_partner = defaultdict(lambda: Access.browse())
        for access in accesses:
            accesses_by_partner[access.partner_id] |= access
        activities_by_partner = defaultdict(lambda: Activity.browse())
        for activity in activities:
            activities_by_partner[activity.partner_id] |= activity

        clients = []
        for partner in partners:
            partner_accesses = accesses_by_partner[partner]
            partner_activities = activities_by_partner[partner]
            last_seen = max(partner_accesses.mapped('login_date') + partner_activities.mapped('date'))
            best = best_interest.get(partner)
            clients.append({
                'name': partner.display_name,
                'salesperson': partner.commercial_partner_id.user_id.name or partner.user_id.name or '—',
                'logins': len(partner_accesses),
                'actions': len(partner_activities),
                'cards': len(partner_activities.filtered(lambda a: a.activity_type == 'card')),
                'quotes': len(partner_activities.filtered(lambda a: a.activity_type == 'quote_add')),
                'last_seen': fmt(last_seen),
                'last_seen_raw': last_seen,
                'top_card': best.page_title if best else '',
                'top_score': best.score if best else 0,
                'top_level': LEVEL_STYLE[best.level] if best else None,
            })
        clients.sort(key=lambda c: (c['top_score'], c['last_seen_raw']), reverse=True)

        top_interests = [{
            'partner': i.partner_id.display_name,
            'card': i.page_title,
            'brand': i.brand or '',
            'views': i.view_count,
            'prices': i.price_count,
            'quotes': i.quote_count,
            'score': i.score,
            'level': LEVEL_STYLE[i.level],
        } for i in interests.filtered(lambda i: i.level in ('hot', 'warm'))[:TOP_INTERESTS]]

        card_views = activities.filtered(lambda a: a.activity_type == 'card' and a.page_key)
        card_counter = Counter((a.page_title or a.page_key, a.brand or '') for a in card_views)
        card_clients = defaultdict(set)
        for a in card_views:
            card_clients[(a.page_title or a.page_key, a.brand or '')].add(a.partner_id.id)
        top_cards = [{
            'card': title, 'brand': brand, 'views': count, 'clients': len(card_clients[(title, brand)]),
        } for (title, brand), count in card_counter.most_common(TOP_CARDS)]

        empty_searches = Counter(
            (a.name or '').strip().lower()
            for a in activities
            if a.activity_type == 'search' and not a.result_count and a.name
        )

        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        interest_action = env.ref('rms_portal_access_log.action_portal_interest', raise_if_not_found=False)
        return {
            'date_from': fmt(date_from, 'dd/MM/yyyy'),
            'date_to': fmt(date_to, 'dd/MM/yyyy'),
            'kpis': {
                'clients': len(partners),
                'logins': len(accesses),
                'cards': len(card_views),
                'prices': len(activities.filtered(lambda a: a.activity_type == 'prices')),
                'quotes': len(activities.filtered(lambda a: a.activity_type == 'quote_add')),
                'hot': len({i.partner_id.id for i in interests if i.level == 'hot'}),
            },
            'clients': clients[:TOP_CLIENTS],
            'more_clients': max(len(clients) - TOP_CLIENTS, 0),
            'top_interests': top_interests,
            'top_cards': top_cards,
            'empty_searches': empty_searches.most_common(TOP_SEARCHES),
            'interest_url': '%s/odoo/action-%s' % (base_url, interest_action.id) if interest_action else base_url,
            'company': env.company,
        }
