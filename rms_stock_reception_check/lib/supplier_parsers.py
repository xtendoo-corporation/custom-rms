# -*- coding: utf-8 -*-
"""Lectores del documento del proveedor (factura / packing list).

Funciones puras: texto -> lista de líneas esperadas. No dependen de Odoo,
así que se prueban con texto de ejemplo. Cada línea devuelta es un dict:

    {"code": referencia del proveedor, "description": texto del artículo,
     "serial": nº de serie o "", "qty": cantidad, "warning": aviso o ""}

Un artículo con N números de serie da N líneas (qty 1). Un artículo sin
números de serie da una sola línea por cantidad.

Los lectores por marca están ajustados a la maquetación REAL del texto que
saca odoo.tools.pdf.PdfReader de las facturas de cada proveedor (los tests
usan copias anonimizadas con los mismos saltos de línea). El genérico es
conservador a propósito: solo devuelve números de serie que vienen detrás
de un rótulo «S/N», «Serial…», «Nº de serie»; ante la duda, nada.
"""
import re

FORMATS = [
    ("meyer", "Meyer Sound"),
    ("digico", "DiGiCo"),
    ("luminex", "Luminex / factura hecha con Odoo"),
    ("harvey", "DSPecialists / Harvey"),
    ("optocore", "Optocore"),
    ("waves", "Waves"),
    ("generic", "Genérico (busca «S/N», «Serial», «Nº serie»)"),
]

# "S/N:", "SN:", "Serial Number:(s):", "Serial Numbers:", "Serial No.",
# "Nº serie", "Nº de serie", "Números de serie", "Seriennummer"...
_MARKER_RE = re.compile(
    r"(?i)(?:"
    r"\bS\s*/\s*N\b\.?"
    r"|\bSN(?=\s*[:#])"
    r"|\bSerial\s*(?:Numbers?|Nos?\b\.?|#)"
    r"|\bSerials?(?=\s*:)"
    r"|\bN[ºo°]\.?\s*(?:de\s+)?serie"
    r"|\bN[úu]m(?:ero)?s?\.?\s*(?:de\s+)?serie"
    r"|\bSeriennummern?"
    r")\s*:?\s*(?:\(s\))?\s*[:#]?\s*"
)
_SERIAL_TOKEN_RE = re.compile(r"^-?[A-Z0-9][A-Z0-9\-/_.]*$", re.IGNORECASE)
# 600.0000 · 1,415.48 · 3.495,00 · 4.00 : importes y cantidades, nunca series
_AMOUNT_RE = re.compile(r"^-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)[.,]\d{2,4}$")
_DATE_RE = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")
_CURRENCY_RE = re.compile(r"[$€£]|\b(?:EUR|USD|GBP)\b")
_QTY_UNIT_RE = re.compile(
    r"(?<![\w.,])(\d{1,5})(?:[.,]0+)?\s*(?:EA|PCS?|PZA?S?|UN(?:IT)?S?|UDS?|UNIDADES|STK|ST)\b\.?",
    re.IGNORECASE,
)
_MEYER_PART_RE = re.compile(r"(?<![\d.])(\d{2}\.\d{3}\.\d{3}\.\d{2})(?![\d.])")
# [Schedule B] Línea Cantidad Part-number Descripción [$unitario $total]
_MEYER_LINE_RE = re.compile(
    r"^(?:\d{6,10}\s+)?(\d{1,3})\s+(\d{1,5})\s+(\d{2}\.\d{3}\.\d{3}\.\d{2}|\d{3}\.\d{3})\s+(.*)$")
_BRACKET_REF_RE = re.compile(r"\[([^\]\[]{2,60})\]")
_DIGICO_QTY_RE = re.compile(r"^(\d{1,5})(?:\.\d+)?\s*EA$", re.IGNORECASE)
_HARVEY_LINE_RE = re.compile(r"^(\d{1,3})\s+(\d{1,4})\s*([A-Za-z].*)$")
_DISCOUNT_RE = re.compile(r"(?i)\b(?:discount|rabatt|descuento|deduction|remise)\b")


def _clean_lines(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n").replace("\xa0", " ")
    return [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]


def _looks_like_serial(token):
    token = token.strip()
    if len(token) < 3 or not any(ch.isdigit() for ch in token):
        return False
    if _AMOUNT_RE.fullmatch(token) or _DATE_RE.fullmatch(token) or token.endswith("%"):
        return False
    return bool(_SERIAL_TOKEN_RE.fullmatch(token))


def _strip_prices(chunk):
    """Quita lo que no es lista de series: otros rótulos «S/N:» repetidos en
    la misma línea y los importes pegados al final («…618$4,600.0000 $55,200.00»,
    «…-088 3.495,00 € 10.485,00 €»)."""
    chunk = _MARKER_RE.sub(" ", chunk or "")
    chunk = _CURRENCY_RE.split(chunk)[0]
    previous = None
    while previous != chunk:
        previous = chunk
        chunk = re.sub(r"[\s,;]+-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)[.,]\d{2,4}\s*$", "", chunk)
    return chunk.strip()


def expand_serial_list(chunk):
    """«12-2429-087, -088» -> ['12-2429-087', '12-2429-088'].

    Admite comas o punto y coma, espacios sueltos tras un guion
    («12-2429- 069») y, si no hay comas, varios números separados por
    espacios. Una pieza que empieza por guion hereda el prefijo de la
    anterior (todo hasta su último guion). Los importes no son series."""
    chunk = _strip_prices(chunk)
    chunk = re.sub(r"-\s+(?=[A-Za-z0-9])", "-", chunk)
    parts = [p.strip() for p in re.split(r"[,;]", chunk)]
    if len([p for p in parts if p]) == 1 and " " in chunk.strip():
        spaced = chunk.strip().split()
        if all(_looks_like_serial(tok) for tok in spaced):
            parts = spaced
    serials = []
    prefix = ""
    for part in parts:
        part = part.strip().strip(".").strip()
        if not part:
            continue
        part = re.sub(r"^(?:y|and|und|&)\s+", "", part, flags=re.IGNORECASE)
        part = part.split()[0] if part.split() else ""
        if not part:
            continue
        if part.startswith("-") and prefix:
            serial = prefix + part[1:]
        else:
            serial = part.lstrip("-")
            prefix = serial[: serial.rindex("-") + 1] if "-" in serial else ""
        if _looks_like_serial(serial) and serial not in serials:
            serials.append(serial)
    return serials


def _is_serial_list_line(line, need_comma):
    """¿La línea es SOLO una lista de números de serie?"""
    if not line or _MARKER_RE.search(line):
        return False
    collapsed = re.sub(r"-\s+(?=[A-Za-z0-9])", "-", _strip_prices(line))
    tokens = [t.strip() for t in re.split(r"[,;]", collapsed) if t.strip()]
    if not tokens or not all(_looks_like_serial(t.lstrip("-")) for t in tokens):
        return False
    return not need_comma or len(tokens) > 1 or line.rstrip().endswith((",", ";"))


def _collect_serials(lines, index, chunk):
    """Lista de series que empieza en `chunk` (lo que sigue al rótulo) y puede
    continuar en las líneas siguientes. Devuelve (series, índice siguiente)."""
    chunk = chunk or ""
    if not _strip_prices(chunk):
        # Rótulo solo en su línea (DiGiCo, Luminex): la lista empieza debajo
        probe = index
        while probe < len(lines) and not lines[probe]:
            probe += 1
        if probe < len(lines) and _is_serial_list_line(lines[probe], need_comma=False):
            chunk = lines[probe]
            index = probe + 1
        else:
            return [], index
    while True:
        ended_with_comma = chunk.rstrip().endswith((",", ";"))
        probe = index
        while ended_with_comma and probe < len(lines) and not lines[probe]:
            probe += 1
        if probe < len(lines) and _is_serial_list_line(lines[probe], need_comma=not ended_with_comma):
            chunk = chunk.rstrip().rstrip(",;") + ", " + _strip_prices(lines[probe]) + (
                "," if lines[probe].rstrip().endswith((",", ";")) else "")
            index = probe + 1
            continue
        break
    return expand_serial_list(chunk), index


def _clean_description(text):
    text = _CURRENCY_RE.split(text or "")[0]
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\s+-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)[.,]\d{2,4}\s*$", "", text)
    return text.strip(" -·|(\t")[:160]


def _finish(items):
    """items [{code, description, qty, serials}] -> líneas de salida."""
    result = []
    for item in items:
        code = (item.get("code") or "").strip()
        description = (item.get("description") or "").strip()
        qty = item.get("qty") or 0
        serials = item.get("serials") or []
        metadata = {}
        if "is_replacement" in item:
            metadata = {"is_replacement": item["is_replacement"],
                        "replaced_serials": ", ".join(item.get("replaced_serials", []))}
        if serials:
            warning = ""
            if qty and int(qty) != len(serials):
                warning = "El documento indica %d unidades y trae %d nº de serie." % (int(qty), len(serials))
            for serial in serials:
                result.append({"code": code, "description": description, "serial": serial, "qty": 1.0,
                               "warning": warning, **metadata})
        elif code or description:
            result.append({"code": code, "description": description, "serial": "", "qty": float(qty or 1.0),
                           "warning": "", **metadata})
    return result


def _add_serials(item, serials):
    for serial in serials:
        if serial not in item["serials"]:
            item["serials"].append(serial)


# --------------------------------------------------------------------------
# Meyer Sound
#   8518210000 1 12 09.338.001.04  1800-LFC,EU,OT,NO RIG,GEN-1
#   S/N: 26476604
#   S/N: 26476618$4,600.0000 $55,200.00
#   8518908100 3 4 40.338.200.01  MCF-T2 CASTER FRAME $840.0000 $3,360.00
# --------------------------------------------------------------------------
_MEYER_REPLACEMENT_RE = re.compile(
    r"(?i)\bREPLACEMENTS?\s+TO\s+SERIAL\s+NUMBERS?\s*:?\s*"
)
_MEYER_SERVICE_RE = re.compile(
    r"(?i)\bSERVICE\s+TO\s+ONE\b.*?\bSER\s*\.\s*#\s*([A-Z0-9][A-Z0-9/-]*)"
)


def _parse_meyer(lines):
    items = []
    current = None
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        replacement = _MEYER_REPLACEMENT_RE.search(line)
        if replacement and current is not None:
            current["is_replacement"] = True
            remainder = line[replacement.end():]
            new_marker = _MARKER_RE.search(remainder)
            chunks = [remainder[:new_marker.start()] if new_marker else remainder]
            while not new_marker and index < len(lines):
                following = lines[index]
                if not following:
                    index += 1
                    continue
                if not re.fullmatch(r"[\d,\s]+", following):
                    break
                chunks.append(following)
                index += 1
            current["replaced_serials"] = list(dict.fromkeys(
                re.findall(r"\d+", " ".join(chunks))
            ))
            if new_marker:
                serials, index = _collect_serials(lines, index, remainder[new_marker.end():])
                _add_serials(current, serials)
            continue
        service = _MEYER_SERVICE_RE.search(line)
        if service and current is not None:
            _add_serials(current, [service.group(1)])
            continue
        marker = _MARKER_RE.search(line)
        if marker and current is not None and not _MEYER_PART_RE.search(line):
            serials, index = _collect_serials(lines, index, line[marker.end():])
            _add_serials(current, serials)
            continue
        match = _MEYER_LINE_RE.match(line)
        if match:
            current = {"code": match.group(3), "description": _clean_description(match.group(4)),
                       "qty": float(match.group(2)), "serials": [],
                       "is_replacement": False, "replaced_serials": []}
            items.append(current)
            continue
        part = _MEYER_PART_RE.search(line)
        if part:
            # Otra maquetación: al menos la referencia y, si se ve, «4 EA»
            unit = _QTY_UNIT_RE.search(line)
            rest = line[part.end():]
            if unit:
                rest = rest[: max(unit.start() - part.end(), 0)] or rest
            current = {"code": part.group(1), "description": _clean_description(rest),
                       "qty": float(unit.group(1)) if unit else 0, "serials": [],
                       "is_replacement": False, "replaced_serials": []}
            items.append(current)
    return _finish(items)


# --------------------------------------------------------------------------
# DiGiCo: cada celda de la tabla sale en su propia línea
#   1 / X-A-168 / 2.00 EA / 707.74 / 1,415.48 / 16 IN 8 OUT STAGE BOX
#   Serial Number:(s): / 168-102760, 168-102835
# --------------------------------------------------------------------------
def _parse_digico(lines):
    lines = [line for line in lines if line]
    starts = [i for i, line in enumerate(lines) if i >= 1 and _DIGICO_QTY_RE.match(line)]
    items = []
    for position, start in enumerate(starts):
        end = starts[position + 1] - 1 if position + 1 < len(starts) else len(lines)
        code = lines[start - 1]
        if not re.fullmatch(r"[\w\-/+.]{2,40}", code) or _AMOUNT_RE.fullmatch(code):
            continue
        item = {"code": code, "description": "", "qty": float(_DIGICO_QTY_RE.match(lines[start]).group(1)),
                "serials": []}
        index = start + 1
        while index < end:
            line = lines[index]
            index += 1
            if re.match(r"(?i)^(?:line\(s\) subtotal|total|GBP|EUR|USD)\b", line):
                break
            marker = _MARKER_RE.search(line)
            if marker:
                serials, index = _collect_serials(lines[:end], index, line[marker.end():])
                _add_serials(item, serials)
                continue
            if (not item["description"] and not item["serials"] and not _AMOUNT_RE.fullmatch(line)
                    and not line.isdigit() and not re.match(r"(?i)^HS Code", line)):
                item["description"] = line[:160]
        items.append(item)
    return _finish(items)


# --------------------------------------------------------------------------
# Luminex y, en general, facturas hechas con Odoo
#   [LU 01 00079-POE-1G] GigaCore 10t ...
#   Serial Numbers: / LUM079003272, / LUM079003270, / ...
#   4.00            <- la cantidad va después, sola en su línea
# --------------------------------------------------------------------------
_ODOO_END_RE = re.compile(r"(?i)^(?:untaxed amount|base imponible|subtotal|total\b|please use|payment terms)")
_ODOO_QTY_INLINE_RE = re.compile(r"\s(\d{1,5})[.,]\d{2,3}\s+(?:Units?|Unit\(s\)|Unidades|Uds?\.?|Stuks?|pcs?)\b", re.IGNORECASE)
_ODOO_QTY_LINE_RE = re.compile(r"^(\d{1,5})[.,]\d{2,3}$")


def _parse_luminex(lines):
    items = []
    current = None
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        bracket = _BRACKET_REF_RE.match(line)
        if bracket:
            rest = line[bracket.end():]
            inline = _ODOO_QTY_INLINE_RE.search(rest)
            current = {"code": bracket.group(1).strip(),
                       "description": (rest[: inline.start()] if inline else rest).strip()[:160],
                       "qty": float(inline.group(1)) if inline else 0, "serials": []}
            items.append(current)
            continue
        if current is None:
            continue
        if _ODOO_END_RE.match(line):
            current = None
            continue
        marker = _MARKER_RE.search(line)
        if marker:
            serials, index = _collect_serials(lines, index, line[marker.end():])
            _add_serials(current, serials)
            continue
        quantity = _ODOO_QTY_LINE_RE.match(line)
        if quantity and not current["qty"]:
            current["qty"] = float(quantity.group(1))
    return _finish(items)


# --------------------------------------------------------------------------
# DSPecialists / Harvey: posición y cantidad pegada a la marca; series abreviadas
#   1 3HARVEY Pro 8x8-DA
#   S/N: 12-2350-019, S/N: 12-2429-087, -088 3.495,00 € 10.485,00 €
#   2 350% distribution discount (Pos. 1) -1.747,50 € -5.242,50 €   <- no es artículo
# --------------------------------------------------------------------------
def _parse_harvey(lines):
    items = []
    current = None
    in_table = False
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        if re.match(r"(?i)^Pos\.?\s", line):
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r"(?i)^(?:total amount|summe|gesamt|total\b)", line):
            break
        marker = _MARKER_RE.search(line)
        if marker and not _HARVEY_LINE_RE.match(line):
            if current is not None:
                serials, index = _collect_serials(lines, index, line[marker.end():])
                _add_serials(current, serials)
            continue
        match = _HARVEY_LINE_RE.match(line)
        if not match:
            continue
        if _DISCOUNT_RE.search(line) or re.search(r"\s-\d[\d.]*,\d{2}", line):
            current = None
            continue
        body = match.group(3)
        inline = _MARKER_RE.search(body)
        name = _clean_description(body[: inline.start()] if inline else body)
        # La factura no trae referencia: el nombre del modelo hace de código
        current = {"code": name, "description": name, "qty": float(match.group(2)), "serials": []}
        items.append(current)
        if inline:
            serials, index = _collect_serials(lines, index, body[inline.end():])
            _add_serials(current, serials)
    return _finish(items)


# --------------------------------------------------------------------------
# Optocore: toda la factura sale en una sola línea
#   ... Pos. Qty. Type Single Price Total Price 1 1 M8-OPT descripción SN: E26-0497 4.395,00 € 4.395,00 € ...
# --------------------------------------------------------------------------
_OPTOCORE_ITEM_RE = re.compile(
    r"(?<!\S)(\d{1,3})\s+(\d{1,4})\s+([A-Z0-9][\w\-/+.]*)\s+(.{0,300}?)\s*"
    r"(?:\bSN\s*:\s*([A-Z0-9][A-Z0-9\-/]*(?:\s*,\s*-?[A-Z0-9][A-Z0-9\-/]*)*)\s+)?"
    r"(\d[\d.]*,\d{2})\s*€\s+(\d[\d.]*,\d{2})\s*€")


def _parse_optocore(lines):
    text = " ".join(line for line in lines if line)
    header = re.search(r"(?i)Pos\.\s*Qty\.\s*Type\s*Single Price\s*Total Price", text)
    if not header:
        return []
    body = re.split(r"(?i)\bSubtotal\s*:", text[header.end():])[0]
    items = []
    for match in _OPTOCORE_ITEM_RE.finditer(body):
        items.append({
            "code": match.group(3), "description": match.group(4).strip()[:160], "qty": float(match.group(2)),
            "serials": expand_serial_list(match.group(5)) if match.group(5) else [],
        })
    return _finish(items)


# --------------------------------------------------------------------------
# Waves: tabla de artículos y, más abajo, un bloque «Serial Numbers»
#   USW379-700C-334 Extreme-C SoundGrid Server 1.00 USD 1,721.85  1
#   Serial Numbers / USW379-700C-334 Extreme-C SoundGrid Server / 6C489F62A05641
# --------------------------------------------------------------------------
_WAVES_ITEM_RE = re.compile(r"^(\S+)\s+(.+?)\s+[\d,]+\.\d{2}\s+(?:USD|EUR|GBP)\s+[\d,]+\.\d{2}\s+(\d{1,4})$")


def _parse_waves(lines):
    items = OrderedItems()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        match = _WAVES_ITEM_RE.match(line)
        if match:
            items.add(match.group(1), match.group(2), float(match.group(3)))
            continue
        if re.fullmatch(r"(?i)serial numbers?:?", line):
            current = None
            while index < len(lines):
                row = lines[index]
                code = row.split(" ")[0] if row else ""
                if code in items.by_code:
                    current = items.by_code[code]
                elif current is not None and re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{5,}", row) and _looks_like_serial(row):
                    _add_serials(current, [row])
                else:
                    break
                index += 1
    return _finish(items.items)


class OrderedItems:
    def __init__(self):
        self.items = []
        self.by_code = {}

    def add(self, code, description, qty):
        item = {"code": code, "description": description.strip()[:160], "qty": qty, "serials": []}
        self.items.append(item)
        self.by_code.setdefault(code, item)
        return item


# --------------------------------------------------------------------------
# Genérico: SOLO series detrás de un rótulo. Sin rótulo no se inventa nada.
# --------------------------------------------------------------------------
def _parse_generic(lines):
    items = []
    last_text = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        marker = _MARKER_RE.search(line)
        if not marker:
            last_text = line
            continue
        serials, index = _collect_serials(lines, index, line[marker.end():])
        # Un rótulo con una sola «serie» corta o sin letras/guiones mezclada en
        # un párrafo largo suele ser otra cosa (nº de cuenta, de pedido...).
        serials = [s for s in serials if len(s) >= 5]
        if not serials:
            continue
        before = line[: marker.start()].strip(" :-")
        source = before if len(before) > 3 else last_text
        if len(source) > 160:
            source = ""
        bracket = _BRACKET_REF_RE.search(source)
        code = bracket.group(1).strip() if bracket else ""
        description = _clean_description(source[bracket.end():] if bracket else source)
        if items and not before and items[-1]["description"] == description and items[-1]["code"] == code:
            _add_serials(items[-1], serials)
        else:
            items.append({"code": code, "description": description, "qty": 0, "serials": serials})
    return _finish(items)


_PARSERS = {
    "meyer": _parse_meyer,
    "digico": _parse_digico,
    "luminex": _parse_luminex,
    "harvey": _parse_harvey,
    "optocore": _parse_optocore,
    "waves": _parse_waves,
    "generic": _parse_generic,
}


def detect_format(text):
    """Formato más probable del documento."""
    text = text or ""
    low = text.lower()
    if "meyer sound" in low or (_MEYER_PART_RE.search(text) and re.search(r"(?i)\bS\s*/\s*N\b", text)):
        return "meyer"
    if "digico" in low or re.search(r"(?i)serial\s*number\s*:\s*\(s\)", text):
        return "digico"
    if "dspecialists" in low or "harvey" in low:
        return "harvey"
    if "optocore" in low:
        return "optocore"
    if "waves.com" in low or "waves inc" in low:
        return "waves"
    if "luminex" in low or re.search(r"(?m)^\s*\[[^\]\[]{2,60}\]\s+\S", text):
        return "luminex"
    return "generic"


def parse_document(text, fmt="auto"):
    """Devuelve (formato usado, líneas). Si el lector elegido no saca nada,
    prueba el genérico (que solo devuelve series con rótulo) antes de rendirse."""
    used = detect_format(text) if fmt in (False, None, "", "auto") else fmt
    lines = _clean_lines(text)
    result = _PARSERS.get(used, _parse_generic)(lines)
    if not result and used != "generic":
        result = _parse_generic(lines)
        if result:
            used = "generic"
    return used, result


def parse_pasted(text):
    """Texto pegado: una serie por línea, o «referencia <tab> serie»
    (también con punto y coma). Una tercera columna es la cantidad; con
    la serie vacía la línea se recibe por cantidad."""
    result = []
    for line in (text or "").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        if "\t" in line or ";" in line:
            cells = [c.strip() for c in re.split(r"[\t;]", line)]
            cells += [""] * (3 - len(cells))
            code, serial, qty = cells[0], cells[1], cells[2]
            quantity = 1.0
            if not serial:
                try:
                    quantity = float((qty or "1").replace(",", ".")) or 1.0
                except ValueError:
                    quantity = 1.0
            if not code and not serial:
                continue
            result.append({"code": code, "description": "", "serial": serial, "qty": quantity, "warning": ""})
        else:
            result.append({"code": "", "description": "", "serial": line.strip(), "qty": 1.0, "warning": ""})
    return result
