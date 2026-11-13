# -*- coding: utf-8 -*-
"""Caso 3: checklist global de Sage. Vistas SQL de solo lectura que cruzan
TODAS las exportaciones vigentes de Sage con las lecturas de TODOS los
recuentos (menos los cancelados). No guardan nada: siempre al día.

- rms.sage.checklist: una fila por nº de serie de Sage -> leído o no, en
  cuántos recuentos, estado físico marcado y si discrepa de Sage. Es el
  informe de "no leídos" para regularizar en Sage.
- rms.sage.checklist.extra: lecturas cuyo nº de serie no está en Sage
  (altas a revisar).
"""
from odoo import fields, models, tools

SAGE_STATES = [('nuevo', 'Nuevo'), ('demo', 'Demo'), ('2mano', '2ª Mano')]

# Lecturas válidas: nº de serie identificado, no ignoradas, de recuentos no
# cancelados.
_VALID_SCANS = """
    SELECT sc.*
      FROM rms_stock_count_scan sc
      JOIN rms_stock_count_session ss ON ss.id = sc.session_id
     WHERE ss.state <> 'cancel'
       AND NOT COALESCE(sc.ignored, FALSE)
       AND COALESCE(sc.serial_normalized, '') <> ''
"""


class SageChecklist(models.Model):
    _name = 'rms.sage.checklist'
    _description = 'Checklist global de Sage'
    _auto = False
    _order = 'sage_company_code, warehouse_code, article_code, serial'
    _rec_name = 'serial'

    sage_line_id = fields.Many2one('rms.sage.stock.line', string='Línea Sage', readonly=True)
    sage_company_code = fields.Selection([('01', 'RMS'), ('02', 'Espacio'), ('03', 'RJB')],
                                         string='Empresa Sage', readonly=True)
    company_id = fields.Many2one('res.company', string='Empresa', readonly=True)
    brand_categ_id = fields.Many2one('product.category', string='Marca', readonly=True)
    warehouse_code = fields.Char(string='Almacén Sage', readonly=True)
    sage_warehouse_id = fields.Many2one('rms.sage.warehouse', string='Almacén', readonly=True)
    article_code = fields.Char(string='Artículo Sage', readonly=True)
    article_name = fields.Char(string='Nombre en Sage', readonly=True)
    model_code = fields.Char(string='Modelo', readonly=True)
    sage_state = fields.Selection(SAGE_STATES, string='Estado en Sage', readonly=True)
    serial = fields.Char(string='Nº de serie', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    counted = fields.Boolean(string='Leído', readonly=True)
    counted_qty = fields.Integer(string='Leídos', readonly=True)
    pending_qty = fields.Integer(string='Faltan', readonly=True)
    session_count = fields.Integer(string='Nº de recuentos', readonly=True, aggregator=False)
    scan_count = fields.Integer(string='Nº de lecturas', readonly=True, aggregator=False)
    first_scan_id = fields.Many2one('rms.stock.count.scan', string='Primera lectura', readonly=True)
    first_session_id = fields.Many2one('rms.stock.count.session', string='Recuento', readonly=True)
    first_scanned_at = fields.Datetime(string='Leído el', readonly=True)
    physical_state_id = fields.Many2one('product.state', string='Estado físico', readonly=True)
    state_mismatch = fields.Boolean(string='Estado distinto', readonly=True)
    multi_session = fields.Boolean(string='En varios recuentos', readonly=True)
    in_deposit = fields.Boolean(string='En depósito en cliente', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
            WITH scans AS (%s)
            SELECT l.id AS id, l.id AS sage_line_id, l.sage_company_code, l.company_id,
                   l.brand_categ_id, l.warehouse_code, l.sage_warehouse_id, l.article_code,
                   l.article_name, l.model_code, l.state AS sage_state, l.serial, l.product_id,
                   COALESCE(s.scan_count, 0) > 0 AS counted,
                   CASE WHEN COALESCE(s.scan_count, 0) > 0 THEN 1 ELSE 0 END AS counted_qty,
                   -- Lo que Sage tiene en depósito en un cliente no falta en la nave.
                   CASE WHEN COALESCE(s.scan_count, 0) > 0 OR COALESCE(l.in_deposit, FALSE) THEN 0 ELSE 1 END AS pending_qty,
                   COALESCE(l.in_deposit, FALSE) AS in_deposit,
                   COALESCE(s.session_count, 0) AS session_count,
                   COALESCE(s.scan_count, 0) AS scan_count,
                   s.first_scan_id, s.first_session_id, s.first_scanned_at,
                   s.last_state_id AS physical_state_id,
                   COALESCE(s.session_count, 0) > 1 AS multi_session,
                   (s.last_state_id IS NOT NULL AND NOT (
                        (ps.code = 'new' AND l.state = 'nuevo')
                     OR (ps.code = 'demo' AND l.state = 'demo')
                     OR (ps.code = 'second_hand' AND l.state = '2mano'))) AS state_mismatch
              FROM rms_sage_stock_line l
              LEFT JOIN LATERAL (
                    SELECT count(*) AS scan_count,
                           count(DISTINCT sc.session_id) AS session_count,
                           min(sc.id) AS first_scan_id,
                           (array_agg(sc.session_id ORDER BY sc.scanned_at, sc.id))[1] AS first_session_id,
                           min(sc.scanned_at) AS first_scanned_at,
                           (array_agg(sc.product_state_id ORDER BY sc.scanned_at DESC, sc.id DESC))[1] AS last_state_id
                      FROM scans sc
                     WHERE sc.serial_normalized = l.serial_normalized
                       AND sc.scan_type = 'serial'
                       AND (l.product_id IS NULL OR sc.product_id = l.product_id)
              ) s ON TRUE
              LEFT JOIN product_state ps ON ps.id = s.last_state_id
             WHERE l.is_current AND l.stock_kind = 'stock' AND COALESCE(l.serial_normalized, '') <> ''
            )""" % (self._table, _VALID_SCANS))


class SageChecklistExtra(models.Model):
    _name = 'rms.sage.checklist.extra'
    _description = 'Lecturas que no están en Sage (altas)'
    _auto = False
    _order = 'scanned_at desc'
    _rec_name = 'lot_name'

    scan_id = fields.Many2one('rms.stock.count.scan', string='Lectura', readonly=True)
    session_id = fields.Many2one('rms.stock.count.session', string='Recuento', readonly=True)
    operator_id = fields.Many2one('rms.stock.count.operator', string='Operario', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    lot_name = fields.Char(string='Nº de serie', readonly=True)
    code = fields.Char(string='Código leído', readonly=True)
    scan_type = fields.Selection([('serial', 'Nº de serie'), ('unknown', 'Sin identificar')],
                                 string='Tipo', readonly=True)
    location_id = fields.Many2one('stock.location', string='Ubicación', readonly=True)
    product_state_id = fields.Many2one('product.state', string='Estado físico', readonly=True)
    scanned_at = fields.Datetime(string='Fecha', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
            WITH scans AS (%s)
            SELECT sc.id AS id, sc.id AS scan_id, sc.session_id, sc.operator_id, sc.product_id,
                   COALESCE(sc.lot_name, sc.code) AS lot_name, sc.code, sc.scan_type,
                   sc.location_id, sc.product_state_id, sc.scanned_at
              FROM scans sc
             WHERE sc.scan_type IN ('serial', 'unknown')
               AND NOT EXISTS (
                    SELECT 1 FROM rms_sage_stock_line l
                     WHERE l.is_current AND l.serial_normalized = sc.serial_normalized)
            )""" % (self._table, _VALID_SCANS))
