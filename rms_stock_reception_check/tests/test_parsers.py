# -*- coding: utf-8 -*-
from odoo.tests.common import BaseCase, tagged

from ..lib import supplier_parsers as parsers
from . import fixtures


def _by_code(lines):
    result = {}
    for line in lines:
        result.setdefault(line["code"], []).append(line)
    return result


def _serials(lines):
    return [line["serial"] for line in lines]


@tagged("post_install", "-at_install")
class TestSupplierParsers(BaseCase):
    """Los textos de fixtures.py reproducen la maquetación real de cada factura."""

    def test_meyer(self):
        fmt, lines = parsers.parse_document(fixtures.MEYER)
        self.assertEqual(fmt, "meyer")
        items = _by_code(lines)
        self.assertEqual(list(items), ["09.338.001.04", "09.338.001.03", "40.338.200.01"])
        # El último S/N lleva los importes pegados: no se cuelan como series
        self.assertEqual(_serials(items["09.338.001.04"]), ["26470001", "26470002", "26470003"])
        self.assertEqual(items["09.338.001.04"][0]["description"], "1800-LFC,EU,OT,NO RIG,GEN-1")
        self.assertEqual(items["09.338.001.04"][0]["warning"], "")
        # Cantidad 3 con 2 series impresas: avisa, no inventa la tercera
        self.assertEqual(_serials(items["09.338.001.03"]), ["26470011", "26470012"])
        self.assertIn("3 unidades y trae 2", items["09.338.001.03"][0]["warning"])
        # Sin S/N: «3 4 40.338…» es línea 3, cantidad 4
        frame = items["40.338.200.01"]
        self.assertEqual((len(frame), frame[0]["serial"], frame[0]["qty"]), (1, "", 4.0))
        self.assertEqual(frame[0]["description"], "MCF-T2 CASTER FRAME")
        # Ni descuentos, ni importes, ni datos del banco
        self.assertEqual(len(lines), 6)
        for line in lines:
            self.assertNotIn("$", line["description"])
            self.assertNotIn("8518", line["description"])

    def test_meyer_spare_parts_without_serials(self):
        fmt, lines = parsers.parse_document(fixtures.MEYER_PARTS)
        self.assertEqual(fmt, "meyer")
        self.assertEqual(
            [(l["code"], l["qty"], l["serial"]) for l in lines],
            [("40.205.008.02", 1.0, ""), ("24.205.022.01", 1.0, ""), ("40.296.030.01", 10.0, ""),
             ("40.330.197.01", 4.0, "")])
        self.assertEqual(lines[1]["description"], "MPS-488HP DC FILTER PCB ASSEMBLY & BOM")
        self.assertEqual(lines[3]["description"], "MS-2013M HF DRIVER W/HARDWARE KIT")

    def test_meyer_replacements_and_repaired_equipment(self):
        text = """Meyer Sound
1 1 40.125.001.02 ST-418A DRIVER,REPLCMNT PARTS,SERVCE KIT
WARRANTY REPLACEMENT TO SERIAL NUMBER 24251369
2 2 40.328.007.01 2100-LFC LO DR SUBASSY REPL SERVICE KIT
REPLACEMENTS TO SERIAL NUMBERS 26102802, 24110163
9 5 40.287.450.05 ULTRA-X40/42 ELECTRONICS W/O PS SVC KIT
WARRANTY REPLACEMENT TO SERIAL NUMBERS:
23250629, 25445566, 23250594,
22259973, 22259982
S/N: 26441923
S/N: 26441924
S/N: 26441925
S/N: 26441926
S/N: 26441927
15 1 001.230 GALAXY 816/AES/BH SERVICE
WARRANTY SERVICE TO ONE GALAXY 816, SER.# 22256208
17 1 001.237 GALAXY 408 SERVICE
SERVICE TO ONE GALAXY 408, SER.# 19249087
"""
        fmt, lines = parsers.parse_document(text)
        self.assertEqual(fmt, "meyer")
        items = _by_code(lines)
        self.assertEqual(_serials(items["40.125.001.02"]), [""])
        self.assertEqual(items["40.125.001.02"][0]["replaced_serials"], "24251369")
        self.assertEqual(_serials(items["40.328.007.01"]), [""])
        self.assertEqual(items["40.328.007.01"][0]["replaced_serials"], "26102802, 24110163")
        replacement = items["40.287.450.05"]
        self.assertEqual(_serials(replacement), ["26441923", "26441924", "26441925", "26441926", "26441927"])
        self.assertTrue(all(line["is_replacement"] for line in replacement))
        self.assertEqual(replacement[0]["replaced_serials"],
                         "23250629, 25445566, 23250594, 22259973, 22259982")
        self.assertEqual(_serials(items["001.230"]), ["22256208"])
        self.assertEqual(_serials(items["001.237"]), ["19249087"])
        self.assertFalse(items["001.230"][0]["is_replacement"])
        self.assertFalse(items["001.237"][0]["is_replacement"])

    def test_meyer_tolerant_to_spacing(self):
        text = "Meyer Sound\r\n1   2   09.338.001.04    ULTRA-X40\r\n\r\n   S / N :   26476604  \r\nS/N 26476605\r\n"
        _fmt, lines = parsers.parse_document(text)
        self.assertEqual(_serials(lines), ["26476604", "26476605"])
        self.assertEqual(lines[0]["warning"], "")

    def test_digico(self):
        fmt, lines = parsers.parse_document(fixtures.DIGICO)
        self.assertEqual(fmt, "digico")
        items = _by_code(lines)
        self.assertEqual(list(items), ["X-A-168", "X-SDR-AES-O", "X-SD-RACK-OP"])
        self.assertEqual(_serials(items["X-A-168"]), ["168-900001", "168-900002"])
        self.assertEqual(items["X-A-168"][0]["description"], "16 IN 8 OUT STAGE BOX")
        # Tarjetas sin S/N: por cantidad
        self.assertEqual((items["X-SDR-AES-O"][0]["serial"], items["X-SDR-AES-O"][0]["qty"]), ("", 6.0))
        self.assertEqual(items["X-SDR-AES-O"][0]["description"], "SD RACK AES OUT XLR")
        # Una sola serie, seguida del total de la factura
        self.assertEqual(_serials(items["X-SD-RACK-OP"]), ["770001-2610"])
        self.assertEqual(len(lines), 4)
        self.assertFalse(any(line["warning"] for line in lines))

    def test_luminex(self):
        fmt, lines = parsers.parse_document(fixtures.LUMINEX)
        self.assertEqual(fmt, "luminex")
        items = _by_code(lines)
        self.assertEqual(
            _serials(items["LU 01 00079-POE-1G"]),
            ["LUM079900001", "LUM079900002", "LUM079900003", "LUM079900004"])
        self.assertEqual(items["LU 01 00079-POE-1G"][0]["description"], "GigaCore 10t -1G-(8 etherCON + PoE++)")
        self.assertEqual(items["LU 01 00079-POE-1G"][0]["warning"], "")
        self.assertEqual((items["LU 90 00120"][0]["qty"], items["LU 90 00120"][0]["serial"]), (2.0, ""))
        self.assertEqual(len(lines), 5)
        # Si faltara una serie respecto a la cantidad, avisa
        _fmt, lines = parsers.parse_document(fixtures.LUMINEX.replace("LUM079900003,", "", 1))
        self.assertEqual(len(_by_code(lines)["LU 01 00079-POE-1G"]), 3)
        self.assertIn("4 unidades y trae 3", lines[0]["warning"])

    def test_other_odoo_invoice_without_serials(self):
        fmt, lines = parsers.parse_document(fixtures.ODOO_NO_SERIALS)
        self.assertEqual(fmt, "luminex")
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["code"], lines[0]["qty"], lines[0]["serial"]), ("AV-HY64-AVB", 4.0, ""))

    def test_harvey_expands_abbreviated_serials(self):
        fmt, lines = parsers.parse_document(fixtures.HARVEY)
        self.assertEqual(fmt, "harvey")
        items = _by_code(lines)
        # Las líneas de descuento no son artículos
        self.assertEqual(list(items), ["HARVEY Pro 8x8-DA", "HARVEY Pro 8x16"])
        self.assertEqual(_serials(items["HARVEY Pro 8x8-DA"]), ["12-9350-019", "12-9429-087", "12-9429-088"])
        self.assertEqual(
            _serials(items["HARVEY Pro 8x16"]), ["12-9429-069", "12-9429-070", "12-9429-071", "12-9429-072"])
        self.assertFalse(any(line["warning"] for line in lines))

    def test_optocore_single_line_document(self):
        fmt, lines = parsers.parse_document(fixtures.OPTOCORE)
        self.assertEqual(fmt, "optocore")
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["code"], lines[0]["serial"], lines[0]["qty"]), ("M8-OPT", "E99-0001", 1.0))
        self.assertTrue(lines[0]["description"].startswith("4 COAXIAL MADI PORTS"))

    def test_waves_serial_block(self):
        fmt, lines = parsers.parse_document(fixtures.WAVES)
        self.assertEqual(fmt, "waves")
        self.assertEqual(
            [(l["code"], l["description"], l["serial"]) for l in lines],
            [("USW379-700C-334", "Extreme-C SoundGrid Server", "6C000F00A00001")])

    def test_expand_serial_list(self):
        expand = parsers.expand_serial_list
        self.assertEqual(expand("12-2429-087, -088"), ["12-2429-087", "12-2429-088"])
        self.assertEqual(expand("12-2429- 069, -070"), ["12-2429-069", "12-2429-070"])
        self.assertEqual(expand("12-2429-087,-088,-089"), ["12-2429-087", "12-2429-088", "12-2429-089"])
        self.assertEqual(expand("A1234; B5678"), ["A1234", "B5678"])
        self.assertEqual(expand("LUM079003272, LUM079003270,"), ["LUM079003272", "LUM079003270"])
        self.assertEqual(expand("ver hoja adjunta"), [])
        # Importes pegados o a continuación: nunca son series
        self.assertEqual(expand("26476618$4,600.0000 $55,200.00"), ["26476618"])
        self.assertEqual(expand("12-2350-019, S/N: 12-2429-087, -088 3.495,00 € 10.485,00 €"),
                         ["12-2350-019", "12-2429-087", "12-2429-088"])
        self.assertEqual(expand("600.0000"), [])
        self.assertEqual(expand("870.0000, 440.00"), [])

    def test_generic_only_reads_labelled_serials(self):
        fmt, lines = parsers.parse_document(fixtures.GENERIC)
        self.assertEqual(fmt, "generic")
        self.assertEqual(_serials(lines), ["XR200-0001", "XR200-0002", "PA9-55A1"])
        self.assertTrue(lines[0]["description"].startswith("Mezclador digital XR-200"))
        self.assertEqual(lines[2]["description"], "Amplificador PA-900")
        self.assertEqual(lines[0]["code"], "")

    def test_generic_never_invents_lines(self):
        for text in fixtures.NO_SERIALS:
            fmt, lines = parsers.parse_document(text)
            self.assertEqual(fmt, "generic")
            self.assertEqual(lines, [], text[:40])
        self.assertEqual(parsers.parse_document("Hola\nmundo")[1], [])
        self.assertEqual(parsers.parse_document("")[1], [])
        # Un rótulo sin series detrás (cabecera de columna) tampoco da líneas
        self.assertEqual(parsers.parse_document("Item\nSerial Numbers\nTotal 100,00 €\nS/N: 200,00")[1], [])

    def test_forced_format(self):
        # Formato elegido a mano aunque el documento no nombre la marca
        fmt, lines = parsers.parse_document(fixtures.DIGICO.replace("DiGiCo", "ACME"), "digico")
        self.assertEqual(fmt, "digico")
        self.assertEqual(len(lines), 4)
        # Lector equivocado que no saca nada: cae al genérico y no pierde las series rotuladas
        fmt, lines = parsers.parse_document(fixtures.GENERIC, "digico")
        self.assertEqual(fmt, "generic")
        self.assertEqual(_serials(lines), ["XR200-0001", "XR200-0002", "PA9-55A1"])

    def test_pasted(self):
        lines = parsers.parse_pasted("26476604\n\n0933800104\t26476605\nX-A-168;168-102760\n4033804001\t\t3\n")
        self.assertEqual(
            [(l["code"], l["serial"], l["qty"]) for l in lines],
            [("", "26476604", 1.0), ("0933800104", "26476605", 1.0), ("X-A-168", "168-102760", 1.0),
             ("4033804001", "", 3.0)])
