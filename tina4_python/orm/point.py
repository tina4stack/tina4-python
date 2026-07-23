# Tina4 ORM Point — SRID-aware geographic point value object.
"""
``Point`` is the in-memory value a :class:`~tina4_python.orm.fields.PointField`
hands you. It is deliberately tiny: two coordinates plus an SRID, and the three
representations a GIS developer actually needs.

    from tina4_python.orm import Point

    cape_town = Point(18.4241, -33.9249)     # (longitude, latitude)
    cape_town.lon                             # 18.4241
    cape_town.lat                             # -33.9249
    cape_town.wkt                             # 'POINT(18.4241 -33.9249)'
    cape_town.geojson                         # {'type': 'Point', 'coordinates': [18.4241, -33.9249]}
    cape_town.srid                            # 4326

**Longitude first.** Every representation here is ``(lon, lat)`` / ``(x, y)`` —
WKT, GeoJSON and PostGIS ``ST_MakePoint`` all order it that way. The tuple form
follows the same order, so ``Point(*some_geojson["coordinates"])`` is correct and
``tuple(point)`` round-trips.

:meth:`Point.parse` is the single coercion funnel used by ``PointField``
assignment, ``QueryBuilder`` spatial predicates and the database read path, so
every entry point accepts exactly the same value shapes:

    Point.parse((18.4241, -33.9249))                             # tuple / list
    Point.parse("POINT(18.4241 -33.9249)")                        # WKT
    Point.parse("SRID=4326;POINT(18.4241 -33.9249)")              # EWKT
    Point.parse({"type": "Point", "coordinates": [18.42, -33.9]})  # GeoJSON
    Point.parse("0101000020E6100000CD3B4ED1916C324003098A1F63F640C0")  # HEXEWKB (what PostGIS returns)
"""
import re as _re
import struct as _struct

# WGS 84 — the SRID the entire web (GPS, GeoJSON, OpenStreetMap, Google Maps)
# speaks. GeoJSON (RFC 7946) mandates it, so it is the only sane default.
DEFAULT_SRID = 4326

# EWKB type-word flags (PostGIS extension to the OGC WKB spec).
_EWKB_SRID_FLAG = 0x20000000
_EWKB_M_FLAG = 0x40000000
_EWKB_Z_FLAG = 0x80000000

_WKT_POINT = _re.compile(
    r"^\s*(?:SRID\s*=\s*(?P<srid>\d+)\s*;\s*)?"
    r"POINT\s*(?:Z|M|ZM)?\s*\(\s*(?P<lon>[-+0-9.eE]+)\s+(?P<lat>[-+0-9.eE]+)"
    r"(?:\s+[-+0-9.eE]+)*\s*\)\s*$",
    _re.IGNORECASE,
)
_HEX = _re.compile(r"^[0-9a-fA-F]+$")

# Any OGC geometry in WKT/EWKT form — the gate `geometry_binding` uses so an
# obviously-not-a-geometry string fails HERE with a readable message instead of
# as an opaque driver error one round trip later.
_WKT_GEOMETRY = _re.compile(
    r"^\s*(?:SRID\s*=\s*(?P<srid>\d+)\s*;\s*)?"
    r"(?:POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON"
    r"|GEOMETRYCOLLECTION|CIRCULARSTRING|COMPOUNDCURVE|CURVEPOLYGON"
    r"|MULTICURVE|MULTISURFACE|TRIANGLE|TIN|POLYHEDRALSURFACE)"
    r"\s*(?:Z|M|ZM)?\s*(?:\(|EMPTY\b)",
    _re.IGNORECASE,
)

_GEOJSON_GEOMETRY_TYPES = frozenset({
    "point", "linestring", "polygon", "multipoint", "multilinestring",
    "multipolygon", "geometrycollection",
})


class Point:
    """An immutable ``(longitude, latitude)`` pair with an SRID.

    Args:
        lon: Longitude / X ordinate, -180..180 for SRID 4326.
        lat: Latitude / Y ordinate, -90..90 for SRID 4326.
        srid: Spatial reference id. Defaults to 4326 (WGS 84).

    Raises:
        ValueError: if the coordinates are not numbers, or are outside the
            valid lon/lat range when ``srid`` is 4326. A swapped lat/lon pair
            (the single commonest GIS mistake) is caught here rather than
            silently stored as a point in the wrong hemisphere.
    """

    __slots__ = ("_lon", "_lat", "_srid")

    def __init__(self, lon, lat, srid: int = DEFAULT_SRID):
        try:
            lon = float(lon)
            lat = float(lat)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Point: longitude and latitude must be numbers, got "
                f"lon={lon!r}, lat={lat!r}"
            ) from e
        try:
            srid = int(srid)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Point: srid must be an integer, got {srid!r}") from e

        # Only range-check when we know the units are degrees. A projected SRID
        # (metres, feet) has no such bounds, so validating there would be wrong.
        if srid == DEFAULT_SRID:
            if not -180.0 <= lon <= 180.0:
                raise ValueError(
                    f"Point: longitude {lon} is out of range for SRID 4326 "
                    f"(-180..180). Tina4 uses (lon, lat) order — did you pass "
                    f"latitude first?"
                )
            if not -90.0 <= lat <= 90.0:
                raise ValueError(
                    f"Point: latitude {lat} is out of range for SRID 4326 "
                    f"(-90..90). Tina4 uses (lon, lat) order — did you pass "
                    f"latitude first?"
                )

        object.__setattr__(self, "_lon", lon)
        object.__setattr__(self, "_lat", lat)
        object.__setattr__(self, "_srid", srid)

    # Immutability: a Point handed to a query must not mutate under the caller.
    def __setattr__(self, name, value):
        raise AttributeError(
            "Point is immutable — build a new Point instead of assigning "
            f"{name!r}."
        )

    @property
    def lon(self) -> float:
        """Longitude (X ordinate)."""
        return self._lon

    @property
    def lat(self) -> float:
        """Latitude (Y ordinate)."""
        return self._lat

    @property
    def srid(self) -> int:
        """Spatial reference id (4326 unless set otherwise)."""
        return self._srid

    @property
    def wkt(self) -> str:
        """OGC Well-Known Text: ``POINT(lon lat)``."""
        return f"POINT({self._fmt(self._lon)} {self._fmt(self._lat)})"

    @property
    def ewkt(self) -> str:
        """PostGIS Extended WKT: ``SRID=4326;POINT(lon lat)``.

        This is the form :meth:`PointField.to_db` writes — it carries the SRID
        with the geometry so the database never has to guess.
        """
        return f"SRID={self._srid};{self.wkt}"

    @property
    def geojson(self) -> dict:
        """RFC 7946 GeoJSON geometry: ``{"type": "Point", "coordinates": [lon, lat]}``."""
        return {"type": "Point", "coordinates": [self._lon, self._lat]}

    def to_dict(self) -> dict:
        """Alias for :attr:`geojson` — what ``response()`` serialises."""
        return self.geojson

    def to_tuple(self) -> tuple:
        """``(lon, lat)`` — the order every representation here uses."""
        return (self._lon, self._lat)

    @staticmethod
    def _fmt(value: float) -> str:
        """Render a coordinate without a trailing ``.0`` and without exponent noise."""
        text = repr(value)
        return text[:-2] if text.endswith(".0") else text

    # ── Coercion ────────────────────────────────────────────────────

    @classmethod
    def parse(cls, value, srid: int = DEFAULT_SRID) -> "Point":
        """Coerce any supported representation into a :class:`Point`.

        Accepts a ``Point``, a ``(lon, lat)`` tuple/list, a WKT or EWKT string,
        a GeoJSON ``dict``, or (H)EWKB as hex text / raw bytes — the form
        PostGIS returns on a plain ``SELECT``.

        Args:
            value: The value to coerce.
            srid: SRID to assume when the value does not carry one.

        Raises:
            ValueError: with the offending value in the message, when the shape
                is not a point. Never guesses.
        """
        if isinstance(value, cls):
            return value

        if isinstance(value, dict):
            return cls._from_geojson(value, srid)

        if isinstance(value, (tuple, list)):
            if len(value) < 2:
                raise ValueError(
                    f"Point.parse: a coordinate pair needs 2 values (lon, lat), "
                    f"got {value!r}"
                )
            return cls(value[0], value[1], srid)

        if isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            # Binary WKB always starts with the endianness byte 0x00 or 0x01,
            # neither of which is an ASCII hex digit — so the first byte tells
            # binary WKB and hex-text-as-bytes apart with no ambiguity.
            if raw and raw[0] not in (0, 1):
                return cls._from_wkb(bytes.fromhex(raw.decode("ascii", "ignore")), srid)
            return cls._from_wkb(raw, srid)

        if isinstance(value, str):
            text = value.strip()
            match = _WKT_POINT.match(text)
            if match:
                found_srid = match.group("srid")
                return cls(
                    match.group("lon"),
                    match.group("lat"),
                    int(found_srid) if found_srid else srid,
                )
            if len(text) >= 42 and len(text) % 2 == 0 and _HEX.match(text):
                return cls._from_wkb(bytes.fromhex(text), srid)
            raise ValueError(
                f"Point.parse: cannot read {value!r} as a point. Supported: "
                f"a (lon, lat) tuple, 'POINT(lon lat)' WKT, "
                f"'SRID=4326;POINT(lon lat)' EWKT, a GeoJSON "
                f"{{'type': 'Point', 'coordinates': [lon, lat]}} dict, or "
                f"(HEX)EWKB."
            )

        raise ValueError(
            f"Point.parse: unsupported type {type(value).__name__} — expected a "
            f"Point, a (lon, lat) tuple, a WKT/EWKT string, a GeoJSON dict, or "
            f"(HEX)EWKB."
        )

    @classmethod
    def _from_geojson(cls, data: dict, srid: int) -> "Point":
        """Build from an RFC 7946 GeoJSON geometry (or a Feature wrapping one)."""
        geometry = data
        if str(data.get("type", "")).lower() == "feature":
            geometry = data.get("geometry") or {}
        geometry_type = str(geometry.get("type", ""))
        if geometry_type.lower() != "point":
            raise ValueError(
                f"Point.parse: GeoJSON type must be 'Point', got "
                f"{geometry_type or 'nothing'!r}. Only point geometries are "
                f"supported by PointField."
            )
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise ValueError(
                f"Point.parse: GeoJSON 'coordinates' must be [lon, lat], got "
                f"{coordinates!r}"
            )
        # RFC 7946 fixes GeoJSON to WGS 84, but honour an explicit crs name if
        # one is present (older GeoJSON) rather than silently ignoring it.
        crs = (geometry.get("crs") or {}).get("properties", {}).get("name") \
            if isinstance(geometry.get("crs"), dict) else None
        if crs:
            digits = _re.findall(r"(\d+)$", str(crs))
            if digits:
                srid = int(digits[0])
        return cls(coordinates[0], coordinates[1], srid)

    @classmethod
    def _from_wkb(cls, raw: bytes, srid: int) -> "Point":
        """Parse OGC WKB / PostGIS EWKB for a point.

        PostGIS returns a geography/geometry column as HEXEWKB on a plain
        ``SELECT``, so this is the read path for every ORM query — ``find()``,
        ``all()``, ``where()`` all issue ``SELECT *`` and never wrap the column
        in ``ST_AsText``. Parsing it here means the ORM read path needs no
        spatial SQL at all.
        """
        if len(raw) < 21:
            raise ValueError(
                f"Point.parse: WKB is too short to be a point "
                f"({len(raw)} bytes, need at least 21)"
            )
        endian = "<" if raw[0] == 1 else ">"
        type_word = _struct.unpack(endian + "I", raw[1:5])[0]
        offset = 5
        if type_word & _EWKB_SRID_FLAG:
            srid = _struct.unpack(endian + "I", raw[5:9])[0]
            offset = 9
        # Low bits carry the geometry type. EWKB keeps it in 1..7 with the high
        # flag bits set; ISO WKB encodes Z/M dimensionality as 1000/2000/3000
        # offsets (1001 = PointZ), so reduce modulo 1000.
        geometry_code = (type_word & ~(_EWKB_SRID_FLAG | _EWKB_Z_FLAG | _EWKB_M_FLAG)) % 1000
        if geometry_code != 1:
            raise ValueError(
                f"Point.parse: WKB geometry type {geometry_code} is not a Point "
                f"(1). PointField stores single points only."
            )
        lon, lat = _struct.unpack(endian + "dd", raw[offset:offset + 16])
        return cls(lon, lat, srid)

    # ── Protocol ────────────────────────────────────────────────────

    def __iter__(self):
        """Unpack as ``lon, lat = point`` / ``tuple(point)``."""
        yield self._lon
        yield self._lat

    def __eq__(self, other):
        if isinstance(other, Point):
            return (
                self._lon == other._lon
                and self._lat == other._lat
                and self._srid == other._srid
            )
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return (self._lon, self._lat) == (float(other[0]), float(other[1]))
        return NotImplemented

    def __hash__(self):
        return hash((self._lon, self._lat, self._srid))

    def __str__(self):
        return self.wkt

    def __repr__(self):
        return f"Point(lon={self._lon}, lat={self._lat}, srid={self._srid})"


def geometry_binding(value, srid: int = DEFAULT_SRID) -> tuple[str, str]:
    """Normalise ANY geometry into one bound value plus its encoding.

    :meth:`Point.parse` is the funnel for single points; this is the funnel for
    the general geometries the spatial predicates take — the polygon of a
    geofence, the rectangle of a map viewport, a route line. It returns
    ``(bound_value, form)`` where ``form`` is ``"ewkt"`` or ``"geojson"``,
    matching :meth:`~tina4_python.database.adapter.SQLTranslator.geometry_literal`.

    The geometry travels as ONE bound parameter, so no coordinate is ever
    formatted into SQL, and the database (not a hand-rolled WKT writer) does the
    parsing::

        geometry_binding("POLYGON((17.5 -34.5, 19.5 -34.5, 19.5 -33, 17.5 -33, 17.5 -34.5))")
        # ('SRID=4326;POLYGON((17.5 -34.5, ...))', 'ewkt')

        geometry_binding({"type": "Polygon", "coordinates": [[[17.5, -34.5], ...]]})
        # ('{"type": "Polygon", "coordinates": ...}', 'geojson')

    Args:
        value: A ``Point``, a ``(lon, lat)`` pair, a WKT/EWKT string of any
            geometry type, or a GeoJSON geometry / Feature ``dict``.
        srid: SRID to assume when the value does not carry one.

    Returns:
        ``(bound_value, form)``.

    Raises:
        ValueError: naming the offending value, when the shape is not a
            geometry. Never guesses.
    """
    import json

    if isinstance(value, Point):
        return value.ewkt, "ewkt"

    if isinstance(value, (tuple, list)):
        return Point.parse(value, srid).ewkt, "ewkt"

    if isinstance(value, dict):
        geometry = value
        if str(value.get("type", "")).lower() == "feature":
            geometry = value.get("geometry") or {}
        geometry_type = str(geometry.get("type", ""))
        if geometry_type.lower() not in _GEOJSON_GEOMETRY_TYPES:
            raise ValueError(
                f"geometry_binding: GeoJSON 'type' must be one of "
                f"{sorted(_GEOJSON_GEOMETRY_TYPES)}, got "
                f"{geometry_type or 'nothing'!r}."
            )
        if geometry_type.lower() == "geometrycollection":
            if not isinstance(geometry.get("geometries"), list):
                raise ValueError(
                    "geometry_binding: a GeoJSON GeometryCollection needs a "
                    "'geometries' list."
                )
        elif not isinstance(geometry.get("coordinates"), (list, tuple)):
            raise ValueError(
                f"geometry_binding: GeoJSON 'coordinates' must be a list, got "
                f"{geometry.get('coordinates')!r}."
            )
        return json.dumps(geometry), "geojson"

    if isinstance(value, str):
        text = value.strip()
        match = _WKT_GEOMETRY.match(text)
        if match:
            # EWKT carries its own SRID; plain WKT gets the caller's, so the
            # engine never has to assume one.
            return (text if match.group("srid") else f"SRID={int(srid)};{text}"), "ewkt"
        raise ValueError(
            f"geometry_binding: cannot read {value!r} as a geometry. Supported: "
            f"a (lon, lat) tuple, a Point, WKT/EWKT such as "
            f"'POLYGON((lon lat, ...))', or a GeoJSON geometry dict."
        )

    raise ValueError(
        f"geometry_binding: unsupported type {type(value).__name__} — expected a "
        f"Point, a (lon, lat) tuple, a WKT/EWKT string, or a GeoJSON dict."
    )
