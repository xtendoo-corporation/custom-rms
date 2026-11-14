#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sage en vivo: lee Sage (SOLO LECTURA) y lo envía a Odoo por la API JSON-2.

Se ejecuta en el NAS dentro de la imagen bi-dash-bi (Python 3 + pyodbc), con
la misma conexión de solo lectura que la copia diaria de los dashboards
(SAGE_PROD_SERVER / SAGE_PROD_USER / SAGE_PROD_PWD, usuario UsuarioLectura).
No escribe nada en Sage ni en el NAS (salvo su propio log, que lo hace run.sh).

Qué envía, por empresa (01 RMS, 02 Espacio, 03 RJB):
- existencias: stock por nº de serie (LOTES0xx.stocklotes) + el resto sin
  serie (año.stocks2), con el nombre del artículo  -> push_stock(stock)
- depósitos de venta abiertos por nº de serie, con el cliente -> push_stock(deposit)
- movimientos nuevos por nº de serie (ventas, depósitos y vueltas, traspasos,
  compras, regularizaciones) desde la última vez -> push_moves

Uso:
  python3 sage_live_sync.py --dry-run          # no envía: resumen + JSON a stdout
  python3 sage_live_sync.py                    # envía a ODOO_URL / ODOO_DB
Variables: SAGE_PROD_SERVER, SAGE_PROD_USER, SAGE_PROD_PWD (del .env de la copia
diaria, montado de solo lectura); ODOO_URL, ODOO_DB, ODOO_API_KEY (su .env);
opcionales SAGE_LOTES_DB (LOTES0FT), SAGE_YEAR_DB (<año>FT), SAGE_COMPANIES
(01,02,03), MAX_SECONDS (480), FIRST_RUN_DAYS (45), LOCK_FILE.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

STOCK_CHUNK = 20000      # filas por llamada de push_stock (Odoo admite 60.000)
MOVES_CHUNK = 2000       # movimientos por llamada de push_moves
MOVES_LIMIT = 20000      # máximo de movimientos por tabla y ejecución
HTTP_TIMEOUT = 300
HTTP_RETRIES = 2

# tabla de lotes -> (tipo de movimiento, columna almacén origen, columna destino, cabecera para el cliente)
MOVE_TABLES = {
    'ltalbve': ('sale', 'ALMACEN', None, ('c_albven', 'CLIENTE', 'clientes')),
    'ltdepve': ('deposit', 'ALMACEN', None, ('c_albdep', 'CLIENTE', 'clientes')),
    'ltalbtr': ('transfer', 'ALMORIG', 'ALMDEST', None),
    'ltalbco': ('purchase', None, 'ALMACEN', None),
    'ltregul': ('adjustment', 'ALMACEN', None, None),
}


def log(msg):
    print('%s %s' % (dt.datetime.now().strftime('%H:%M:%S'), msg), flush=True)


class Deadline:
    def __init__(self, seconds):
        self.end = time.time() + seconds

    def check(self, what):
        if time.time() > self.end:
            raise TimeoutError('Tiempo máximo superado antes de: %s' % what)


# ----------------------------------------------------------------- Sage (lectura)
class Sage:
    def __init__(self):
        import pyodbc  # disponible en la imagen bi-dash-bi
        self.conn = pyodbc.connect(
            'DRIVER={ODBC Driver 18 for SQL Server};SERVER=%s;UID=%s;PWD=%s;TrustServerCertificate=yes;'
            'ApplicationIntent=ReadOnly' % (os.environ['SAGE_PROD_SERVER'], os.environ['SAGE_PROD_USER'],
                                            os.environ['SAGE_PROD_PWD']),
            timeout=30, readonly=True)
        self.conn.timeout = 120  # segundos por consulta
        self._cols = {}

    def rows(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        names = [d[0] for d in cur.description]
        out = [dict(zip(names, r)) for r in cur.fetchall()]
        cur.close()
        return out

    def columns(self, db, table):
        key = (db, table)
        if key not in self._cols:
            got = self.rows("SELECT COLUMN_NAME FROM [%s].INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?" % db, (table,))
            self._cols[key] = {r['COLUMN_NAME'].upper() for r in got}
        return self._cols[key]


def txt(value):
    return str(value).strip() if value is not None else ''


def num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def first(cols, *names):
    return next((n for n in names if n in cols), None)


def article_names(sage, year_db):
    cols = sage.columns(year_db, 'articulo')
    if not {'CODIGO', 'NOMBRE'} <= cols:
        return {}
    return {txt(r['CODIGO']): txt(r['NOMBRE']) for r in sage.rows("SELECT CODIGO, NOMBRE FROM [%s].dbo.articulo" % year_db)}


def is_no_serial(lot):
    """Sage usa "SN" / "S/N" como lote de las unidades sin nº de serie."""
    return txt(lot).upper().replace('/', '').replace(' ', '') in ('', 'SN', 'SINSERIE', 'NODESERIE')


def stock_rows(sage, lotes_db, year_db, company, names):
    """Existencias de una empresa como las da 'Valoración de stocks':
    nº de serie (stocklotes) + resto sin serie (stocks2 menos lo que tiene serie)."""
    serial = sage.rows(
        "SELECT RTRIM(ALMACEN) AS ALMACEN, RTRIM(ARTICULO) AS ARTICULO, RTRIM(LOTE) AS LOTE, SUM(UNIDADES) AS U "
        "FROM [%s].dbo.stocklotes WHERE RTRIM(EMPRESA) = ? GROUP BY RTRIM(ALMACEN), RTRIM(ARTICULO), RTRIM(LOTE) "
        "HAVING SUM(UNIDADES) <> 0" % lotes_db, (company,))
    rows, serial_units = [], {}
    for r in serial:
        if is_no_serial(r['LOTE']):
            continue  # "SN": unidades sin nº de serie, van con el stock del artículo
        key = (txt(r['ALMACEN']), txt(r['ARTICULO']))
        serial_units[key] = serial_units.get(key, 0) + num(r['U'])
        rows.append({'warehouse_code': key[0], 'article_code': key[1], 'article_name': names.get(key[1], ''),
                     'serial': txt(r['LOTE']), 'quantity': num(r['U'])})
    cols = sage.columns(year_db, 'stocks2')
    qty_col = first(cols, 'FINAL', 'STOCK', 'EXISTENCIA', 'EXISTENCIAS', 'UNIDADES')
    if qty_col and {'ARTICULO', 'ALMACEN'} <= cols:
        where = "WHERE RTRIM(EMPRESA) = ?" if 'EMPRESA' in cols else ''
        params = (company,) if 'EMPRESA' in cols else ()
        totals = sage.rows(
            "SELECT RTRIM(ALMACEN) AS ALMACEN, RTRIM(ARTICULO) AS ARTICULO, SUM(%s) AS U FROM [%s].dbo.stocks2 %s "
            "GROUP BY RTRIM(ALMACEN), RTRIM(ARTICULO) HAVING SUM(%s) <> 0" % (qty_col, year_db, where, qty_col), params)
        for r in totals:
            key = (txt(r['ALMACEN']), txt(r['ARTICULO']))
            total = num(r['U'])
            rest = total - serial_units.get(key, 0)
            # Igual que el lector del archivo: lo que no tiene nº de serie.
            if key in serial_units:
                rest = max(0.0, rest) if total >= 0 else rest
            if rest:
                rows.append({'warehouse_code': key[0], 'article_code': key[1], 'article_name': names.get(key[1], ''),
                             'serial': '', 'quantity': rest})
    else:
        log('AVISO: stocks2 sin columnas reconocibles (%s): solo se envía stock con nº de serie' % sorted(cols)[:12])
    return rows


def partner_names(sage, year_db, header, partner_col, partner_table, company, docs):
    """{(letra, numero): nombre del cliente} solo de los documentos pedidos."""
    if not docs:
        return {}
    hcols = sage.columns(year_db, header)
    pcols = sage.columns(year_db, partner_table)
    if not ({'NUMERO', partner_col} <= hcols and {'CODIGO', 'NOMBRE'} <= pcols):
        return {}
    letra = 'LTRIM(RTRIM(h.LETRA))' if 'LETRA' in hcols else "''"
    emp = "AND LTRIM(RTRIM(h.EMPRESA)) = ?" if 'EMPRESA' in hcols else ''
    out = {}
    # El nº de documento lleva espacios delante ("       884") y un depósito
    # de otro año tiene su cabecera en la base de ese año (2025FT...).
    pending = {(txt(l), txt(n)) for l, n in docs}
    year = int(year_db[:4]) if year_db[:4].isdigit() else 0
    for db in [year_db] + (['%d%s' % (y, year_db[4:]) for y in range(year - 1, year - 6, -1)] if year else []):
        if not pending:
            break
        if db != year_db and not sage.columns(db, header):
            continue
        numbers = sorted({n for _l, n in pending})
        for start in range(0, len(numbers), 500):
            chunk = numbers[start:start + 500]
            marks = ','.join('?' * len(chunk))
            params = ((company,) if emp else ()) + tuple(chunk)
            for r in sage.rows(
                    "SELECT %s AS LETRA, LTRIM(RTRIM(h.NUMERO)) AS NUMERO, p.NOMBRE AS NOMBRE FROM [%s].dbo.[%s] h "
                    "LEFT JOIN [%s].dbo.[%s] p ON LTRIM(RTRIM(p.CODIGO)) = LTRIM(RTRIM(h.%s)) "
                    "WHERE 1=1 %s AND LTRIM(RTRIM(h.NUMERO)) IN (%s)"
                    % (letra, db, header, db, partner_table, partner_col, emp, marks), params):
                key = (txt(r['LETRA']), txt(r['NUMERO']))
                if key in pending:
                    out[key] = txt(r['NOMBRE'])
        pending -= set(out)
    return out


def deposit_rows(sage, lotes_db, year_db, company, names):
    """Depósitos de venta ABIERTOS por nº de serie: suma de unidades de
    ltdepve por almacén+artículo+serie sin las líneas ya traspasadas a albarán
    (TRASPAS); > 0 = sigue en casa del cliente. Cliente = el del último
    depósito de esa serie."""
    cols = sage.columns(lotes_db, 'ltdepve')
    open_filter = ("AND (TRASPAS IS NULL OR LTRIM(RTRIM(CAST(TRASPAS AS varchar(50)))) IN ('', '0'))"
                   if 'TRASPAS' in cols else '')
    letra = 'RTRIM(LETRA)' if 'LETRA' in cols else "''"
    lines = sage.rows(
        "SELECT RTRIM(ALMACEN) AS ALMACEN, RTRIM(ARTICULO) AS ARTICULO, RTRIM(LOTE) AS LOTE, UNIDADES, FECHA, "
        "%s AS LETRA, RTRIM(NUMERO) AS NUMERO FROM [%s].dbo.ltdepve WHERE RTRIM(EMPRESA) = ? %s"
        % (letra, lotes_db, open_filter), (company,))
    acc = {}
    for r in lines:
        key = (txt(r['ALMACEN']), txt(r['ARTICULO']), txt(r['LOTE']))
        item = acc.setdefault(key, {'u': 0.0, 'last': None})
        item['u'] += num(r['UNIDADES'])
        if num(r['UNIDADES']) > 0 and (item['last'] is None or (r['FECHA'] or dt.datetime.min) >= item['last'][0]):
            item['last'] = (r['FECHA'] or dt.datetime.min, txt(r['LETRA']), txt(r['NUMERO']))
    open_items = {k: v for k, v in acc.items() if v['u'] > 0 and k[2] and not is_no_serial(k[2])}
    docs = {(v['last'][1], v['last'][2]) for v in open_items.values() if v['last']}
    partners = partner_names(sage, year_db, 'c_albdep', 'CLIENTE', 'clientes', company, docs)
    rows = []
    for (wh, art, lot), v in open_items.items():
        doc = (v['last'][1], v['last'][2]) if v['last'] else ('', '')
        rows.append({'warehouse_code': wh, 'article_code': art, 'article_name': names.get(art, ''),
                     'serial': lot, 'quantity': v['u'], 'partner_name': partners.get(doc, '')})
    return rows


def move_rows(sage, lotes_db, year_db, table, since, companies):
    move_type, from_col, to_col, header = MOVE_TABLES[table]
    cols = sage.columns(lotes_db, table)
    if not {'EMPRESA', 'ARTICULO', 'LOTE'} <= cols:
        log('AVISO: %s sin columnas esperadas, se omite' % table)
        return []
    pick = ['RTRIM(EMPRESA) AS EMPRESA', 'RTRIM(ARTICULO) AS ARTICULO', 'RTRIM(LOTE) AS LOTE']
    for col in ('LETRA', 'NUMERO', 'LINIA', 'FECHA', 'UNIDADES', 'MODIFIED', 'GUID_ID', from_col, to_col):
        if col and col in cols:
            pick.append(col)
    where = "RTRIM(EMPRESA) IN (%s) AND LOTE IS NOT NULL AND RTRIM(LOTE) <> '' AND UPPER(REPLACE(REPLACE(LOTE, '/', ''), ' ', '')) <> 'SN'" % ','.join('?' * len(companies))
    params = list(companies)
    if since and 'MODIFIED' in cols:
        where += " AND MODIFIED > ?"
        # Como fecha real, no como texto: el SQL Server de Sage está en español
        # (día/mes) y '2026-11-13 14:07:06' en texto da "fuera de intervalo".
        params.append(dt.datetime.fromisoformat(str(since)[:19]) if isinstance(since, str) else since)
    elif 'FECHA' in cols:
        where += " AND FECHA >= ?"
        params.append(dt.datetime.now() - dt.timedelta(days=int(os.environ.get('FIRST_RUN_DAYS', '45'))))
    order = 'MODIFIED' if 'MODIFIED' in cols else 'FECHA'
    rows = sage.rows("SELECT TOP %d %s FROM [%s].dbo.[%s] WHERE %s ORDER BY %s"
                     % (MOVES_LIMIT, ', '.join(pick), lotes_db, table, where, order), tuple(params))
    partners = {}
    if header:
        for company in companies:
            docs = {(txt(r.get('LETRA')), txt(r.get('NUMERO'))) for r in rows
                    if txt(r['EMPRESA']) == company and r.get('NUMERO') is not None}
            partners.update({(company,) + k: v for k, v in partner_names(
                sage, year_db, header[0], header[1], header[2], company, docs).items()})
    out = []
    for r in rows:
        units = num(r.get('UNIDADES'))
        kind = move_type
        if table == 'ltdepve' and units < 0:
            kind = 'deposit_return'
        doc = '%s%s' % (txt(r.get('LETRA')), txt(r.get('NUMERO')))
        key = txt(r.get('GUID_ID')) or '|'.join([table, txt(r['EMPRESA']), txt(r.get('LETRA')), txt(r.get('NUMERO')),
                                                 txt(r.get('LINIA')), txt(r['LOTE'])])
        when = r.get('FECHA')
        modified = r.get('MODIFIED')
        out.append({
            'sage_key': key, 'sage_table': table,
            'sage_modified': modified.strftime('%Y-%m-%d %H:%M:%S') if modified else False,
            'sage_company_code': txt(r['EMPRESA']), 'move_type': kind,
            'move_date': when.strftime('%Y-%m-%d') if when else False,
            'article_code': txt(r['ARTICULO']), 'serial': txt(r['LOTE']), 'quantity': units,
            'warehouse_from': txt(r.get(from_col)) if from_col else '',
            'warehouse_to': txt(r.get(to_col)) if to_col else '',
            'document': doc,
            'partner_name': partners.get((txt(r['EMPRESA']), txt(r.get('LETRA')), txt(r.get('NUMERO'))), ''),
        })
    return out


# --------------------------------------------------------------------- Odoo (API)
class Odoo:
    def __init__(self):
        self.base = os.environ['ODOO_URL'].rstrip('/') + '/json/2/'
        self.headers = {'Content-Type': 'application/json', 'Authorization': 'bearer ' + os.environ['ODOO_API_KEY'],
                        'X-Odoo-Database': os.environ['ODOO_DB'], 'User-Agent': 'rms-sage-live-sync'}

    def call(self, model, method, **body):
        data = json.dumps(body, default=str).encode()
        last = None
        for attempt in range(HTTP_RETRIES + 1):
            req = urllib.request.Request(self.base + model + '/' + method, data, self.headers)
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    return json.loads(resp.read() or b'null')
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:400]
                if exc.code < 500:  # error de datos/permiso: no reintentar
                    raise RuntimeError('Odoo %s %s: %s' % (exc.code, method, detail)) from exc
                last = 'HTTP %s %s' % (exc.code, detail)
            except (urllib.error.URLError, TimeoutError) as exc:
                last = str(exc)
            time.sleep(10 * (attempt + 1))
        raise RuntimeError('Odoo no responde (%s): %s' % (method, last))


# ------------------------------------------------------------------------ main
def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--dry-run', action='store_true', help='No envía nada; resumen y JSON a stdout.')
    parser.add_argument('--only', choices=['stock', 'deposit', 'moves'], help='Solo una parte.')
    args = parser.parse_args()

    lock = None
    if os.environ.get('LOCK_FILE'):
        import fcntl
        lock = open(os.environ['LOCK_FILE'], 'w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('Otra ejecución en marcha: salgo sin hacer nada.')
            return 0

    deadline = Deadline(int(os.environ.get('MAX_SECONDS', '480')))
    lotes_db = os.environ.get('SAGE_LOTES_DB', 'LOTES0FT')
    year_db = os.environ.get('SAGE_YEAR_DB', '%dFT' % dt.date.today().year)
    companies = [c.strip() for c in os.environ.get('SAGE_COMPANIES', '01,02,03').split(',') if c.strip()]
    today = dt.date.today().strftime('%Y-%m-%d')
    started = time.time()
    sage = Sage()
    odoo = None if args.dry_run else Odoo()
    dump = {'stock': {}, 'deposit': {}, 'moves': []}
    names = article_names(sage, year_db)
    log('Artículos leídos: %d (%s)' % (len(names), year_db))

    for company in companies:
        if args.only in (None, 'stock'):
            deadline.check('existencias %s' % company)
            rows = stock_rows(sage, lotes_db, year_db, company, names)
            log('Existencias %s: %d filas (%d con nº de serie)' % (company, len(rows), sum(1 for r in rows if r['serial'])))
            if args.dry_run:
                dump['stock'][company] = rows
            elif len(rows) <= STOCK_CHUNK:
                res = odoo.call('rms.sage.sync.run', 'push_stock', sage_company_code=company, stock_kind='stock',
                                rows=rows, export_date=today)
                log('  -> Odoo: %s' % res)
            else:
                log('  ERROR: demasiadas filas para una sola versión (%d); no se envía' % len(rows))
        # Depósitos en vivo desactivados por defecto (SEND_DEPOSITS=1 para activarlos)
        # hasta validar la regla de "depósito abierto" con Administración.
        send_deposits = os.environ.get('SEND_DEPOSITS', '0') == '1' or args.only == 'deposit'
        if args.only in (None, 'deposit') and (send_deposits or args.dry_run):
            deadline.check('depósitos %s' % company)
            rows = deposit_rows(sage, lotes_db, year_db, company, names)
            log('Depósitos abiertos %s: %d nº de serie' % (company, len(rows)))
            if args.dry_run:
                dump['deposit'][company] = rows
            else:
                res = odoo.call('rms.sage.sync.run', 'push_stock', sage_company_code=company, stock_kind='deposit',
                                rows=rows, export_date=today)
                log('  -> Odoo: %s' % res)

    if args.only in (None, 'moves'):
        marks = {} if args.dry_run else (odoo.call('rms.sage.sync.run', 'last_watermark') or {})
        for table in MOVE_TABLES:
            deadline.check('movimientos %s' % table)
            rows = move_rows(sage, lotes_db, year_db, table, marks.get(table), companies)
            log('Movimientos %s desde %s: %d' % (table, marks.get(table) or 'los últimos días', len(rows)))
            if args.dry_run:
                dump['moves'].extend(rows)
                continue
            for start in range(0, len(rows), MOVES_CHUNK):
                deadline.check('envío de movimientos %s' % table)
                res = odoo.call('rms.sage.sync.run', 'push_moves', rows=rows[start:start + MOVES_CHUNK])
                log('  -> Odoo: %s' % res)

    log('Fin en %.0f s' % (time.time() - started))
    if args.dry_run:
        print('JSON ' + json.dumps(dump, default=str))
    if lock:
        lock.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # el log debe decir qué ha pasado, sin contraseñas
        log('ERROR: %s: %s' % (type(exc).__name__, str(exc)[:500]))
        sys.exit(1)
