# -*- coding: utf-8 -*-
"""Aplicar y deshacer la carga de arranque.

Las existencias se crean como hace Odoo en un ajuste de inventario: un
movimiento de stock desde la ubicación «Ajuste de inventario» de la empresa
hasta el destino, validado con _action_done(). Así los quants, la
trazabilidad del nº de serie y la valoración los calcula Odoo (no se escribe
ningún quant a mano). «Deshacer» crea los movimientos contrarios.
"""
import time
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.rms_stock_count_session.models.sage_expected import normalize_serial

from .initial_load import SITE_NAMES

BATCH = 500


class InitialLoad(models.Model):
    _inherit = 'rms.initial.load'

    # ------------------------------------------------------------------ utilidades
    @api.model
    def _rms_loss_location(self, company, product):
        """Ubicación «Ajuste de inventario» de la empresa (la misma que usa Odoo
        al aplicar un inventario)."""
        location = product.with_company(company).property_stock_inventory
        if not location or (location.company_id and location.company_id != company):
            location = self.env['stock.location'].sudo().search([
                ('usage', '=', 'inventory'), ('company_id', '=', company.id), ('rms_phantom', '=', False)],
                order='id', limit=1)
        if not location:
            raise UserError('La empresa %s no tiene ubicación de «Ajuste de inventario».' % company.name)
        return location

    @api.model
    def _rms_move_vals(self, company, product, quantity, source, dest, lot=None, state=None, name=None):
        return {
            'product_id': product.id, 'product_uom': product.uom_id.id, 'product_uom_qty': quantity,
            'company_id': company.id, 'state': 'confirmed', 'location_id': source.id, 'location_dest_id': dest.id,
            'is_inventory': True, 'picked': True, 'inventory_name': name, 'origin': name,
            'move_line_ids': [(0, 0, {
                'product_id': product.id, 'product_uom_id': product.uom_id.id, 'quantity': quantity,
                'location_id': source.id, 'location_dest_id': dest.id, 'company_id': company.id,
                'lot_id': lot.id if lot else False,
                'product_state_id': state.id if state else False,
            })],
        }

    def _check_companies(self, lines):
        missing = lines.company_id - self.env.companies
        if missing:
            raise UserError(
                'La carga toca las tres empresas. Activa también %s en el selector de empresas (arriba a la derecha) '
                'y vuelve a intentarlo.' % ', '.join(missing.mapped('name')))

    # ------------------------------------------------------------------ aplicar
    def action_apply(self):
        self.ensure_one()
        self._check_manager()
        if self.state != 'prepared':
            raise UserError('Solo se puede aplicar una carga preparada. Pulsa antes «Preparar».')
        pending = self.review_ids.filtered(lambda r: r.state == 'pending')
        if pending:
            raise UserError(
                'Quedan %d equipos con el estado sin revisar (la lectura no coincide con Sage). '
                'Abre «Revisión de estados» y decide el estado de cada uno antes de aplicar.' % len(pending))
        started = time.time()
        load = self.sudo()
        lines = load.line_ids.filtered(lambda l: l.kind != 'skip' and l.apply_result == 'pending')
        self._check_companies(lines)
        if any(not line.product_id or not line.company_id or line.quantity <= 0 for line in lines):
            raise UserError('Hay líneas sin producto, sin empresa o sin cantidad. Vuelve a preparar la carga.')
        load._apply_destinations(lines)
        lines = load._apply_lots(lines)
        load._apply_moves(lines)
        load._apply_deposits(lines.filtered(lambda l: l.kind == 'deposit'))
        load.write({'state': 'applied', 'applied_at': fields.Datetime.now(), 'applied_by': self.env.user.id,
                    'apply_seconds': time.time() - started})
        load._refresh_summary()
        return True

    def _apply_destinations(self, lines):
        """Ubicaciones fantasma (se crean si faltan) y de depósitos en clientes."""
        Location = self.env['stock.location']
        Cession = self.env['stock.cession']
        for company in lines.filtered(lambda l: l.kind == 'phantom').company_id:
            location = Location._rms_phantom_location(company)
            lines.filtered(lambda l: l.kind == 'phantom' and l.company_id == company).write({'location_id': location.id})
        for company in lines.filtered(lambda l: l.kind == 'deposit').company_id:
            location = Cession._rms_deposit_location(company)
            lines.filtered(lambda l: l.kind == 'deposit' and l.company_id == company).write({'location_id': location.id})
        if any(not line.location_id for line in lines):
            raise UserError('Hay líneas sin ubicación de destino. Vuelve a preparar la carga.')

    def _apply_lots(self, lines):
        """Nº de serie con su estado y sus marcas. Si un nº de serie ya existe
        en Odoo CON existencias no se duplica: la línea queda señalada."""
        Lot = self.env['stock.lot']
        tracked = lines.filtered(lambda l: l.lot_name and l.product_id.tracking != 'none')
        if not tracked:
            return lines
        self.env.cr.execute('SELECT id, product_id, name FROM stock_lot WHERE product_id = ANY(%s)',
                            [tracked.product_id.ids])
        existing = {(product_id, normalize_serial(name)): lot_id for lot_id, product_id, name in self.env.cr.fetchall()}
        with_stock = set()
        if existing:
            for (lot,) in self.env['stock.quant']._read_group(
                    [('lot_id', 'in', list(existing.values())), ('quantity', '>', 0),
                     '|', ('location_id.usage', 'in', ('internal', 'transit')), ('location_id.rms_phantom', '=', True)],
                    ['lot_id']):
                with_stock.add(lot.id)
        duplicates = self.env['rms.initial.load.line']
        to_create, create_lines = [], []
        reuse = defaultdict(lambda: self.env['stock.lot'])
        for line in tracked:
            lot_id = existing.get((line.product_id.id, line.serial_normalized or normalize_serial(line.lot_name)))
            flags = (line.state_id.id, bool(line.unverified), line.kind == 'alta')
            if lot_id and lot_id in with_stock:
                duplicates |= line
                line.lot_id = lot_id
            elif lot_id:
                line.lot_id = lot_id
                reuse[flags] |= Lot.browse(lot_id)
            else:
                to_create.append({
                    'name': line.lot_name, 'product_id': line.product_id.id, 'product_state_id': line.state_id.id,
                    'rms_unverified': flags[1], 'rms_alta_review': flags[2], 'rms_initial_load_id': self.id,
                })
                create_lines.append(line)
        for (state_id, unverified, alta), lots in reuse.items():
            vals = {'rms_unverified': unverified, 'rms_alta_review': alta, 'rms_initial_load_id': self.id}
            if state_id:
                vals['product_state_id'] = state_id
            lots.write(vals)
        for start in range(0, len(to_create), 1000):
            lots = Lot.create(to_create[start:start + 1000])
            for line, lot in zip(create_lines[start:start + 1000], lots):
                line.write({'lot_id': lot.id, 'lot_created': True})
        if duplicates:
            for line in duplicates:
                line.write({'apply_result': 'duplicate', 'note': (
                    'YA TENÍA EXISTENCIAS EN ODOO: no se ha duplicado. ' + (line.note or ''))[:1000]})
        return lines - duplicates

    def _apply_moves(self, lines):
        Move = self.env['stock.move'].with_context(inventory_mode=False)
        Value = self.env['product.value']
        name = 'Carga de arranque: %s' % self.name
        loss = {}
        for company in lines.company_id:
            company_lines = lines.filtered(lambda l: l.company_id == company)
            for product in company_lines.product_id.with_company(company):
                loss[(company.id, product.id)] = product.property_stock_inventory
        valued = {}
        ids = lines.ids
        Line = self.env['rms.initial.load.line']
        for start in range(0, len(ids), BATCH):
            chunk = Line.browse(ids[start:start + BATCH])
            vals_list = []
            for line in chunk:
                company = line.company_id
                source = loss.get((company.id, line.product_id.id)) or self._rms_loss_location(company, line.product_id)
                vals_list.append(self._rms_move_vals(
                    company, line.product_id, line.quantity, source, line.location_id,
                    lot=line.lot_id, state=line.state_id, name=name))
            moves = Move.create(vals_list)
            moves.with_context(ignore_dest_packages=True)._action_done()
            value_vals = []
            for line, move in zip(chunk, moves):
                line.write({'move_id': move.id, 'apply_result': 'done'})
                location = line.location_id
                if location.id not in valued:
                    valued[location.id] = location._should_be_valued()
                # Coste de la línea (si lo hay): valor manual del movimiento, como
                # el botón «Ajustar valoración» de Odoo. Sin coste, Odoo usa el
                # coste del producto.
                if line.cost and valued[location.id]:
                    value_vals.append({'move_id': move.id, 'value': line.cost * line.quantity,
                                       'company_id': line.company_id.id,
                                       'description': 'Coste de la carga de arranque'})
            if value_vals:
                Value.create(value_vals)
            self.env.flush_all()
            self.env.invalidate_all()

    def _apply_deposits(self, lines):
        """Un depósito por cliente y empresa, ya «en el cliente», heredado de Sage."""
        if not lines:
            return
        Cession = self.env['stock.cession']
        Unit = self.env['rms.deposit.unit']
        generic = self.env.ref('rms_stock_initial_load.partner_inherited_deposits')
        groups = defaultdict(lambda: self.env['rms.initial.load.line'])
        for line in lines:
            sage_name = (line.sage_partner_name or '').strip()
            key = (line.company_id.id, line.partner_id.id, sage_name.upper() if line.partner_id == generic else '')
            groups[key] |= line
        for (company_id, partner_id, _name), group in groups.items():
            company = self.env['res.company'].browse(company_id)
            code = group[0].sage_company_code
            sites = [line.site_number for line in group if line.site_number]
            source = False
            if sites:
                site = max(set(sites), key=sites.count)
                source = self.env['stock.location'].browse(self._plan_location({'loc_by': {}}, code, site))
            if not source:
                source = self.env['stock.warehouse'].search([('company_id', '=', company_id)], limit=1).lot_stock_id
            names = sorted({(line.sage_partner_name or '').strip() for line in group if line.sage_partner_name})
            dates = [line.deposit_date for line in group if line.deposit_date]
            first = min(dates) if dates else self.date
            cession = Cession.with_company(company).create({
                'company_id': company_id, 'partner_id': partner_id,
                'date': fields.Datetime.to_datetime(first),
                'location_src_id': source.id, 'location_dest_id': group[0].location_id.id,
                'rms_inherited_from_sage': True, 'rms_sage_partner_name': ' / '.join(names)[:250],
                'rms_initial_load_id': self.id,
                'notes': 'Heredado de Sage, sin firma. Creado por la carga de arranque «%s». '
                         'Entró según Sage, sin verificar.' % self.name,
            })
            cession.write({'state': 'done'})
            Unit.create([{
                'cession_id': cession.id, 'product_id': line.product_id.id, 'lot_id': line.lot_id.id,
                'quantity': line.quantity,
                'date_out': fields.Datetime.to_datetime(line.deposit_date or first),
            } for line in group])
            group.write({'cession_id': cession.id})

    # ------------------------------------------------------------------ deshacer
    def action_undo(self):
        """Revierte lo aplicado: movimientos contrarios, depósitos heredados
        borrados y marcas de los nº de serie quitadas."""
        self.ensure_one()
        self._check_manager()
        if self.state != 'applied':
            raise UserError('Solo se puede deshacer una carga aplicada.')
        load = self.sudo()
        lines = load.line_ids.filtered(lambda l: l.apply_result == 'done' and l.move_id and not l.undo_move_id)
        self._check_companies(lines)
        # Nada de lo cargado puede haberse movido ya.
        available = defaultdict(float)
        if lines:
            for location, product, lot, quantity, reserved in self.env['stock.quant']._read_group(
                    [('location_id', 'in', lines.location_id.ids), ('product_id', 'in', lines.product_id.ids)],
                    ['location_id', 'product_id', 'lot_id'], ['quantity:sum', 'reserved_quantity:sum']):
                available[(location.id, product.id, lot.id)] = (quantity or 0.0) - (reserved or 0.0)
        problems = []
        for line in lines:
            key = (line.location_id.id, line.product_id.id, line.lot_id.id)
            available[key] -= line.quantity
            if available[key] < -0.0001:
                problems.append('%s %s (%s)' % (line.product_id.display_name, line.lot_name or '',
                                                SITE_NAMES.get(line.site_number, line.destination or '')))
        if problems:
            raise UserError(
                'No se puede deshacer: %d líneas de la carga ya se han movido, vendido o reservado después. '
                'Por ejemplo:\n- %s' % (len(problems), '\n- '.join(problems[:10])))
        returned = load.cession_ids.rms_unit_ids.filtered(lambda u: u.state != 'out' or u.qty_returned)
        if returned:
            raise UserError('No se puede deshacer: hay depósitos heredados con devoluciones ya registradas (%s).'
                            % ', '.join(returned.cession_id.mapped('name')[:10]))
        Move = self.env['stock.move'].with_context(inventory_mode=False)
        Line = self.env['rms.initial.load.line']
        name = 'Deshacer carga de arranque: %s' % self.name
        ids = lines.ids
        for start in range(0, len(ids), BATCH):
            chunk = Line.browse(ids[start:start + BATCH])
            moves = Move.create([self._rms_move_vals(
                line.company_id, line.product_id, line.quantity, line.move_id.location_dest_id,
                line.move_id.location_id, lot=line.lot_id, state=line.lot_id.product_state_id, name=name)
                for line in chunk])
            moves.with_context(ignore_dest_packages=True)._action_done()
            for line, move in zip(chunk, moves):
                line.write({'undo_move_id': move.id, 'apply_result': 'undone'})
            self.env.flush_all()
            self.env.invalidate_all()
        cessions = load.cession_ids
        if cessions:
            cessions.write({'state': 'cancel'})
            cessions.unlink()
        self.env['stock.lot'].search([('rms_initial_load_id', '=', load.id)]).write({
            'rms_unverified': False, 'rms_alta_review': False, 'rms_initial_load_id': False})
        load.line_ids.filtered(lambda l: l.apply_result == 'duplicate').write({'apply_result': 'undone'})
        load.write({'state': 'undone', 'undone_at': fields.Datetime.now(), 'undone_by': self.env.user.id})
        return True
