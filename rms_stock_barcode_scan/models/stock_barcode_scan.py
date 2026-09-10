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
        stock del primer almacén de la compañía activa."""
        company = self.env.company
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        )
        location = warehouse.lot_stock_id if warehouse else self.env["stock.location"]
        if not location:
            location = self.env["stock.location"].search(
                [("usage", "=", "internal"), ("company_id", "=", company.id)], limit=1
            )
        return {
            "location_id": location.id or False,
            "location_name": location.display_name or "",
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
    # Confirmación del escaneo (paso 3)
    # ------------------------------------------------------------------

    @api.model
    def confirm_scan(self, product_id, location_id, serials):
        """Por cada número de serie escaneado: busca o crea el stock.lot
        del producto, y busca o crea la línea de stock.quant
        (producto + lote + ubicación) incrementando en +1 su cantidad
        "Contada" (inventory_quantity). No aplica el ajuste: la línea
        queda pendiente en Inventario físico, igual que si se editara a
        mano.

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
        for serial in serials or []:
            serial = (serial or "").strip()
            if serial and serial not in seen:
                seen.add(serial)
                clean_serials.append(serial)

        if not clean_serials:
            raise UserError("No hay ningún número de serie escaneado que confirmar.")

        Lot = self.env["stock.lot"] if "stock.lot" in self.env else self.env["stock.production.lot"]
        Quant = self.env["stock.quant"]

        applied = 0
        errors = []
        for serial in clean_serials:
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
                        lot = Lot.create(
                            {
                                "product_id": product.id,
                                "name": serial,
                                "company_id": location.company_id.id,
                            }
                        )

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
