from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .delivery_scan import REASONS
from .tools import clean_code, is_valid_gtin

REVIEW_STATES = ('ex_demo', 'second_hand')
KIND_LABELS = {
    'sale': 'Salida a cliente',
    'deposit_out': 'Depósito: salida',
    'deposit_return': 'Depósito: vuelta',
}


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    rms_check_required = fields.Boolean(
        string='Checklist de salida obligatorio',
        help="Si se marca, los albaranes de este tipo solo se pueden validar "
             "desde el checklist de salida con pistola.")


class StockMove(models.Model):
    _inherit = 'stock.move'

    rms_check_qty = fields.Float(
        string='Cantidad contada (checklist)', copy=False, digits='Product Unit',
        help="Para productos sin nº de serie (accesorios): cantidad anotada en el checklist.")


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    rms_check_state = fields.Selection([
        ('none', 'Sin empezar'),
        ('in_progress', 'En curso'),
        ('pending_admin', 'Pendiente de administrador'),
        ('ready', 'Listo para validar'),
        ('done', 'Validado con checklist'),
    ], string='Checklist', default='none', copy=False, tracking=True, index=True)
    rms_check_scan_ids = fields.One2many('rms.delivery.scan', 'picking_id', string='Lecturas del checklist')
    rms_check_partial = fields.Selection([
        ('backorder', 'Entrega parcial: lo que falta queda pendiente'),
        ('no_backorder', 'Entrega parcial: lo que falta NO queda pendiente'),
    ], string='Decisión de envío parcial', copy=False, tracking=True)
    rms_check_partial_user_id = fields.Many2one('res.users', string='Parcial decidido por', copy=False)
    rms_check_finished_by_id = fields.Many2one('res.users', string='Checklist terminado por', copy=False)
    rms_check_finished_at = fields.Datetime(string='Checklist terminado el', copy=False)
    rms_deposit_role = fields.Selection([
        ('out', 'Salida de depósito'),
        ('return', 'Vuelta de depósito'),
    ], string='Depósito', copy=False, index=True)
    rms_cession_id = fields.Many2one('stock.cession', string='Depósito / cesión', copy=False, index=True)
    rms_check_kind = fields.Selection([
        ('sale', 'Salida a cliente'),
        ('deposit_out', 'Depósito: salida'),
        ('deposit_return', 'Depósito: vuelta'),
    ], string='Tipo de checklist', compute='_compute_rms_check_kind', store=True)
    rms_check_progress = fields.Char(string='Leído', compute='_compute_rms_check_progress')
    rms_check_incident_count = fields.Integer(string='Incidencias', compute='_compute_rms_check_progress')

    @api.depends('rms_deposit_role', 'picking_type_id.code')
    def _compute_rms_check_kind(self):
        for picking in self:
            if picking.rms_deposit_role == 'out':
                picking.rms_check_kind = 'deposit_out'
            elif picking.rms_deposit_role == 'return':
                picking.rms_check_kind = 'deposit_return'
            elif picking.picking_type_id.code == 'outgoing':
                picking.rms_check_kind = 'sale'
            else:
                picking.rms_check_kind = False

    def _compute_rms_check_progress(self):
        for picking in self:
            if not picking.rms_check_kind:
                picking.rms_check_progress = False
                picking.rms_check_incident_count = 0
                continue
            summary = picking._rms_summary()
            picking.rms_check_progress = _("%(read)s de %(total)s", read=_fmt(summary['read']), total=_fmt(summary['total']))
            picking.rms_check_incident_count = len(picking.rms_check_scan_ids.filtered('is_incident'))

    # ------------------------------------------------------------------ util
    def _rms_is_manager(self):
        return self.env.su or self.env.user.has_group('stock.group_stock_manager')

    def _rms_require_manager(self):
        if not self._rms_is_manager():
            raise AccessError(_("Esto solo lo puede decidir un responsable de inventario."))

    def _rms_lock(self):
        self.ensure_one()
        self.check_access('write')
        self.env.cr.execute("SELECT id FROM stock_picking WHERE id = %s FOR UPDATE", [self.id])

    def _rms_check_moves(self):
        return self.move_ids.filtered(lambda m: m.state != 'cancel').sorted(lambda m: (m.sequence, m.id))

    @staticmethod
    def _rms_demand(move):
        return move.product_uom_qty

    @staticmethod
    def _rms_is_serial(move):
        return move.product_id.tracking == 'serial'

    def _rms_expected(self, move):
        """(nº de serie fijados en el pedido, estado pedido). Fuera de una venta
        no se exige estado (en un depósito puede salir cualquiera)."""
        Lot = self.env['stock.lot']
        if self.rms_check_kind != 'sale':
            return Lot, self.env['product.state']
        line = move.sale_line_id.sudo()
        if line and line.serial_ids:
            lots = line.serial_ids.lot_id
            return lots, lots[0].product_state_id
        if line and line.rms_requested_state_id:
            return Lot, line.rms_requested_state_id
        return Lot, self.env.ref('rms_product_state.state_new')

    def _rms_summary(self):
        self.ensure_one()
        scans = self.rms_check_scan_ids.filtered(lambda s: not s.undone)
        total = read = 0.0
        for move in self._rms_check_moves():
            demand = self._rms_demand(move)
            total += demand
            if self._rms_is_serial(move):
                read += len(scans.filtered(lambda s: s.move_id == move and s._counts()))
            else:
                read += min(move.rms_check_qty, demand)
        return {
            'total': total,
            'read': read,
            'missing': max(total - read, 0.0),
            'pending': scans.filtered(lambda s: s.result == 'amber' and s.approval_state == 'pending'),
            'unreviewed': scans.filtered(lambda s: s._occupies() and s.needs_review and not s.reviewed),
            'blocked': len(self.rms_check_scan_ids.filtered(lambda s: s.result == 'red')),
        }

    def _rms_check_can_operate(self):
        self.ensure_one()
        if not self.rms_check_kind:
            raise UserError(_("Este albarán no es una salida ni un depósito: no tiene checklist."))
        if self.state in ('done', 'cancel'):
            raise UserError(_("Este albarán ya está cerrado."))
        if self.state == 'draft':
            raise UserError(_("Primero hay que confirmar el albarán (botón «Marcar por realizar»)."))
        if self.rms_check_state in ('pending_admin', 'ready'):
            raise UserError(_(
                "El checklist ya se dio por terminado. Para seguir leyendo, pulsa «Seguir leyendo» "
                "(si está pendiente de administrador, lo tiene que devolver él)."))
        if self.rms_check_state == 'none':
            self.sudo().rms_check_state = 'in_progress'

    # --------------------------------------------------------------- abrir
    def action_open_delivery_check(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'rms_stock_delivery_check.checklist',
            'name': _("Checklist %s", self.name),
            'params': {'picking_id': self.id},
            'context': {'active_id': self.id},
        }

    def action_view_delivery_scans(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rms_stock_delivery_check.action_delivery_scan')
        action['domain'] = [('picking_id', '=', self.id)]
        action['context'] = {}
        return action

    # -------------------------------------------------------------- lectura
    def rms_check_scan(self, code):
        self._rms_lock()
        self._rms_check_can_operate()
        cleaned = clean_code(code)
        if not cleaned:
            return {'scan_id': False, 'state': self.rms_check_get_state()}
        vals = self._rms_evaluate_code(cleaned)
        vals.update({
            'picking_id': self.id, 'code': (code or '').strip()[:200], 'code_clean': cleaned[:200],
            'user_id': self.env.uid, 'scanned_at': fields.Datetime.now(),
        })
        if vals['result'] == 'amber':
            vals['approval_state'] = 'pending'
        scan = self.env['rms.delivery.scan'].sudo().create(vals)
        self._rms_sync_packs()
        return {'scan_id': scan.id, 'state': self.rms_check_get_state()}

    def _rms_find_lot(self, code, products):
        Lot = self.env['stock.lot'].sudo()
        company_domain = [('company_id', 'in', [False, self.company_id.id])]
        lots = Lot.search([('name', '=', code)] + company_domain)
        if not lots and code.upper() != code:
            lots = Lot.search([('name', '=', code.upper())] + company_domain)
        return lots.filtered(lambda l: l.product_id in products)[:1] or lots[:1]

    def _rms_stock_problem(self, lot):
        """(motivo, explicación) si el nº de serie no puede salir de aquí."""
        Quant = self.env['stock.quant'].sudo()
        here = Quant.search([
            ('lot_id', '=', lot.id), ('quantity', '>', 0),
            ('location_id', 'child_of', self.location_id.id)], limit=1)
        if not here:
            other = Quant.search([
                ('lot_id', '=', lot.id), ('quantity', '>', 0),
                ('location_id.usage', 'in', ('internal', 'transit'))], limit=1)
            if other:
                return 'not_in_stock', _(
                    "No está en %(here)s: Odoo lo tiene en %(there)s.",
                    here=self.location_id.display_name, there=other.location_id.display_name)
            return 'already_out', _("Ya salió: Odoo no lo tiene en stock.")
        other_scan = self.env['rms.delivery.scan'].sudo().search([
            ('lot_id', '=', lot.id), ('picking_id', '!=', self.id), ('undone', '=', False),
            ('result', 'in', ('ok', 'amber')), ('approval_state', '!=', 'rejected'),
            ('picking_id.state', 'not in', ('done', 'cancel'))], limit=1)
        if other_scan:
            return 'reserved_other', _("Ya está leído en otro albarán (%s).", other_scan.picking_id.name)
        other_line = self._rms_other_reservations(lot).filtered(
            lambda l: lot in l.move_id.sale_line_id.sudo().serial_ids.lot_id)[:1]
        if other_line:
            return 'reserved_other', _(
                "Está vendido con este nº de serie en otro albarán (%s).", other_line.picking_id.name)
        return None, None

    def _rms_other_reservations(self, lot):
        return self.env['stock.move.line'].sudo().search([
            ('lot_id', '=', lot.id), ('state', 'not in', ('done', 'cancel')),
            ('picking_id', '!=', self.id), ('quantity', '>', 0),
            ('location_id', 'child_of', self.location_id.id)])

    def _rms_evaluate_code(self, code):
        """Veredicto de una lectura: valores de rms.delivery.scan."""
        self.ensure_one()
        kind = self.rms_check_kind
        moves = self._rms_check_moves()
        serial_moves = moves.filtered(self._rms_is_serial)
        lot = self._rms_find_lot(code, serial_moves.product_id)

        if not lot:
            Product = self.env['product.product'].sudo()
            product = Product.search(['|', ('barcode', '=', code), ('default_code', '=', code)], limit=1)
            if product or is_valid_gtin(code):
                if product and product in moves.product_id and product.tracking != 'serial':
                    message = _("%s va por cantidad: anótala con los botones + y −.", product.display_name)
                elif product:
                    message = _("Es el código del producto %s, no un nº de serie. Lee el nº de serie de la caja.",
                                product.display_name)
                else:
                    message = _("Es un código de producto (EAN), no un nº de serie. Lee el nº de serie de la caja.")
                return {'result': 'grey', 'reason': 'product_code', 'message': message,
                        'product_id': product.id or False}
            return {'result': 'red', 'reason': 'unknown',
                    'message': _("Este nº de serie no existe en Odoo. Aparta la caja y avisa.")}

        state = lot.product_state_id
        vals = {'lot_id': lot.id, 'product_id': lot.product_id.id, 'state_id': state.id}

        def verdict(result, reason, message, **extra):
            return dict(vals, result=result, reason=reason, message=message, **extra)

        active = self.rms_check_scan_ids.filtered(lambda s: s.lot_id == lot and s._occupies())
        if active:
            return verdict('duplicate', 'already_read', _("Ya leído (%s).", active[0].user_id.name))

        product_moves = serial_moves.filtered(lambda m: m.product_id == lot.product_id)
        if not product_moves:
            return verdict('red', 'not_in_picking', _(
                "%s no está en este albarán. No debe salir.", lot.product_id.display_name))

        if kind == 'deposit_return' and self.rms_cession_id:
            out_lots = self.rms_cession_id.rms_unit_ids.filtered(lambda u: u.state == 'out').lot_id
            if lot not in out_lots:
                return verdict('red', 'not_in_deposit', _("Este equipo no consta como entregado en este depósito."))

        reason, message = self._rms_stock_problem(lot)
        if reason:
            return verdict('red', reason, message)

        if kind == 'sale' and state.code == 'demo':
            return verdict('red', 'demo_sale', _("Es un equipo DEMO: no se vende. No debe salir."))

        # Línea del albarán a la que se apunta.
        scans = self.rms_check_scan_ids
        free = product_moves.filtered(
            lambda m: len(scans.filtered(lambda s: s.move_id == m and s._occupies())) < self._rms_demand(m))
        expected = {move: self._rms_expected(move) for move in product_moves}
        fixed_here = product_moves.filtered(lambda m: lot in expected[m][0])
        if fixed_here:
            move = (fixed_here & free)[:1]
        else:
            move = free.filtered(lambda m: not expected[m][0])[:1] or free[:1]
        if not move:
            return verdict('red', 'over_qty', _(
                "Ya están leídas todas las unidades de %s. Esta caja sobra.", lot.product_id.display_name))
        vals['move_id'] = move.id
        vals['needs_review'] = kind != 'deposit_return' and state.code in REVIEW_STATES

        fixed_lots, wanted_state = expected[move]
        if fixed_lots and lot not in fixed_lots:
            return verdict('amber', 'serial_mismatch', _(
                "El pedido fija otro nº de serie (%s). Lo decide el administrador.",
                ', '.join(fixed_lots.mapped('name'))))
        if wanted_state and state != wanted_state:
            return verdict('amber', 'state_mismatch', _(
                "El pedido es de estado %(wanted)s y este equipo es %(real)s. Lo decide el administrador.",
                wanted=wanted_state.name, real=state.name))
        if kind == 'sale' and state.code == 'second_hand':
            pack = self.env['rms.used.pack']._pack_of_lot(lot, self.company_id)
            if not pack:
                return verdict('amber', 'used_no_pack', _(
                    "2ª mano sin paquete autorizado por Dirección. Lo decide el administrador."))
            vals['pack_id'] = pack.id
        return verdict('ok', 'ok', _("Correcto"))

    def _rms_sync_packs(self):
        """Un paquete de 2ª mano sale entero: sus lecturas están en ámbar
        mientras falte alguno de sus equipos y pasan a verde al completarlo."""
        self.ensure_one()
        scans = self.rms_check_scan_ids.sudo().filtered(
            lambda s: not s.undone and s.pack_id and s.reason in ('ok', 'pack_incomplete')
            and s.approval_state in ('none', 'pending'))
        for pack in scans.pack_id:
            pack_scans = scans.filtered(lambda s: s.pack_id == pack)
            missing = pack.lot_ids - pack_scans.lot_id if pack.state == 'authorized' else pack.lot_ids.browse()
            if not missing:
                pack_scans.filtered(lambda s: s.reason == 'pack_incomplete').write({
                    'result': 'ok', 'reason': 'ok', 'approval_state': 'none',
                    'message': _("Correcto (paquete «%s» completo)", pack.name),
                })
                continue
            pack_scans.write({
                'result': 'amber', 'reason': 'pack_incomplete', 'approval_state': 'pending',
                'message': _(
                    "Paquete «%(pack)s»: faltan %(n)s de %(total)s (%(serials)s). Se vende entero.",
                    pack=pack.name, n=len(missing), total=len(pack.lot_ids),
                    serials=', '.join(missing.mapped('name'))),
            })

    def rms_check_undo(self, scan_id):
        self._rms_lock()
        self._rms_check_can_operate()
        scan = self.rms_check_scan_ids.sudo().filtered(lambda s: s.id == scan_id and not s.undone)
        if scan:
            scan.write({'undone': True, 'undone_by_id': self.env.uid, 'undone_at': fields.Datetime.now()})
            self._rms_sync_packs()
        return self.rms_check_get_state()

    def rms_check_set_reviewed(self, scan_id, value):
        self._rms_lock()
        self._rms_check_can_operate()
        scan = self.rms_check_scan_ids.sudo().filtered(lambda s: s.id == scan_id and s.needs_review)
        scan.write({
            'reviewed': bool(value),
            'reviewed_by_id': self.env.uid if value else False,
            'reviewed_at': fields.Datetime.now() if value else False,
        })
        return self.rms_check_get_state()

    def rms_check_set_qty(self, move_id, qty):
        self._rms_lock()
        self._rms_check_can_operate()
        move = self._rms_check_moves().filtered(lambda m: m.id == move_id and not self._rms_is_serial(m))
        if not move:
            raise UserError(_("Esa línea no va por cantidad."))
        qty = max(float(qty or 0.0), 0.0)
        if qty > self._rms_demand(move):
            raise UserError(_("No puede salir más cantidad de la que pide el albarán."))
        move.sudo().rms_check_qty = qty
        return self.rms_check_get_state()

    # ------------------------------------------------------------- terminar
    def rms_check_finish(self):
        """«He terminado». Todo verde y revisado: listo para validar. Con
        ámbar o faltando unidades: pasa al administrador."""
        self._rms_lock()
        self._rms_check_can_operate()
        self._rms_sync_packs()
        summary = self._rms_summary()
        if not summary['read'] and not summary['pending']:
            raise UserError(_("Todavía no has leído nada."))
        if summary['unreviewed']:
            raise UserError(_(
                "Falta marcar «Revisado» en %(n)s equipo(s) Ex-Demo / 2ª mano: %(serials)s",
                n=len(summary['unreviewed']), serials=', '.join(summary['unreviewed'].mapped('lot_id.name'))))
        vals = {'rms_check_finished_by_id': self.env.uid, 'rms_check_finished_at': fields.Datetime.now()}
        partial_ok = self.rms_check_kind == 'deposit_return'  # lo que no vuelve sigue en el cliente
        if summary['pending'] or (summary['missing'] and not partial_ok):
            self.sudo().write(dict(vals, rms_check_state='pending_admin', rms_check_partial=False))
            lines = [escape(_("%(serial)s: %(why)s", serial=s.lot_id.name or s.code, why=s.message or ''))
                     for s in summary['pending']]
            if summary['missing']:
                lines.append(escape(_("Faltan %s unidad(es) por leer.", _fmt(summary['missing']))))
            self.message_post(body=Markup("%s<br/>%s") % (
                escape(_("Checklist de salida pendiente de administrador (terminado por %s):", self.env.user.name)),
                Markup("<br/>").join(lines)))
            status = 'pending_admin'
        else:
            self.sudo().write(dict(vals, rms_check_state='ready'))
            status = 'ready'
        return {'status': status, 'state': self.rms_check_get_state()}

    def rms_check_reopen(self):
        """Volver a leer. Desde «pendiente de administrador» solo lo devuelve
        el administrador."""
        self._rms_lock()
        if self.rms_check_state == 'pending_admin':
            self._rms_require_manager()
        elif self.rms_check_state != 'ready':
            return self.rms_check_get_state()
        self.sudo().write({'rms_check_state': 'in_progress', 'rms_check_partial': False})
        return self.rms_check_get_state()

    def _rms_after_admin(self):
        if self.rms_check_state != 'pending_admin':
            return
        summary = self._rms_summary()
        if not summary['pending'] and not summary['unreviewed'] and (
                not summary['missing'] or self.rms_check_partial) and summary['read']:
            self.sudo().rms_check_state = 'ready'

    def _rms_admin_scans(self, scan_id):
        self._rms_lock()
        self._rms_require_manager()
        scan = self.rms_check_scan_ids.sudo().filtered(
            lambda s: s.id == scan_id and not s.undone and s.approval_state == 'pending')
        if not scan:
            raise UserError(_("Esa lectura ya no está pendiente de decisión."))
        if scan.reason == 'pack_incomplete':
            # Un paquete se decide entero.
            scan = self.rms_check_scan_ids.sudo().filtered(
                lambda s: s.pack_id == scan.pack_id and not s.undone and s.approval_state == 'pending')
        return scan

    def rms_check_approve(self, scan_id, note=False):
        scans = self._rms_admin_scans(scan_id)
        if scans[0].reason == 'pack_incomplete':
            pack = scans[0].pack_id
            pack._break(_(
                "Roto en el albarán %(picking)s: salen %(out)s. %(note)s",
                picking=self.name, out=', '.join(scans.mapped('lot_id.name')), note=note or ''))
        scans.write({
            'approval_state': 'approved', 'approved_by_id': self.env.uid,
            'approved_at': fields.Datetime.now(), 'approval_note': note or False,
            'incident_resolved': True, 'incident_resolved_by_id': self.env.uid,
        })
        self.message_post(body=_(
            "Checklist: %(user)s APRUEBA %(serials)s (%(why)s). %(note)s",
            user=self.env.user.name, serials=', '.join(scans.mapped('lot_id.name')),
            why=dict(REASONS).get(scans[0].reason), note=note or ''))
        self._rms_after_admin()
        return self.rms_check_get_state()

    def rms_check_reject(self, scan_id, note=False):
        scans = self._rms_admin_scans(scan_id)
        scans.write({
            'approval_state': 'rejected', 'approved_by_id': self.env.uid,
            'approved_at': fields.Datetime.now(), 'approval_note': note or False,
            'incident_resolved': True, 'incident_resolved_by_id': self.env.uid,
        })
        self.message_post(body=_(
            "Checklist: %(user)s RECHAZA %(serials)s (%(why)s): no sale. %(note)s",
            user=self.env.user.name, serials=', '.join(scans.mapped('lot_id.name')),
            why=dict(REASONS).get(scans[0].reason), note=note or ''))
        self._rms_after_admin()
        return self.rms_check_get_state()

    def rms_check_decide_partial(self, decision):
        self._rms_lock()
        self._rms_require_manager()
        if decision not in ('backorder', 'no_backorder'):
            raise UserError(_("Decisión no válida."))
        if self.rms_check_state != 'pending_admin':
            raise UserError(_("El checklist no está pendiente de administrador."))
        self.sudo().write({'rms_check_partial': decision, 'rms_check_partial_user_id': self.env.uid})
        self._rms_after_admin()
        return self.rms_check_get_state()

    def rms_check_reset(self):
        """El administrador anula el checklist (las lecturas quedan guardadas
        como deshechas) y el albarán vuelve a poder validarse a mano."""
        self._rms_lock()
        self._rms_require_manager()
        if self.state == 'done':
            raise UserError(_("El albarán ya está validado."))
        self.rms_check_scan_ids.sudo().filtered(lambda s: not s.undone).write({
            'undone': True, 'undone_by_id': self.env.uid, 'undone_at': fields.Datetime.now()})
        self._rms_check_moves().sudo().write({'rms_check_qty': 0.0})
        self.sudo().write({'rms_check_state': 'none', 'rms_check_partial': False})
        self.message_post(body=_("Checklist de salida anulado por %s.", self.env.user.name))
        return True

    # -------------------------------------------------------------- validar
    def rms_check_validate(self):
        """Valida el albarán con EXACTAMENTE los nº de serie leídos."""
        self._rms_lock()
        if self.rms_check_state != 'ready':
            raise UserError(_("Primero pulsa «He terminado»."))
        if self.state in ('done', 'cancel'):
            raise UserError(_("Este albarán ya está cerrado."))
        self._rms_sync_packs()
        summary = self._rms_summary()
        partial_ok = self.rms_check_kind == 'deposit_return'
        if summary['pending'] or summary['unreviewed'] or not summary['read'] or (
                summary['missing'] and not (self.rms_check_partial or partial_ok)):
            self.sudo().rms_check_state = 'in_progress'
            raise UserError(_("El checklist ha cambiado y ya no está completo. Vuelve a pulsar «He terminado»."))
        self._rms_apply_scans()
        context = {'rms_check_validated': True, 'skip_backorder': True, 'skip_sms': True}
        if summary['missing'] and (partial_ok or self.rms_check_partial == 'no_backorder'):
            context['picking_ids_not_to_backorder'] = self.ids
        self.with_context(**context).button_validate()
        if self.state != 'done':
            raise UserError(_(
                "Odoo no ha podido validar el albarán. Ábrelo y revisa los avisos, o llama al administrador."))
        self.sudo().rms_check_state = 'done'
        return {'status': 'done', 'state': self.rms_check_get_state()}

    def _rms_apply_scans(self):
        """Escribe en el albarán los nº de serie leídos (y solo esos)."""
        self.ensure_one()
        MoveLine = self.env['stock.move.line']
        Quant = self.env['stock.quant'].sudo()
        counted = self.rms_check_scan_ids.filtered(lambda s: s._counts() and s.lot_id and s.move_id)
        moves = self._rms_check_moves()
        serial_moves = moves.filtered(self._rms_is_serial)
        wanted = {move: counted.filtered(lambda s: s.move_id == move).lot_id for move in serial_moves}
        # 1) fuera las reservas que no corresponden a lo leído
        for move in serial_moves:
            move.move_line_ids.filtered(lambda l: l.lot_id not in wanted[move]).unlink()
        # 2) una línea por nº de serie leído, desde su ubicación real
        for move in serial_moves:
            for lot in wanted[move] - move.move_line_ids.lot_id:
                quant = Quant.search([
                    ('lot_id', '=', lot.id), ('quantity', '>', 0),
                    ('location_id', 'child_of', self.location_id.id)], limit=1)
                if not quant:
                    raise UserError(_("El nº de serie %s ya no está en stock en el origen.", lot.name))
                others = self._rms_other_reservations(lot)
                other_moves = others.move_id
                others.unlink()  # otro albarán lo tenía reservado «el que sea»: se le busca otro
                MoveLine.create({
                    'move_id': move.id, 'picking_id': self.id, 'company_id': self.company_id.id,
                    'product_id': move.product_id.id, 'product_uom_id': move.product_id.uom_id.id,
                    'lot_id': lot.id, 'product_state_id': lot.product_state_id.id,
                    'location_id': quant.location_id.id, 'location_dest_id': move.location_dest_id.id,
                    'quantity': 1.0,
                })
                other_moves._action_assign()
            for line in move.move_line_ids:
                if line.quantity != 1.0:
                    line.quantity = 1.0
            move.picked = True
        # 3) accesorios por cantidad
        for move in moves - serial_moves:
            move.quantity = min(move.rms_check_qty, self._rms_demand(move))
            move.picked = True

    def button_validate(self):
        if not self.env.context.get('rms_check_validated'):
            for picking in self:
                if picking.state in ('done', 'cancel') or not picking.rms_check_kind:
                    continue
                if picking.rms_check_state in ('in_progress', 'pending_admin', 'ready'):
                    raise UserError(_(
                        "El albarán %s tiene un checklist de salida abierto: se valida desde el checklist "
                        "(botón «Abrir checklist»). Un administrador puede anularlo.", picking.name))
                if picking.picking_type_id.rms_check_required:
                    raise UserError(_(
                        "Los albaranes de «%s» solo se validan desde el checklist de salida "
                        "(botón «Abrir checklist»).", picking.picking_type_id.name))
        return super().button_validate()

    def _create_backorder(self, backorder_moves=None):
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        for backorder in backorders:
            origin = backorder.backorder_id
            if origin.rms_deposit_role:
                backorder.sudo().write({
                    'rms_deposit_role': origin.rms_deposit_role, 'rms_cession_id': origin.rms_cession_id.id})
        return backorders

    def _action_done(self):
        res = super()._action_done()
        for picking in self.filtered(lambda p: p.state == 'done'):
            if picking.rms_cession_id and picking.rms_deposit_role:
                picking.rms_cession_id.sudo()._rms_picking_done(picking)
            if picking.rms_check_kind == 'sale':
                lots = picking.move_line_ids.lot_id
                packs = self.env['rms.used.pack'].sudo().search([
                    ('state', '=', 'authorized'), ('lot_ids', 'in', lots.ids)]) if lots else []
                for pack in packs:
                    if not (pack.lot_ids - lots):
                        pack.state = 'sold'
                        pack.message_post(body=_("Paquete vendido entero en el albarán %s.", picking.name))
        return res

    # ---------------------------------------------------------- para la pantalla
    def rms_check_get_state(self):
        self.ensure_one()
        self.check_access('read')
        scans_all = self.rms_check_scan_ids.sorted(lambda s: (s.scanned_at, s.id), reverse=True)
        scans = scans_all.filtered(lambda s: not s.undone)
        summary = self._rms_summary()
        editable = self.rms_check_state in ('none', 'in_progress') and self.state not in ('done', 'cancel', 'draft')
        reason_labels = dict(REASONS)

        def when(dt):
            return fields.Datetime.context_timestamp(self, dt).strftime('%H:%M') if dt else ''

        def unit(scan):
            return {
                'scan_id': scan.id,
                'serial': scan.lot_id.name,
                'lot_id': scan.lot_id.id,
                'state_name': scan.state_id.name or '',
                'state_code': scan.state_id.code or '',
                'result': scan.result,
                'reason': scan.reason,
                'reason_label': reason_labels.get(scan.reason, ''),
                'message': scan.message or '',
                'needs_review': scan.needs_review,
                'reviewed': scan.reviewed,
                'approval': scan.approval_state,
                'approved_by': scan.approved_by_id.name or '',
                'pack': scan.pack_id.name or '',
                'user': scan.user_id.name,
                'time': when(scan.scanned_at),
            }

        groups = []
        for move in self._rms_check_moves():
            serial = self._rms_is_serial(move)
            demand = self._rms_demand(move)
            fixed_lots, wanted_state = self._rms_expected(move)
            move_scans = scans.filtered(lambda s: s.move_id == move and s.result in ('ok', 'amber'))
            done = len(move_scans.filtered(lambda s: s._counts())) if serial else min(move.rms_check_qty, demand)
            groups.append({
                'move_id': move.id,
                'product': move.product_id.display_name,
                'by_qty': not serial,
                'demand': demand,
                'done': done,
                'complete': done >= demand,
                'wanted_state': wanted_state.name if wanted_state and wanted_state.code != 'new' else '',
                'fixed_missing': (fixed_lots - move_scans.filtered(lambda s: s._occupies()).lot_id).mapped('name'),
                'units': [unit(s) for s in move_scans.sorted(lambda s: (s.scanned_at, s.id))],
            })

        feed = [{
            'id': scan.id,
            'code': scan.lot_id.name or scan.code_clean or scan.code,
            'product': scan.product_id.display_name or '',
            'result': scan.result,
            'label': reason_labels.get(scan.reason, ''),
            'message': scan.message or '',
            'user': scan.user_id.name,
            'time': when(scan.scanned_at),
            'undone': scan.undone,
            'can_undo': editable and not scan.undone and scan.result in ('ok', 'amber'),
            'lot_id': scan.lot_id.id,
        } for scan in scans_all[:40]]

        outside = []
        if self.rms_check_kind == 'deposit_return' and self.rms_cession_id:
            read_lots = scans.filtered(lambda s: s._counts()).lot_id
            outside = [{
                'product': u.product_id.display_name, 'serial': u.lot_id.name or '',
                'qty': u.quantity - u.qty_returned, 'days': u.days_out,
                'back': bool(u.lot_id and u.lot_id in read_lots),
            } for u in self.rms_cession_id.rms_unit_ids.filtered(lambda u: u.state == 'out')]

        return {
            'picking': {
                'id': self.id,
                'name': self.name,
                'partner': self.partner_id.display_name or '',
                'origin': self.origin or '',
                'kind': self.rms_check_kind,
                'kind_label': KIND_LABELS.get(self.rms_check_kind, ''),
                'state': self.state,
                'check_state': self.rms_check_state,
                'partial': self.rms_check_partial or '',
                'company': self.company_id.name,
                'source': self.location_id.display_name,
            },
            'is_manager': self._rms_is_manager(),
            'editable': editable,
            'groups': groups,
            'feed': feed,
            'outside': outside,
            'last_scan_id': scans_all[:1].id or 0,
            'counters': {
                'read': summary['read'],
                'total': summary['total'],
                'missing': summary['missing'],
                'amber': len(summary['pending']),
                'blocked': summary['blocked'],
                'unreviewed': len(summary['unreviewed']),
            },
            'label_report': 'rms_stock_lot_label_print.report_lot_label_10x5_document',
        }


def _fmt(value):
    return ('%g' % value) if value is not None else '0'
