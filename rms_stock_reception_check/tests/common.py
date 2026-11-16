# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class ReceptionCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.supplier = cls.env["res.partner"].create({"name": "Meyer Sound Test", "is_company": True})
        Product = cls.env["product.product"]

        def product(name, ref, tracking="serial", barcode=False):
            return Product.create({
                "name": name, "default_code": ref, "is_storable": True, "tracking": tracking, "barcode": barcode,
            })

        cls.ultra = product("ULTRA-X40", "0933800104", barcode="0733009338015")
        cls.galaxy = product("GALAXY 816", "0907600102")
        cls.rack = product("A168D Stage Rack", "X-A-168")
        cls.bracket = product("MUB-X40 U-Bracket", "4033804001", tracking="none", barcode="0733004033808")
        cls.state_new = cls.env.ref("rms_product_state.state_new")
        cls.state_demo = cls.env.ref("rms_product_state.state_demo")
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.operator = Users.create({
            "name": "Operario Uno", "login": "c1_operario1",
            "group_ids": [(6, 0, [cls.env.ref("stock.group_stock_user").id])],
        })
        cls.operator2 = Users.create({
            "name": "Operario Dos", "login": "c1_operario2",
            "group_ids": [(6, 0, [cls.env.ref("stock.group_stock_user").id])],
        })
        cls.manager = Users.create({
            "name": "Responsable", "login": "c1_responsable",
            "group_ids": [(6, 0, [cls.env.ref("stock.group_stock_manager").id])],
        })

    @classmethod
    def _reception(cls, lines=(), **vals):
        """lines: [(producto, nº de serie o False, cantidad)]"""
        reception = cls.env["rms.reception"].create(dict({
            "partner_id": cls.supplier.id, "warehouse_id": cls.warehouse.id, "supplier_ref": "INV-1",
        }, **vals))
        for index, (product, serial, qty) in enumerate(lines):
            cls.env["rms.reception.line"].create({
                "reception_id": reception.id, "sequence": index, "product_id": product.id if product else False,
                "serial": serial, "qty_expected": qty,
            })
        return reception

    def _scan(self, reception, code, user=None, product=None, **kwargs):
        response = reception.with_user(user or self.operator).checklist_scan(
            code, product_id=product.id if product else False, **kwargs)
        return response["result"]
