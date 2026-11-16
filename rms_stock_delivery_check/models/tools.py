"""Limpieza de lecturas de la pistola (copiado lo mínimo de
rms_stock_count_session para no depender de ese módulo)."""
import re

_SERIAL_PREFIX_RE = re.compile(
    r"^(?:S\s*/\s*N\s*[:#.\-]?\s*|(?:SN|SERIAL(?:\s*N(?:O|UMBER)?\.?)?)\s*[:#.\-\s]\s*)",
    re.IGNORECASE,
)
_AIM_PREFIX_RE = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _gtin_check_digit(body):
    total = sum(int(ch) * (3 if i % 2 == 0 else 1) for i, ch in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def is_valid_gtin(code):
    """EAN-8, UPC-A, EAN-13 o GTIN-14 con dígito de control correcto: un
    código de producto nunca es un nº de serie."""
    return (bool(code) and code.isdigit() and len(code) in (8, 12, 13, 14)
            and _gtin_check_digit(code[:-1]) == code[-1])


def clean_code(raw):
    code = _CONTROL_RE.sub("", raw or "").strip()
    # Lector con teclado inglés en un ordenador en español: el "-" llega como "'".
    code = code.replace("'", "-")
    code = _AIM_PREFIX_RE.sub("", code)
    code = _SERIAL_PREFIX_RE.sub("", code).strip()
    return code
