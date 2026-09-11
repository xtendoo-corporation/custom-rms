# -*- coding: utf-8 -*-

import logging

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SEARCH_LIMIT = 20

# ---------------------------------------------------------------------------
# Todos los métodos usan self.env (permisos del usuario que escanea, nunca
# sudo): quien no tenga acceso de escritura a stock.lot / stock.quant en
# Odoo, tampoco podrá crear líneas desde aquí. La única tabla propia de este
# módulo es el ir.model.access de rms.stock.barcode.scan (solo lectura, ver
# security/ir.model.access.csv); las escrituras reales las valida el propio
# stock.
# ---------------------------------------------------------------------------


class RmsStockBarcodeScan(models.AbstractModel):
    _name = "rms.stock.barcode.scan"
    _description = "RMS Stock Barcode Scan"

    # ------------------------------------------------------------------
    # Datos para el asistente (paso 1: catálogo + ubicación)
    # ------------------------------------------------------------------

    @api.model
    def get_scan_config(self):
        """Ubicación de almacén propuesta por defecto: la ubicación de
        stock del primer almacén de la compañía activa. También devuelve
        los estados de producto (Nuevo, 2ª Mano, Demo...) para que se
        pueda elegir uno por cada número de serie escaneado."""
        company = self.env.company
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        )
        location = warehouse.lot_stock_id if warehouse else self.env["stock.location"]
        if not location:
            location = self.env["stock.location"].search(
                [("usage", "=", "internal"), ("company_id", "=", company.id)], limit=1
            )
        states = self.env["product.state"].search([], order="sequence, id")
        default_state = states.filtered(lambda s: s.code == "new")[:1] or states[:1]
        return {
            "location_id": location.id or False,
            "location_name": location.display_name or "",
            "product_states": [
                {"id": s.id, "name": s.name} for s in states
            ],
            "default_product_state_id": default_state.id or False,
        }

    @api.model
    def search_products(self, query, limit=SEARCH_LIMIT):
        domain = []
        query = (query or "").strip()
        if query:
            domain += [
                "|", "|",
                ("name", "ilike", query),
                ("default_code", "ilike", query),
                ("barcode", "ilike", query),
            ]
        products = self.env["product.product"].search(
            domain, limit=limit, order="name"
        )
        return [
            {
                "id": p.id,
                "name": p.display_name,
                "default_code": p.default_code or "",
                "barcode": p.barcode or "",
                "tracking": p.tracking,
                "uom_name": p.uom_id.name,
            }
            for p in products
        ]

    @api.model
    def search_locations(self, query, limit=SEARCH_LIMIT):
        domain = [("usage", "=", "internal")]
        query = (query or "").strip()
        if query:
            domain.append(("complete_name", "ilike", query))
        locations = self.env["stock.location"].search(domain, limit=limit, order="complete_name")
        return [{"id": loc.id, "name": loc.complete_name} for loc in locations]

    # ------------------------------------------------------------------
    # Escaneo desde una línea de movimiento (recepción, etc.): producto y
    # ubicación ya fijados por el movimiento, sin pasar por el catálogo.
    # ------------------------------------------------------------------

    @api.model
    def get_move_scan_config(self, move_id):
        move = self.env["stock.move"].browse(move_id).exists()
        if not move:
            raise UserError("El movimiento ya no existe.")
        product = move.product_id
        states = self.env["product.state"].search([], order="sequence, id")
        default_state = states.filtered(lambda s: s.code == "new")[:1] or states[:1]
        return {
            "move_id": move.id,
            "product": {
                "id": product.id,
                "name": product.display_name,
                "default_code": product.default_code or "",
                "barcode": product.barcode or "",
                "tracking": product.tracking,
                "uom_name": product.uom_id.name,
            },
            "location_id": move.location_dest_id.id,
            "location_name": move.location_dest_id.display_name,
            "product_states": [{"id": s.id, "name": s.name} for s in states],
            "default_product_state_id": default_state.id or False,
        }

    @api.model
    def confirm_scan_move(self, move_id, serials):
        """Como confirm_scan, pero opera directamente sobre las líneas
        (stock.move.line) de este movimiento en vez de tocar Inventario
        físico. Cada número de serie escaneado rellena primero los
        "huecos" ya reservados por la cantidad pedida (líneas sin
        lote/serie asignado todavía, como las que Odoo crea al abrir
        "Operaciones detalladas" para la demanda); solo si no quedan
        huecos libres se crea una línea nueva (recibir más unidades de
        las pedidas). Rellenar un hueco es lo mismo que teclear el
        número de serie a mano ahí: el propio stock.move.line busca o
        crea el stock.lot correspondiente al guardar.
        """
        move = self.env["stock.move"].browse(move_id).exists()
        if not move:
            raise UserError("El movimiento ya no existe.")
        if move.state in ("done", "cancel"):
            raise UserError("Este movimiento ya no se puede modificar.")
        product = move.product_id
        if product.tracking == "none":
            raise UserError("Este producto no lleva número de lote/serie.")

        seen = set()
        clean_serials = []
        for item in serials or []:
            serial = (item.get("serial") or "").strip() if isinstance(item, dict) else (item or "").strip()
            if serial and serial not in seen:
                seen.add(serial)
                state_id = item.get("product_state_id") if isinstance(item, dict) else False
                clean_serials.append((serial, state_id or False))

        if not clean_serials:
            raise UserError("No hay ningún número de serie escaneado que confirmar.")

        existing_names = {
            (line.lot_name or (line.lot_id.name if line.lot_id else ""))
            for line in move.move_line_ids
            if line.lot_name or line.lot_id
        }
        empty_lines = iter(
            move.move_line_ids.filtered(lambda l: not l.lot_name and not l.lot_id).sorted("id")
        )
        Lot = self.env["stock.lot"] if "stock.lot" in self.env else self.env["stock.production.lot"]
        MoveLine = self.env["stock.move.line"]

        applied = 0
        errors = []
        for serial, state_id in clean_serials:
            try:
                with self.env.cr.savepoint():
                    if serial in existing_names:
                        raise UserError(
                            "El número de serie %s ya está en esta línea." % serial
                        )
                    if product.tracking == "serial":
                        existing_lot = Lot.search(
                            [
                                ("product_id", "=", product.id),
                                ("name", "=", serial),
                                ("company_id", "in", [move.company_id.id, False]),
                            ],
                            limit=1,
                        )
                        if existing_lot:
                            existing_qty = sum(
                                self.env["stock.quant"].search(
                                    [
                                        ("product_id", "=", product.id),
                                        ("lot_id", "=", existing_lot.id),
                                    ]
                                ).mapped("quantity")
                            )
                            if existing_qty >= 1:
                                raise UserError(
                                    "El número de serie %s ya tiene stock (cantidad "
                                    "%g): es un número de serie único y no se puede "
                                    "volver a recibir." % (serial, existing_qty)
                                )

                    vals = {"lot_name": serial}
                    if state_id:
                        vals["product_state_id"] = state_id

                    target_line = next(empty_lines, None)
                    if target_line:
                        target_line.write(vals)
                    else:
                        vals.update({
                            "move_id": move.id,
                            "picking_id": move.picking_id.id,
                            "product_id": product.id,
                            "product_uom_id": move.product_uom.id,
                            "location_id": move.location_id.id,
                            "location_dest_id": move.location_dest_id.id,
                            "company_id": move.company_id.id,
                            "quantity": 1,
                        })
                        MoveLine.create(vals)
                    existing_names.add(serial)
                applied += 1
            except Exception as exc:  # noqa: BLE001 - se reporta al usuario, no se oculta
                _logger.exception(
                    "Error añadiendo el número de serie %s (producto %s) al movimiento %s",
                    serial, product.display_name, move.id,
                )
                errors.append({"serial": serial, "message": str(exc)})

        return {"applied": applied, "errors": errors, "total": len(clean_serials)}

    # ------------------------------------------------------------------
    # Confirmación del escaneo (paso 3, modo genérico sobre Inventario físico)
    # ------------------------------------------------------------------

    @api.model
    def confirm_scan(self, product_id, location_id, serials):
        """Por cada número de serie escaneado: busca o crea el stock.lot
        del producto (con el estado elegido para ese número de serie si
        se ha creado en este momento), y busca o crea la línea de
        stock.quant (producto + lote + ubicación) incrementando en +1 su
        cantidad "Contada" (inventory_quantity). No aplica el ajuste: la
        línea queda pendiente en Inventario físico, igual que si se
        editara a mano.

        `serials` es una lista de dicts {'serial': str, 'product_state_id':
        int|False}: el estado solo se aplica al crear el lote por primera
        vez, nunca se sobreescribe si el número de serie ya existía.

        Cada número de serie se procesa en su propio savepoint: si uno
        falla (p. ej. una restricción de unicidad), no se pierde el resto
        del lote de escaneos.

        Devuelve {'applied': n, 'errors': [{'serial': ..., 'message': ...}]}.
        """
        product = self.env["product.product"].browse(product_id).exists()
        if not product:
            raise UserError("El producto seleccionado ya no existe. Vuelve a buscarlo.")
        location = self.env["stock.location"].browse(location_id).exists()
        if not location:
            raise UserError("La ubicación seleccionada ya no existe. Vuelve a elegirla.")
        if location.usage != "internal":
            raise UserError("La ubicación elegida no es una ubicación interna de almacén.")

        # Serials únicos y no vacíos, preservando el orden de escaneo.
        seen = set()
        clean_serials = []
        for item in serials or []:
            serial = (item.get("serial") or "").strip() if isinstance(item, dict) else (item or "").strip()
            if serial and serial not in seen:
                seen.add(serial)
                state_id = item.get("product_state_id") if isinstance(item, dict) else False
                clean_serials.append((serial, state_id or False))

        if not clean_serials:
            raise UserError("No hay ningún número de serie escaneado que confirmar.")

        Lot = self.env["stock.lot"] if "stock.lot" in self.env else self.env["stock.production.lot"]
        Quant = self.env["stock.quant"]

        applied = 0
        errors = []
        for serial, state_id in clean_serials:
            try:
                with self.env.cr.savepoint():
                    lot = Lot.search(
                        [
                            ("product_id", "=", product.id),
                            ("name", "=", serial),
                            ("company_id", "in", [location.company_id.id, False]),
                        ],
                        limit=1,
                    )
                    if not lot:
                        lot_vals = {
                            "product_id": product.id,
                            "name": serial,
                            "company_id": location.company_id.id,
                        }
                        if state_id:
                            lot_vals["product_state_id"] = state_id
                        lot = Lot.create(lot_vals)

                    if product.tracking == "serial":
                        # Un número de serie es una única unidad física: si ya
                        # tiene alguna cantidad contada (en esta ubicación o en
                        # otra), volver a escanearlo por error no puede sumar
                        # una segunda unidad. Se corta aquí, no se deja para
                        # que falle luego al pulsar "Aplicar todo".
                        existing_qty = sum(
                            Quant.search(
                                [
                                    ("product_id", "=", product.id),
                                    ("lot_id", "=", lot.id),
                                ]
                            ).mapped("inventory_quantity")
                        )
                        if existing_qty >= 1:
                            raise UserError(
                                "El número de serie %s ya está contado (cantidad "
                                "%g) para este producto: es un número de serie "
                                "único y no se puede volver a añadir."
                                % (serial, existing_qty)
                            )

                    quant = Quant.search(
                        [
                            ("product_id", "=", product.id),
                            ("lot_id", "=", lot.id),
                            ("location_id", "=", location.id),
                        ],
                        limit=1,
                    )
                    if quant:
                        quant.inventory_quantity = quant.inventory_quantity + 1
                    else:
                        Quant.create(
                            {
                                "product_id": product.id,
                                "lot_id": lot.id,
                                "location_id": location.id,
                                "inventory_quantity": 1,
                            }
                        )
                applied += 1
            except Exception as exc:  # noqa: BLE001 - se reporta al usuario, no se oculta
                _logger.exception(
                    "Error añadiendo el número de serie %s (producto %s) al inventario físico",
                    serial, product.display_name,
                )
                errors.append({"serial": serial, "message": str(exc)})

        return {"applied": applied, "errors": errors, "total": len(clean_serials)}
