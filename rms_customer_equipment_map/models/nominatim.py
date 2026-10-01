"""Nominatim (OpenStreetMap) geocoding tuned for Spanish addresses.

Odoo's standard OpenStreetMap geocoder sends the raw address as free text,
fires two requests in a row for every contact that is not found and reads
any answer as JSON. Nominatim then answers "429 Too many requests" with an
HTML page, which Odoo reports as "Expecting value: line 2 column 1".

This module:

* cleans the street before searching (abbreviations, floor, door, unit...),
* tries a few queries from the most to the least precise,
* rejects results in another province than the postal code,
* waits between requests to respect the usage policy (1 request/second),
* turns HTTP errors into explicit messages, with a retry delay for 429.
"""

import logging
import re
import threading
import time
import unicodedata

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT = 15
# Seconds between two requests of this server process (policy: max 1/s).
NOMINATIM_MIN_INTERVAL = 1.2
# Seconds to wait when Nominatim answers 429 without a Retry-After header.
NOMINATIM_DEFAULT_RETRY_AFTER = 30

_throttle_lock = threading.Lock()
_last_request_at = [0.0]

STREET_PREFIXES = [
    # Industrial estates first: "Pol." must not be read as "Paseo".
    (r"pol(?:[íi]gono)?\.?\s*ind(?:ustrial)?\.?\s*", "Polígono Industrial "),
    (r"p\.\s*i\.\s*", "Polígono Industrial "),
    (r"pg\.?\s*ind\.?\s*", "Polígono Industrial "),
    (r"c\s*/\s*", "Calle "),
    (r"cl\.?\s+", "Calle "),
    (r"cll\.?\s+", "Calle "),
    (r"avda\.?\s*", "Avenida "),
    (r"av\.?\s+", "Avenida "),
    (r"pza\.?\s*", "Plaza "),
    (r"pl\.?\s+", "Plaza "),
    (r"p[º°]\.?\s*", "Paseo "),
    (r"po\.\s*", "Paseo "),
    (r"ps\.?\s+", "Paseo "),
    (r"ctra\.?\s*", "Carretera "),
    (r"crta\.?\s*", "Carretera "),
    (r"urb\.?\s+", "Urbanización "),
]
# Everything from these words on is not useful to locate a building.
STREET_DETAILS = re.compile(
    r"\s*(?:\b\d+\s*[ºª°]|\b(?:piso|planta|pta|puerta|bajo|bajos|local|nave|"
    r"portal|esc|escalera|oficina|of|dcha|izda|dpto|departamento|bloque|blq)\b).*$",
    re.IGNORECASE,
)
STREET_NUMBER = re.compile(r"^(?:n[º°o]?\.?\s*)?(\d+[a-z]?)$", re.IGNORECASE)


class GeoLocalizeServiceError(UserError):
    """The geolocation service did not answer usefully (not a "not found")."""

    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def clean_street(street):
    """Return the street and number only, with common abbreviations expanded.

    ``"C/ Gran Vía, 28, 2º B"`` gives ``"Calle Gran Vía 28"``.
    """
    if not street:
        return ""
    parts = [part.strip() for part in street.replace(";", ",").split(",") if part.strip()]
    if not parts:
        return ""
    name = parts[0]
    # A street number written after a comma: "Calle Mayor, 5".
    if len(parts) > 1:
        number = STREET_NUMBER.match(parts[1])
        if number:
            name = f"{name} {number.group(1)}"
    for pattern, replacement in STREET_PREFIXES:
        new_name = re.sub(rf"^{pattern}", replacement, name, count=1, flags=re.IGNORECASE)
        if new_name != name:
            name = new_name
            break
    name = STREET_DETAILS.sub("", name)
    name = re.sub(r"\bs\s*/\s*n\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\bn[º°]\.?\s*(\d)", r"\1", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip(" ,.-")


def build_queries(street="", zip_code="", city="", state="", country=""):
    """Queries to try, from the most to the least precise.

    :return: list of ``(query, precise)``; ``precise`` is True for the
        queries that include the street.
    """
    locality = " ".join(filter(None, (zip_code, city)))
    queries = []
    cleaned_street = clean_street(street)
    if cleaned_street and (locality or state):
        streets = [cleaned_street]
        # OpenStreetMap often names streets without the generic "Calle"
        # ("Gran Vía", not "Calle Gran Vía").
        if cleaned_street.lower().startswith("calle "):
            streets.append(cleaned_street[6:])
        for street_name in streets:
            queries.append(
                (", ".join(filter(None, (street_name, locality, state, country))), True)
            )
    if locality:
        queries.append((", ".join(filter(None, (locality, state, country))), False))
    if city and state:
        queries.append((", ".join(filter(None, (city, state, country))), False))
    elif not locality and state:
        queries.append((", ".join(filter(None, (state, country))), False))
    # Keep the order, drop duplicates.
    return list(dict.fromkeys(queries))


def _normalize(value):
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in value if not unicodedata.combining(char)).lower().strip()


def _throttle():
    with _throttle_lock:
        wait = _last_request_at[0] + NOMINATIM_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at[0] = time.monotonic()


def _request(query, country_code, headers, email):
    import requests  # noqa: PLC0415

    params = {
        "format": "jsonv2",
        "q": query,
        "limit": 1,
        "addressdetails": 1,
    }
    if country_code:
        params["countrycodes"] = country_code.lower()
    if email:
        params["email"] = email
    _throttle()
    try:
        response = requests.get(
            NOMINATIM_URL, params=params, headers=headers, timeout=NOMINATIM_TIMEOUT
        )
    except requests.RequestException as error:
        raise GeoLocalizeServiceError(
            f"No se pudo conectar con Nominatim (OpenStreetMap): {error}"
        ) from error
    if response.status_code == 429:
        try:
            retry_after = int(response.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = NOMINATIM_DEFAULT_RETRY_AFTER
        raise GeoLocalizeServiceError(
            "Nominatim (OpenStreetMap) pide esperar: demasiadas peticiones seguidas "
            "(HTTP 429).",
            retry_after=retry_after,
        )
    if response.status_code == 403:
        raise GeoLocalizeServiceError(
            "Nominatim (OpenStreetMap) ha bloqueado las peticiones de este servidor "
            "(HTTP 403). Suele deberse a un uso excesivo; se puede configurar Google "
            "Maps como proveedor en Ajustes > Geolocalización."
        )
    if response.status_code != 200:
        raise GeoLocalizeServiceError(
            f"Respuesta inesperada de Nominatim (OpenStreetMap): HTTP {response.status_code}."
        )
    try:
        results = response.json()
    except ValueError as error:
        raise GeoLocalizeServiceError(
            "Nominatim (OpenStreetMap) ha devuelto una respuesta no válida."
        ) from error
    return results if isinstance(results, list) else []


def _matches(result, zip_code, city, precise):
    """Reject results that are not where the contact's address says.

    A street search must fall in the same postal code or the same town; a
    town or postal code search must fall in the same province.
    """
    address = result.get("address") or {}
    result_zip = (address.get("postcode") or "").strip()
    zip_code = (zip_code or "").strip()
    if not precise:
        if len(zip_code) < 2 or len(result_zip) < 2:
            return True
        return result_zip[:2] == zip_code[:2]
    if zip_code and result_zip and result_zip == zip_code:
        return True
    city = _normalize(city)
    if city:
        towns = {
            _normalize(address.get(key))
            for key in ("city", "town", "village", "municipality", "suburb", "hamlet")
            if address.get(key)
        }
        if any(city == town or city in town or town in city for town in towns):
            return True
        return False
    # No town to compare with: fall back to the postal code (if any).
    return not (zip_code and result_zip)


def geo_localize(street="", zip_code="", city="", state="", country="", country_code="",
                 headers=None, email=""):
    """Return ``(latitude, longitude)`` or ``None`` when the address is not found.

    :raises GeoLocalizeServiceError: when Nominatim does not answer usefully.
    """
    for query, precise in build_queries(
        street, zip_code, city, state, "" if country_code else country
    ):
        for result in _request(query, country_code, headers or {}, email):
            if _matches(result, zip_code, city, precise):
                return float(result["lat"]), float(result["lon"])
            _logger.info(
                "Nominatim result for %r ignored: %s is not in %s %s",
                query,
                result.get("display_name"),
                zip_code,
                city,
            )
    return None
