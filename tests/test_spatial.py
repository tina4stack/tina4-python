"""Spatial / GIS tests — PointField, spatial DDL, QueryBuilder predicates, GeoJSON.

Phase 1a of plan/v3/iot-and-ev-charging.md. Python is the master design the
PHP / Ruby / Node mirrors follow, so these tests pin the CONTRACT, not just the
implementation.

**No mocks.** The spatial engine here is a real PostGIS container and the
negative engine case is a real SQLite file — nothing is stubbed. Provision it
the way CI does (.github/workflows/test.yml, service `postgis`)::

    docker run -d --name tina4-postgis -p 55433:5432 \
        -e POSTGRES_USER=tina4 -e POSTGRES_PASSWORD=tina4 \
        -e POSTGRES_DB=tina4_gis postgis/postgis:16-3.4

Override with TINA4_TEST_POSTGIS_URL. The PostGIS tests skip cleanly when no
service is listening locally; in CI the conftest TINA4_REQUIRE_SERVICES gate
turns that skip into a hard failure, so they always RUN there.

Known-answer distance fixtures are real WGS 84 geodesic distances measured
against PostGIS 3.4 (ST_Distance on geography, metres):

    Cape Town  -> Johannesburg   1 261 119.44 m
    Cape Town  -> Durban         1 273 094.55 m
    Johannesburg -> Durban         499 521.49 m
"""
from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlparse

import pytest

from tina4_python.database import Database
from tina4_python.database.adapter import SQLTranslator, SpatialNotSupportedError
from tina4_python.orm import (
    ORM,
    IntegerField,
    Point,
    PointField,
    StringField,
    bind_database,
    feature_collection,
)
from tina4_python.orm import model as orm_model
from tina4_python.orm.point import geometry_binding
from tina4_python.query_builder import QueryBuilder

# ── Known-answer geography fixtures (lon, lat) ──────────────────────
CAPE_TOWN = (18.4241, -33.9249)
JOHANNESBURG = (28.0473, -26.2041)
DURBAN = (31.0218, -29.8587)
PORT_ELIZABETH = (25.6022, -33.9608)

CPT_TO_JNB_METRES = 1_261_119.44
CPT_TO_DBN_METRES = 1_273_094.55
JNB_TO_DBN_METRES = 499_521.49
CPT_TO_PLZ_METRES = 663_467.49

# ── Edge fixtures (lon, lat) ────────────────────────────────────────
# Cape Town with the pair typed the way a human says it ("lat, long"). Both
# ordinates are individually in range, so nothing rejects it — only the
# geography does, by landing the point in the Atlantic off West Africa.
SWAPPED_CAPE_TOWN = (-33.9249, 18.4241)
ANTIMERIDIAN_EAST = (179.9, 0.0)
ANTIMERIDIAN_WEST = (-179.9, 0.0)
NORTH_POLE = (0.0, 89.999)
NORTH_POLE_OPPOSITE_MERIDIAN = (180.0, 89.999)
NULL_ISLAND = (0.0, 0.0)

# 115 km from Cape Town on a 38-degree bearing (ST_Project, measured below):
# OUTSIDE a 100 km circle, but inside the degree bounding box that circle
# implies — by both constructions a naive implementation uses, the square
# +/- R/110574 box (offsets 0.7585 and 0.8194 degrees vs a 0.9044 half-size) and
# the cos(lat)-corrected one. The discriminator for "radius is a circle, not a
# cheap bbox".
BBOX_CORNER = (19.182595, -33.105516)
BBOX_CORNER_RADIUS_METRES = 100_000.0
# The degree box a naive "radius as bounding box" implementation builds for a
# 100 km radius at Cape Town: lat +/- R/110574, lon +/- R/(111320*cos(lat)).
NAIVE_DEGREE_BBOX = (17.3415, -34.8293, 19.5067, -33.0205)

# Distances below are REAL WGS 84 geodesic metres, each measured once from the
# PostGIS container itself (PostGIS 3.4.3, GEOS 3.9.0, PROJ 7.2.1) with
# ``SELECT ST_Distance(a::geography, b::geography)`` — not estimated, not
# recalled. Re-derive with the same query if a fixture coordinate ever changes.
CPT_TO_SWAPPED_CPT_METRES = 8_021_546.75
ANTIMERIDIAN_CROSSING_METRES = 22_263.90
CPT_TO_NORTH_POLE_METRES = 13_757_190.98
ACROSS_THE_NORTH_POLE_METRES = 223.39
CPT_TO_BBOX_CORNER_METRES = 114_999.96

# HEXEWKB exactly as PostGIS returns SRID=4326;POINT(18.4241 -33.9249) on a
# plain SELECT — the read path every ORM query (SELECT *) goes through.
CAPE_TOWN_HEXEWKB = "0101000020E6100000CD3B4ED1916C324003098A1F63F640C0"


# ── Real PostGIS connection ─────────────────────────────────────────
POSTGIS_URL = os.environ.get(
    "TINA4_TEST_POSTGIS_URL", "postgres://tina4:tina4@localhost:55433/tina4_gis"
)
_parsed = urlparse(POSTGIS_URL)
POSTGIS_HOST = _parsed.hostname or "localhost"
POSTGIS_PORT = _parsed.port or 5432


def _postgis_reachable() -> bool:
    try:
        with socket.create_connection((POSTGIS_HOST, POSTGIS_PORT), timeout=1.0):
            return True
    except OSError:
        return False


postgis_required = pytest.mark.skipif(
    not _postgis_reachable(),
    reason=(
        f"postgis not reachable at {POSTGIS_HOST}:{POSTGIS_PORT} — start the "
        f"postgis/postgis container or set TINA4_TEST_POSTGIS_URL (skip)"
    ),
)


class SpatialSite(ORM):
    """The spatial model under test — one point column, auto GiST index."""

    table_name = "spatial_site"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    location = PointField()


class SpatialNoIndexSite(ORM):
    """spatial_index=False — column but no index."""

    table_name = "spatial_no_index_site"
    id = IntegerField(primary_key=True, auto_increment=True)
    location = PointField(spatial_index=False)


class SpatialPlainSite(ORM):
    """No PointField at all — proves the spatial paths stay inert."""

    table_name = "spatial_plain_site"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


@pytest.fixture()
def gis_db():
    """A real PostGIS connection with the test tables freshly created."""
    previous = orm_model._database
    connection = Database(POSTGIS_URL)
    for table in ("spatial_site", "spatial_no_index_site", "spatial_plain_site"):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.commit()
    bind_database(connection)
    assert SpatialSite.create_table() is True
    yield connection
    for table in ("spatial_site", "spatial_no_index_site", "spatial_plain_site"):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.commit()
    connection.close()
    orm_model._database = previous


@pytest.fixture()
def seeded_db(gis_db):
    """Three known cities inserted through the ORM write path."""
    assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()
    assert SpatialSite({"name": "Johannesburg", "location": JOHANNESBURG}).save()
    assert SpatialSite({"name": "Durban", "location": DURBAN}).save()
    return gis_db


def _names(result) -> list[str]:
    """Row names in result order (works for DatabaseResult and model lists)."""
    return [
        row["name"] if isinstance(row, dict) else row.name
        for row in (result.records if hasattr(result, "records") else result)
    ]


def _ids(result) -> list[int]:
    """Row ids in result order — what a pagination check compares."""
    return [
        row["id"] if isinstance(row, dict) else row.id
        for row in (result.records if hasattr(result, "records") else result)
    ]


def _metres(db, first, second) -> float:
    """Ask the REAL engine for the geodesic distance between two (lon, lat) pairs.

    Used to re-derive a pinned fixture inside a test so the committed constant
    is checked against the engine rather than trusted.
    """
    row = db.fetch_one(
        "SELECT ST_Distance("
        "ST_SetSRID(ST_MakePoint(?, ?), 4326)::geography, "
        "ST_SetSRID(ST_MakePoint(?, ?), 4326)::geography) AS m",
        [first[0], first[1], second[0], second[1]],
    )
    return row["m"]


def _explain_nodes(db, builder) -> list[dict]:
    """Flatten the REAL PostgreSQL plan for a builder's query into a node list.

    ``EXPLAIN (FORMAT JSON)`` returns one row holding the whole plan tree, so a
    single ``fetch_one`` gets it without the pagination wrapper ``fetch()``
    would put around a bare EXPLAIN. Walking the tree (rather than looking only
    at the root) is what makes the assertion robust: PostgreSQL may answer the
    same predicate with a plain ``Index Scan`` or with a
    ``Bitmap Heap Scan`` -> ``Bitmap Index Scan`` pair.
    """
    row = db.fetch_one(
        "EXPLAIN (FORMAT JSON) " + builder.to_sql(), builder._all_params() or None
    )
    plan = row["QUERY PLAN"]
    if isinstance(plan, str):
        plan = json.loads(plan)
    nodes, stack = [], [plan[0]["Plan"]]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(node.get("Plans", []))
    return nodes


# ══════════════════════════════════════════════════════════════════
# Point value object — pure logic, no dependency, no double
# ══════════════════════════════════════════════════════════════════


class TestPointValueObject:
    def test_lon_lat_srid_defaults_to_4326(self):
        point = Point(*CAPE_TOWN)
        assert point.lon == 18.4241
        assert point.lat == -33.9249
        assert point.srid == 4326

    def test_wkt_is_lon_then_lat(self):
        assert Point(*CAPE_TOWN).wkt == "POINT(18.4241 -33.9249)"

    def test_ewkt_carries_the_srid(self):
        assert Point(*CAPE_TOWN).ewkt == "SRID=4326;POINT(18.4241 -33.9249)"

    def test_geojson_shape_is_rfc7946(self):
        assert Point(*CAPE_TOWN).geojson == {
            "type": "Point",
            "coordinates": [18.4241, -33.9249],
        }

    def test_whole_number_coordinates_do_not_gain_a_trailing_zero(self):
        assert Point(18, -34).wkt == "POINT(18 -34)"

    def test_custom_srid_is_kept(self):
        point = Point(100000, 200000, srid=3857)
        assert point.srid == 3857
        assert point.ewkt.startswith("SRID=3857;")

    def test_is_immutable(self):
        point = Point(*CAPE_TOWN)
        with pytest.raises(AttributeError, match="immutable"):
            point.lon = 0.0

    def test_unpacks_as_lon_lat(self):
        lon, lat = Point(*CAPE_TOWN)
        assert (lon, lat) == CAPE_TOWN
        assert tuple(Point(*CAPE_TOWN)) == CAPE_TOWN

    def test_equality_against_point_and_tuple(self):
        assert Point(*CAPE_TOWN) == Point(*CAPE_TOWN)
        assert Point(*CAPE_TOWN) == CAPE_TOWN
        assert Point(*CAPE_TOWN) != Point(*DURBAN)

    def test_different_srid_is_not_equal(self):
        assert Point(10, 20) != Point(10, 20, srid=3857)

    # ── negative ──

    def test_out_of_range_longitude_is_rejected(self):
        with pytest.raises(ValueError, match="longitude 200.0 is out of range"):
            Point(200.0, 0.0)

    def test_out_of_range_latitude_is_rejected(self):
        with pytest.raises(ValueError, match="latitude -100.0 is out of range"):
            Point(0.0, -100.0)

    def test_swapped_lat_lon_is_caught_with_a_hint(self):
        # -33.9249, 18.4241 reversed is in range, but 151.2, -33.8 reversed is
        # not — the common Sydney mistake. The message must name the order.
        with pytest.raises(ValueError, match=r"did you pass\s+latitude first\?"):
            Point(-33.8688, 151.2093)

    def test_projected_srid_skips_the_degree_range_check(self):
        # A metre-based SRID legitimately exceeds 180 — validating there
        # would reject valid data.
        assert Point(2_000_000, 5_000_000, srid=3857).lon == 2_000_000

    def test_non_numeric_coordinates_are_rejected(self):
        with pytest.raises(ValueError, match="must be numbers"):
            Point("here", "there")


class TestPointParse:
    def test_parses_a_tuple(self):
        assert Point.parse(CAPE_TOWN) == Point(*CAPE_TOWN)

    def test_parses_a_list(self):
        assert Point.parse([18.4241, -33.9249]) == Point(*CAPE_TOWN)

    def test_parses_wkt(self):
        assert Point.parse("POINT(18.4241 -33.9249)") == Point(*CAPE_TOWN)

    def test_parses_wkt_case_insensitively_with_extra_space(self):
        assert Point.parse("  point ( 18.4241   -33.9249 )  ") == Point(*CAPE_TOWN)

    def test_parses_ewkt_and_takes_its_srid(self):
        point = Point.parse("SRID=3857;POINT(100000 200000)")
        assert point.srid == 3857
        assert point.lon == 100000

    def test_parses_geojson(self):
        assert Point.parse(
            {"type": "Point", "coordinates": [18.4241, -33.9249]}
        ) == Point(*CAPE_TOWN)

    def test_parses_a_geojson_feature_wrapper(self):
        assert Point.parse(
            {
                "type": "Feature",
                "properties": {"name": "Cape Town"},
                "geometry": {"type": "Point", "coordinates": [18.4241, -33.9249]},
            }
        ) == Point(*CAPE_TOWN)

    def test_parses_hexewkb_as_postgis_returns_it(self):
        point = Point.parse(CAPE_TOWN_HEXEWKB)
        assert round(point.lon, 4) == 18.4241
        assert round(point.lat, 4) == -33.9249
        assert point.srid == 4326

    def test_parses_hexewkb_supplied_as_ascii_bytes(self):
        point = Point.parse(CAPE_TOWN_HEXEWKB.encode())
        assert round(point.lon, 4) == 18.4241

    def test_parses_raw_wkb_bytes(self):
        point = Point.parse(bytes.fromhex(CAPE_TOWN_HEXEWKB))
        assert round(point.lat, 4) == -33.9249

    def test_a_point_passes_through_unchanged(self):
        point = Point(*CAPE_TOWN)
        assert Point.parse(point) is point

    def test_wkt_z_keeps_the_first_two_ordinates(self):
        assert Point.parse("POINT Z (18.4241 -33.9249 1000)") == Point(*CAPE_TOWN)

    # ── negative ──

    def test_garbage_string_is_rejected_naming_the_supported_forms(self):
        with pytest.raises(ValueError, match="cannot read"):
            Point.parse("somewhere near the shops")

    def test_a_polygon_is_rejected(self):
        with pytest.raises(ValueError, match="cannot read"):
            Point.parse("POLYGON((0 0, 1 0, 1 1, 0 0))")

    def test_geojson_of_the_wrong_type_is_rejected(self):
        with pytest.raises(ValueError, match="must be 'Point'"):
            Point.parse({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})

    def test_geojson_without_coordinates_is_rejected(self):
        with pytest.raises(ValueError, match="coordinates"):
            Point.parse({"type": "Point"})

    def test_one_element_tuple_is_rejected(self):
        with pytest.raises(ValueError, match="needs 2 values"):
            Point.parse((18.4241,))

    def test_unsupported_type_is_rejected(self):
        with pytest.raises(ValueError, match="unsupported type int"):
            Point.parse(42)

    def test_non_point_wkb_is_rejected(self):
        # A LINESTRING EWKB (type 2) must not be silently read as a point.
        linestring = "0102000020E610000002000000" + "00" * 32
        with pytest.raises(ValueError, match="is not a Point"):
            Point.parse(linestring)


# ══════════════════════════════════════════════════════════════════
# PointField — pure logic
# ══════════════════════════════════════════════════════════════════


class TestPointField:
    def test_validate_normalises_every_input_shape_to_point(self):
        field = PointField()
        field.name = "location"
        for value in (
            CAPE_TOWN,
            "POINT(18.4241 -33.9249)",
            "SRID=4326;POINT(18.4241 -33.9249)",
            {"type": "Point", "coordinates": [18.4241, -33.9249]},
        ):
            assert field.validate(value) == Point(*CAPE_TOWN)

    def test_to_db_emits_ewkt(self):
        field = PointField()
        field.name = "location"
        assert field.to_db(Point(*CAPE_TOWN)) == "SRID=4326;POINT(18.4241 -33.9249)"

    def test_to_db_accepts_an_uncoerced_value(self):
        field = PointField()
        field.name = "location"
        assert field.to_db(CAPE_TOWN) == "SRID=4326;POINT(18.4241 -33.9249)"

    def test_none_round_trips_as_none(self):
        field = PointField()
        field.name = "location"
        assert field.validate(None) is None
        assert field.to_db(None) is None

    def test_custom_srid_flows_into_to_db(self):
        field = PointField(srid=3857)
        field.name = "location"
        assert field.to_db((100000, 200000)) == "SRID=3857;POINT(100000 200000)"

    def test_default_is_coerced_to_a_point(self):
        field = PointField(default=CAPE_TOWN)
        field.name = "location"
        assert field.validate(None) == Point(*CAPE_TOWN)

    def test_kind_and_srid_are_introspectable(self):
        field = PointField()
        assert field.kind == "PointField"
        assert field.srid == 4326
        assert field.spatial_index is True

    # ── negative ──

    def test_required_field_rejects_none_naming_the_field(self):
        field = PointField(required=True)
        field.name = "location"
        with pytest.raises(ValueError, match="Field 'location' is required"):
            field.validate(None)

    def test_bad_value_error_names_the_field(self):
        field = PointField()
        field.name = "location"
        with pytest.raises(ValueError, match="Field 'location': "):
            field.validate("not a point")

    def test_model_metaclass_records_spatial_fields(self):
        assert SpatialSite._spatial_fields == ("location",)
        assert SpatialPlainSite._spatial_fields == ()


# ══════════════════════════════════════════════════════════════════
# SQLTranslator — the per-engine dialect seam
# ══════════════════════════════════════════════════════════════════


class TestSpatialDialect:
    def test_postgres_and_postgresql_both_support_spatial(self):
        assert SQLTranslator.supports_spatial("postgresql") is True
        assert SQLTranslator.supports_spatial("postgres") is True

    def test_point_column_type_is_geography_with_the_srid(self):
        assert SQLTranslator.point_column_type("postgresql") == "geography(Point,4326)"
        assert (
            SQLTranslator.point_column_type("postgresql", 3857)
            == "geography(Point,3857)"
        )

    def test_spatial_index_is_gist_and_idempotent(self):
        sql = SQLTranslator.spatial_index("postgresql", "spatial_site", "location")
        assert "USING GIST (location)" in sql
        assert "IF NOT EXISTS" in sql

    def test_within_distance_fragment_is_st_dwithin_with_three_placeholders(self):
        sql = SQLTranslator.within_distance("postgresql", "location")
        assert sql == (
            "ST_DWithin(location, ST_SetSRID(ST_MakePoint(?, ?), 4326)::geography, ?)"
        )

    def test_distance_fragment_is_st_distance_with_two_placeholders(self):
        sql = SQLTranslator.distance("postgresql", "location")
        assert sql == (
            "ST_Distance(location, ST_SetSRID(ST_MakePoint(?, ?), 4326)::geography)"
        )

    # ── negative: unsupported engines must be named, never guessed ──

    @pytest.mark.parametrize("engine", ["sqlite", "mysql", "mssql", "firebird", "odbc"])
    def test_unsupported_engine_raises_naming_the_engine(self, engine):
        with pytest.raises(SpatialNotSupportedError) as excinfo:
            SQLTranslator.point_column_type(engine)
        message = str(excinfo.value)
        assert f"'{engine}'" in message
        assert "PointField" in message
        assert "PostGIS" in message

    def test_unsupported_engine_message_names_the_attempted_feature(self):
        with pytest.raises(SpatialNotSupportedError, match=r"within_distance\(\)"):
            SQLTranslator.within_distance("sqlite", "location")
        with pytest.raises(SpatialNotSupportedError, match=r"order_by_distance\(\)"):
            SQLTranslator.distance("sqlite", "location")

    def test_spatial_error_is_catchable_as_notimplementederror(self):
        with pytest.raises(NotImplementedError):
            SQLTranslator.point_column_type("sqlite")

    def test_unknown_engine_still_names_itself(self):
        with pytest.raises(SpatialNotSupportedError, match="'unknown'"):
            SQLTranslator.point_column_type("")

    # ── negative: identifiers are validated, never trusted ──

    @pytest.mark.parametrize(
        "column",
        [
            "location); DROP TABLE spatial_site; --",
            "location, (SELECT password FROM users)",
            "location'",
            "1=1",
            "",
        ],
    )
    def test_hostile_column_name_is_refused(self, column):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SQLTranslator.within_distance("postgresql", column)

    def test_hostile_table_name_is_refused(self):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SQLTranslator.spatial_index("postgresql", "t; DROP TABLE x", "location")

    def test_non_numeric_srid_is_refused(self):
        with pytest.raises(ValueError, match="SRID must be an integer"):
            SQLTranslator.point_column_type("postgresql", "4326); DROP TABLE x --")


# ══════════════════════════════════════════════════════════════════
# QueryBuilder — SQL shape + parameterisation (no DB needed)
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestQueryBuilderSpatialSql:
    """SQL shape + parameterisation, built against the REAL PostGIS connection.

    Nothing is stubbed: the builder gets the live connection so it resolves the
    engine for real; these particular assertions just inspect the generated SQL
    instead of executing it (the execution assertions live further down).
    """

    def test_within_distance_binds_lon_lat_metres_in_order(self, gis_db):
        builder = QueryBuilder.from_table("spatial_site", gis_db)
        builder.within_distance("location", CAPE_TOWN, 5000)
        assert "ST_DWithin(location," in builder.to_sql()
        assert builder._params == [18.4241, -33.9249, 5000.0]

    def test_order_by_distance_params_come_after_where_params(self, gis_db):
        builder = (
            QueryBuilder.from_table("spatial_site", gis_db)
            .where("name = ?", ["Cape Town"])
            .order_by_distance("location", JOHANNESBURG)
        )
        sql = builder.to_sql()
        # Clause order in the SQL must match the bound-value order.
        assert sql.index("WHERE") < sql.index("ORDER BY")
        assert builder._all_params() == ["Cape Town", 28.0473, -26.2041]

    def test_descending_order_by_distance_appends_desc(self, gis_db):
        builder = QueryBuilder.from_table(
            "spatial_site", gis_db
        ).order_by_distance("location", CAPE_TOWN, descending=True)
        assert builder.to_sql().rstrip().endswith("DESC")

    def test_no_coordinate_is_ever_interpolated_into_the_sql(self, gis_db):
        builder = (
            QueryBuilder.from_table("spatial_site", gis_db)
            .within_distance("location", CAPE_TOWN, 5000)
            .order_by_distance("location", CAPE_TOWN)
        )
        sql = builder.to_sql()
        for literal in ("18.4241", "-33.9249", "5000"):
            assert literal not in sql, f"{literal!r} was interpolated into the SQL"
        assert sql.count("?") == 5  # lon, lat, metres, then lon, lat

    def test_accepts_the_same_point_shapes_as_the_field(self, gis_db):
        for value in (
            CAPE_TOWN,
            Point(*CAPE_TOWN),
            "POINT(18.4241 -33.9249)",
            {"type": "Point", "coordinates": [18.4241, -33.9249]},
        ):
            builder = QueryBuilder.from_table("spatial_site", gis_db)
            builder.within_distance("location", value, 100)
            assert builder._params[:2] == [18.4241, -33.9249]

    # ── negative: injection through the VALUE path ──

    def test_hostile_point_value_cannot_reach_the_sql(self, gis_db):
        builder = QueryBuilder.from_table("spatial_site", gis_db)
        with pytest.raises(ValueError, match="cannot read"):
            builder.within_distance(
                "location", "POINT(0 0)); DROP TABLE spatial_site; --", 100
            )
        # Nothing was appended — the builder is untouched.
        assert builder._wheres == []
        assert builder._params == []

    def test_hostile_metres_value_cannot_reach_the_sql(self, gis_db):
        builder = QueryBuilder.from_table("spatial_site", gis_db)
        with pytest.raises(ValueError):
            builder.within_distance("location", CAPE_TOWN, "100); DROP TABLE x --")
        assert builder._wheres == []

    def test_hostile_column_name_is_refused_by_the_builder(self, gis_db):
        builder = QueryBuilder.from_table("spatial_site", gis_db)
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            builder.within_distance("location); DROP TABLE spatial_site; --", CAPE_TOWN, 100)
        assert builder._wheres == []

    def test_a_builder_with_no_connection_fails_before_building_spatial_sql(self):
        # A spatial predicate must know the engine to pick a dialect, so with no
        # connection at all it fails with the builder's existing message rather
        # than guessing a dialect. The ORM global is cleared for the duration
        # because _ensure_db() legitimately falls back to it.
        previous = orm_model._database
        orm_model._database = None
        try:
            builder = QueryBuilder.from_table("spatial_site")
            with pytest.raises(RuntimeError, match="No database connection"):
                builder.within_distance("location", CAPE_TOWN, 100)
        finally:
            orm_model._database = previous


class TestQueryBuilderSpatialOnSqlite:
    """A real SQLite file: a spatial predicate must refuse to build, naming the
    engine, rather than emitting SQL SQLite cannot run."""

    def test_within_distance_raises_at_the_call_site(self, tmp_path):
        connection = Database(f"sqlite:///{tmp_path / 'qb.db'}")
        try:
            builder = QueryBuilder.from_table("spatial_site", connection)
            with pytest.raises(SpatialNotSupportedError, match="'sqlite'"):
                builder.within_distance("location", CAPE_TOWN, 100)
        finally:
            connection.close()

    def test_order_by_distance_raises_at_the_call_site(self, tmp_path):
        connection = Database(f"sqlite:///{tmp_path / 'qb2.db'}")
        try:
            builder = QueryBuilder.from_table("spatial_site", connection)
            with pytest.raises(SpatialNotSupportedError, match="'sqlite'"):
                builder.order_by_distance("location", CAPE_TOWN)
        finally:
            connection.close()

    def test_a_non_spatial_query_on_sqlite_is_unaffected(self, tmp_path):
        connection = Database(f"sqlite:///{tmp_path / 'qb3.db'}")
        try:
            connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO t (name) VALUES ('a')")
            connection.commit()
            builder = QueryBuilder.from_table("t", connection).order_by("name")
            assert builder.count() == 1
            assert len(builder.get().records) == 1
        finally:
            connection.close()


# ══════════════════════════════════════════════════════════════════
# NEGATIVE: real SQLite must refuse a PointField, loudly
# ══════════════════════════════════════════════════════════════════


class TestSqliteRefusesSpatial:
    """A real SQLite file — not a stub. The point is that DDL must FAIL rather
    than create a TEXT column that silently accepts points and can never be
    queried spatially."""

    def test_create_table_raises_naming_sqlite(self, tmp_path):
        previous = orm_model._database
        connection = Database(f"sqlite:///{tmp_path / 'spatial.db'}")
        bind_database(connection)
        try:
            with pytest.raises(SpatialNotSupportedError) as excinfo:
                SpatialSite.create_table()
            message = str(excinfo.value)
            assert "'sqlite'" in message
            assert "PointField" in message
            assert "PostGIS" in message
            assert "FloatField" in message  # names the actionable alternative
            # And it did NOT silently create a wrong table.
            assert connection.table_exists("spatial_site") is False
        finally:
            connection.close()
            orm_model._database = previous

    def test_raises_even_when_the_table_already_exists(self, tmp_path):
        # The error must not depend on table state — a hand-made table with a
        # TEXT column is exactly the silent-wrong-column case we refuse.
        previous = orm_model._database
        connection = Database(f"sqlite:///{tmp_path / 'spatial2.db'}")
        connection.execute(
            "CREATE TABLE spatial_site (id INTEGER PRIMARY KEY, name TEXT, location TEXT)"
        )
        connection.commit()
        bind_database(connection)
        try:
            assert connection.table_exists("spatial_site") is True
            with pytest.raises(SpatialNotSupportedError, match="'sqlite'"):
                SpatialSite.create_table()
        finally:
            connection.close()
            orm_model._database = previous

    def test_a_model_without_a_pointfield_still_works_on_sqlite(self, tmp_path):
        # The spatial branches must stay completely inert for everyone else.
        previous = orm_model._database
        connection = Database(f"sqlite:///{tmp_path / 'plain.db'}")
        bind_database(connection)
        try:
            assert SpatialPlainSite.create_table() is True
            assert connection.table_exists("spatial_plain_site") is True
            assert SpatialPlainSite({"name": "Anywhere"}).save()
            assert SpatialPlainSite.count() == 1
        finally:
            connection.close()
            orm_model._database = previous


# ══════════════════════════════════════════════════════════════════
# REAL PostGIS — DDL
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestPostgisDdl:
    def test_column_is_geography_point_4326(self, gis_db):
        row = gis_db.fetch_one(
            "SELECT type, srid, coord_dimension FROM geography_columns "
            "WHERE f_table_name = ? AND f_geography_column = ?",
            ["spatial_site", "location"],
        )
        assert row is not None, "location is not registered as a geography column"
        assert row["type"] == "Point"
        assert row["srid"] == 4326
        assert row["coord_dimension"] == 2

    def test_gist_index_is_created(self, gis_db):
        row = gis_db.fetch_one(
            "SELECT indexdef FROM pg_indexes WHERE tablename = ? AND indexname = ?",
            ["spatial_site", "spatial_site_location_gist"],
        )
        assert row is not None, "the GiST spatial index was not created"
        assert "gist" in row["indexdef"].lower()

    def test_create_table_is_idempotent(self, gis_db):
        assert SpatialSite.create_table() is True

    def test_spatial_index_false_creates_the_column_without_an_index(self, gis_db):
        assert SpatialNoIndexSite.create_table() is True
        row = gis_db.fetch_one(
            "SELECT type FROM geography_columns WHERE f_table_name = ?",
            ["spatial_no_index_site"],
        )
        assert row is not None and row["type"] == "Point"
        indexes = gis_db.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = ?",
            ["spatial_no_index_site"],
        )
        assert not any(
            "gist" in r["indexname"] for r in indexes.records
        ), "spatial_index=False still created a spatial index"


# ══════════════════════════════════════════════════════════════════
# REAL PostGIS — round-trip
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestPostgisRoundTrip:
    @pytest.mark.parametrize(
        "assigned",
        [
            CAPE_TOWN,
            [18.4241, -33.9249],
            "POINT(18.4241 -33.9249)",
            "SRID=4326;POINT(18.4241 -33.9249)",
            {"type": "Point", "coordinates": [18.4241, -33.9249]},
        ],
        ids=["tuple", "list", "wkt", "ewkt", "geojson"],
    )
    def test_every_input_shape_survives_save_and_reload(self, gis_db, assigned):
        site = SpatialSite({"name": "Cape Town", "location": assigned})
        assert site.save()
        loaded = SpatialSite.find(site.id)
        assert isinstance(loaded.location, Point)
        assert round(loaded.location.lon, 6) == 18.4241
        assert round(loaded.location.lat, 6) == -33.9249
        assert loaded.location.srid == 4326

    def test_update_rewrites_the_point(self, gis_db):
        site = SpatialSite({"name": "Moving", "location": CAPE_TOWN})
        assert site.save()
        site.location = DURBAN
        assert site.save()
        reloaded = SpatialSite.find(site.id)
        assert round(reloaded.location.lon, 4) == 31.0218
        assert round(reloaded.location.lat, 4) == -29.8587

    def test_a_null_point_round_trips_as_none(self, gis_db):
        site = SpatialSite({"name": "Nowhere", "location": None})
        assert site.save()
        assert SpatialSite.find(site.id).location is None

    def test_all_and_where_hydrate_points(self, gis_db):
        SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()
        SpatialSite({"name": "Durban", "location": DURBAN}).save()
        for site in SpatialSite.all():
            assert isinstance(site.location, Point)
        found = SpatialSite.where("name = ?", ["Durban"])
        assert len(found) == 1
        assert round(found[0].location.lat, 4) == -29.8587

    def test_the_stored_value_is_really_a_geography_not_text(self, gis_db):
        # Proves to_db()'s EWKT was coerced by the engine, not stored verbatim.
        SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()
        row = gis_db.fetch_one(
            "SELECT ST_AsText(location) AS wkt, ST_SRID(location) AS srid "
            "FROM spatial_site WHERE name = ?",
            ["Cape Town"],
        )
        assert row["wkt"] == "POINT(18.4241 -33.9249)"
        assert row["srid"] == 4326

    def test_a_bad_point_is_refused_before_it_reaches_the_database(self, gis_db):
        with pytest.raises(ValueError, match="Field 'location'"):
            SpatialSite({"name": "Bad", "location": "over there somewhere"})
        assert SpatialSite.count() == 0


# ══════════════════════════════════════════════════════════════════
# REAL PostGIS — spatial predicates with known-answer distances
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestPostgisSpatialQueries:
    def test_known_distances_match_the_fixtures(self, seeded_db):
        # Anchors the radii below to real geodesic metres, so a wrong-units
        # regression (degrees, or geometry instead of geography) fails here.
        row = seeded_db.fetch_one(
            "SELECT ST_Distance("
            "  (SELECT location FROM spatial_site WHERE name = 'Cape Town'),"
            "  (SELECT location FROM spatial_site WHERE name = 'Johannesburg')"
            ") AS metres"
        )
        assert round(row["metres"], 2) == CPT_TO_JNB_METRES

    def test_within_distance_returns_exactly_the_expected_subset(self, seeded_db):
        # 600 km of Johannesburg: JNB (0 m) and Durban (499 521 m) are in,
        # Cape Town (1 261 119 m) is out.
        result = (
            SpatialSite.query()
            .within_distance("location", JOHANNESBURG, 600_000)
            .get()
        )
        assert sorted(_names(result)) == ["Durban", "Johannesburg"]

    def test_a_tighter_radius_excludes_durban(self, seeded_db):
        result = (
            SpatialSite.query()
            .within_distance("location", JOHANNESBURG, 100_000)
            .get()
        )
        assert _names(result) == ["Johannesburg"]

    def test_a_radius_just_inside_the_known_distance_excludes_it(self, seeded_db):
        # 499 521.49 m apart: 499 000 excludes Durban, 500 000 includes it.
        # A wrong-units bug cannot pass both of these.
        tight = SpatialSite.query().within_distance("location", JOHANNESBURG, 499_000).get()
        wide = SpatialSite.query().within_distance("location", JOHANNESBURG, 500_000).get()
        assert _names(tight) == ["Johannesburg"]
        assert sorted(_names(wide)) == ["Durban", "Johannesburg"]

    def test_a_wide_radius_returns_all_three(self, seeded_db):
        result = (
            SpatialSite.query()
            .within_distance("location", JOHANNESBURG, 2_000_000)
            .get()
        )
        assert sorted(_names(result)) == ["Cape Town", "Durban", "Johannesburg"]

    def test_a_radius_that_matches_nothing_returns_no_rows(self, seeded_db):
        result = (
            SpatialSite.query()
            .within_distance("location", (0.0, 0.0), 1_000)
            .get()
        )
        assert _names(result) == []

    def test_order_by_distance_from_cape_town(self, seeded_db):
        # CPT 0 m < JNB 1 261 119 m < DBN 1 273 094 m — only 12 km apart, so a
        # broken ordering shows up immediately.
        result = SpatialSite.query().order_by_distance("location", CAPE_TOWN).get()
        assert _names(result) == ["Cape Town", "Johannesburg", "Durban"]

    def test_order_by_distance_from_johannesburg(self, seeded_db):
        result = SpatialSite.query().order_by_distance("location", JOHANNESBURG).get()
        assert _names(result) == ["Johannesburg", "Durban", "Cape Town"]

    def test_order_by_distance_descending_reverses_it(self, seeded_db):
        result = (
            SpatialSite.query()
            .order_by_distance("location", CAPE_TOWN, descending=True)
            .get()
        )
        assert _names(result) == ["Durban", "Johannesburg", "Cape Town"]

    def test_radius_and_ordering_compose(self, seeded_db):
        result = (
            SpatialSite.query()
            .within_distance("location", JOHANNESBURG, 600_000)
            .order_by_distance("location", JOHANNESBURG)
            .get()
        )
        assert _names(result) == ["Johannesburg", "Durban"]

    def test_composes_with_a_plain_where_and_keeps_param_order(self, seeded_db):
        result = (
            SpatialSite.query()
            .where("name <> ?", ["Johannesburg"])
            .within_distance("location", JOHANNESBURG, 2_000_000)
            .order_by_distance("location", JOHANNESBURG)
            .get()
        )
        assert _names(result) == ["Durban", "Cape Town"]

    def test_limit_gives_nearest_n(self, seeded_db):
        result = (
            SpatialSite.query()
            .order_by_distance("location", DURBAN)
            .limit(2)
            .get()
        )
        assert _names(result) == ["Durban", "Johannesburg"]

    def test_count_works_alongside_distance_ordering(self, seeded_db):
        # Regression: ORDER BY is dropped for the count probe. PostgreSQL
        # rejects a non-aggregated ORDER BY expression next to COUNT(*), so
        # before that fix this raised instead of returning a number.
        builder = (
            SpatialSite.query()
            .within_distance("location", JOHANNESBURG, 600_000)
            .order_by_distance("location", JOHANNESBURG)
        )
        assert builder.count() == 2
        assert builder.exists() is True

    def test_plain_order_by_also_survives_count(self, seeded_db):
        assert SpatialSite.query().order_by("name DESC").count() == 3

    def test_the_distance_can_be_selected_via_raw_sql_and_the_dialect_seam(self, seeded_db):
        # QueryBuilder.select() has no bound-parameter list of its own (a
        # pre-existing limitation, not spatial-specific), so selecting the
        # distance value goes through raw SQL — reusing the same
        # SQLTranslator fragment, still fully parameterised.
        distance_sql = SQLTranslator.distance("postgresql", "location")
        result = seeded_db.fetch(
            f"SELECT name, {distance_sql} AS metres FROM spatial_site "
            f"ORDER BY name",
            [28.0473, -26.2041],
        )
        by_name = {row["name"]: row["metres"] for row in result.records}
        assert round(by_name["Cape Town"], 2) == CPT_TO_JNB_METRES
        assert round(by_name["Durban"], 2) == JNB_TO_DBN_METRES
        assert round(by_name["Johannesburg"], 2) == 0.0

    # ── negative against the real engine ──

    def test_a_hostile_point_value_never_executes_and_leaves_data_intact(self, seeded_db):
        with pytest.raises(ValueError):
            SpatialSite.query().within_distance(
                "location", "POINT(0 0)); DROP TABLE spatial_site; --", 1000
            ).get()
        # The real table is still there with all three rows.
        assert seeded_db.table_exists("spatial_site") is True
        assert SpatialSite.count() == 3

    def test_a_hostile_column_name_never_executes(self, seeded_db):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SpatialSite.query().order_by_distance(
                "location); DROP TABLE spatial_site; --", CAPE_TOWN
            ).get()
        assert seeded_db.table_exists("spatial_site") is True
        assert SpatialSite.count() == 3


# ══════════════════════════════════════════════════════════════════
# REAL PostGIS — GeoJSON output
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestGeoJsonOutput:
    def test_to_dict_emits_a_geojson_point(self, gis_db):
        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        data = SpatialSite.find(site.id).to_dict()
        assert data["location"]["type"] == "Point"
        assert [round(c, 4) for c in data["location"]["coordinates"]] == [18.4241, -33.9249]

    def test_to_dict_keeps_none_as_none(self, gis_db):
        site = SpatialSite({"name": "Nowhere", "location": None})
        assert site.save()
        assert SpatialSite.find(site.id).to_dict()["location"] is None

    def test_to_json_is_valid_json_with_the_geometry_inline(self, gis_db):
        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        payload = json.loads(SpatialSite.find(site.id).to_json())
        assert payload["location"]["type"] == "Point"

    def test_camel_case_output_still_converts_the_point(self, gis_db):
        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        data = SpatialSite.find(site.id).to_dict(case="camel")
        assert data["location"]["type"] == "Point"

    def test_to_feature_shape(self, gis_db):
        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        feature = SpatialSite.find(site.id).to_feature()
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        assert feature["properties"]["name"] == "Cape Town"
        assert "location" not in feature["properties"]
        assert feature["id"] == site.id

    def test_feature_collection_shape(self, seeded_db):
        collection = feature_collection(SpatialSite.all())
        assert collection["type"] == "FeatureCollection"
        assert len(collection["features"]) == 3
        assert {f["properties"]["name"] for f in collection["features"]} == {
            "Cape Town",
            "Johannesburg",
            "Durban",
        }
        for feature in collection["features"]:
            assert feature["geometry"]["type"] == "Point"
            assert len(feature["geometry"]["coordinates"]) == 2

    def test_feature_collection_preserves_query_order(self, seeded_db):
        # Model.select() hydrates models (QueryBuilder.get() returns raw rows),
        # and the coordinates stay bound as parameters here too.
        nearest = SpatialSite.select(
            "SELECT * FROM spatial_site ORDER BY "
            + SQLTranslator.distance("postgresql", "location"),
            [28.0473, -26.2041],
        )
        collection = feature_collection(nearest)
        assert [f["properties"]["name"] for f in collection["features"]] == [
            "Johannesburg",
            "Durban",
            "Cape Town",
        ]

    def test_feature_collection_of_a_single_model(self, gis_db):
        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        collection = feature_collection(SpatialSite.find(site.id))
        assert len(collection["features"]) == 1

    def test_response_serialises_a_model_with_a_geojson_point(self, gis_db):
        from tina4_python.core.response import Response

        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        rendered = Response()(SpatialSite.find(site.id))
        assert rendered.content_type == "application/json"
        payload = json.loads(rendered.content.decode())
        assert set(payload["location"]) == {"type", "coordinates"}
        assert payload["location"]["type"] == "Point"
        longitude, latitude = payload["location"]["coordinates"]
        assert (round(longitude, 4), round(latitude, 4)) == (18.4241, -33.9249)
        # Not the WKT string, and not a stringified Python object.
        assert "POINT" not in rendered.content.decode()

    def test_response_serialises_a_list_of_models_as_a_json_array(self, seeded_db):
        from tina4_python.core.response import Response

        rendered = Response()(SpatialSite.all())
        payload = json.loads(rendered.content.decode())
        assert isinstance(payload, list) and len(payload) == 3
        assert all(row["location"]["type"] == "Point" for row in payload)

    def test_response_serialises_a_feature_collection_dict(self, seeded_db):
        from tina4_python.core.response import Response

        rendered = Response()(feature_collection(SpatialSite.all()))
        payload = json.loads(rendered.content.decode())
        assert payload["type"] == "FeatureCollection"
        assert len(payload["features"]) == 3

    # ── negative ──

    def test_feature_collection_is_empty_for_no_rows(self, gis_db):
        assert feature_collection([]) == {"type": "FeatureCollection", "features": []}
        assert feature_collection(None) == {"type": "FeatureCollection", "features": []}

    def test_to_feature_on_a_model_without_a_pointfield_raises(self, gis_db):
        assert SpatialPlainSite.create_table() is True
        assert SpatialPlainSite({"name": "Anywhere"}).save()
        with pytest.raises(ValueError, match="has no PointField"):
            SpatialPlainSite.all()[0].to_feature()

    def test_to_feature_rejects_a_non_point_geometry_field(self, gis_db):
        site = SpatialSite({"name": "Cape Town", "location": CAPE_TOWN})
        assert site.save()
        with pytest.raises(ValueError, match="is not a PointField"):
            SpatialSite.find(site.id).to_feature(geometry_field="name")

    def test_feature_collection_rejects_raw_row_dicts(self, seeded_db):
        result = SpatialSite.query().get()
        with pytest.raises(TypeError, match="expected ORM model instances"):
            feature_collection(result.records)


# ══════════════════════════════════════════════════════════════════
# A1 — lat/lon swap is DECISIVE (plan/v3/iot-gis-test-plan.md A1)
#
# The single commonest spatial defect: WKT, GeoJSON and ST_MakePoint are all
# (lon, lat), but humans say "lat, long". Both ordinates of a swapped Cape Town
# are individually legal, so no range check catches it — only geography does.
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestLatLonSwapIsDecisive:
    def test_the_swapped_pair_is_not_rejected_by_range_checks(self):
        # This is WHY the swap needs a geographic test: -33.92 is a valid
        # longitude and 18.42 is a valid latitude, so validation cannot help.
        point = Point(*SWAPPED_CAPE_TOWN)
        assert point.lon == -33.9249
        assert point.lat == 18.4241

    def test_the_swap_lands_thousands_of_kilometres_away(self, gis_db):
        # Pinned from PostGIS itself, and re-derived here against the engine so
        # the committed constant is verified rather than trusted.
        measured = _metres(gis_db, CAPE_TOWN, SWAPPED_CAPE_TOWN)
        assert round(measured, 2) == CPT_TO_SWAPPED_CPT_METRES
        assert measured > 8_000_000

    def test_a_swapped_row_is_excluded_by_a_1000km_radius_around_the_real_place(
        self, gis_db
    ):
        assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()
        assert SpatialSite(
            {"name": "swapped Cape Town", "location": SWAPPED_CAPE_TOWN}
        ).save()

        near = SpatialSite.query().within_distance(
            "location", CAPE_TOWN, 1_000_000
        ).get()

        assert _names(near) == ["Cape Town"]

    def test_the_swapped_row_really_is_stored_and_findable_where_it_landed(
        self, gis_db
    ):
        # Proves the exclusion above is "it is somewhere else", not "the insert
        # silently failed" — the row exists, in the Atlantic.
        assert SpatialSite(
            {"name": "swapped Cape Town", "location": SWAPPED_CAPE_TOWN}
        ).save()

        assert SpatialSite.count() == 1
        found = SpatialSite.query().within_distance(
            "location", SWAPPED_CAPE_TOWN, 1_000
        ).get()
        assert _names(found) == ["swapped Cape Town"]

    def test_nothing_silently_reorders_the_pair_on_the_round_trip(self, gis_db):
        # A framework that "helpfully" swapped the pair back would hide the bug
        # in dev and produce different data than the map client sent.
        assert SpatialSite(
            {"name": "swapped Cape Town", "location": SWAPPED_CAPE_TOWN}
        ).save()

        reloaded = SpatialSite.select_one("SELECT * FROM spatial_site")
        assert reloaded.location.lon == SWAPPED_CAPE_TOWN[0]
        assert reloaded.location.lat == SWAPPED_CAPE_TOWN[1]


# ══════════════════════════════════════════════════════════════════
# C2 — a radius is a CIRCLE, not a bounding box
#
# Guards against a later "optimisation" that replaces ST_DWithin with a cheap
# degree box: a box's corners reach further than its inscribed circle, so a
# point at 1.15x the radius on a 38-degree bearing is inside the box and
# outside the circle. Confirmed RED against a real bbox-substituted predicate.
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestRadiusIsACircleNotABoundingBox:
    def test_the_corner_point_is_outside_the_circle(self, gis_db):
        measured = _metres(gis_db, CAPE_TOWN, BBOX_CORNER)
        assert round(measured, 2) == CPT_TO_BBOX_CORNER_METRES
        assert measured > BBOX_CORNER_RADIUS_METRES

    def test_the_corner_point_is_inside_the_bounding_box_of_that_radius(
        self, gis_db
    ):
        # The discriminator: a bbox implementation WOULD return this row.
        # Asserted against the real engine through the real bbox() predicate.
        assert SpatialSite({"name": "corner", "location": BBOX_CORNER}).save()

        inside_box = SpatialSite.query().bbox("location", *NAIVE_DEGREE_BBOX).get()

        assert _names(inside_box) == ["corner"]

    def test_within_distance_excludes_the_corner_point(self, gis_db):
        assert SpatialSite({"name": "corner", "location": BBOX_CORNER}).save()
        assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()

        near = SpatialSite.query().within_distance(
            "location", CAPE_TOWN, BBOX_CORNER_RADIUS_METRES
        ).get()

        assert _names(near) == ["Cape Town"]

    def test_a_point_on_the_same_bearing_but_inside_the_radius_is_included(
        self, gis_db
    ):
        # Positive control: the exclusion above is distance, not bearing.
        row = gis_db.fetch_one(
            "SELECT ST_X(p::geometry) AS lon, ST_Y(p::geometry) AS lat FROM ("
            "SELECT ST_Project(ST_SetSRID(ST_MakePoint(?, ?), 4326)::geography, "
            "?, radians(38))::geography AS p) t",
            [CAPE_TOWN[0], CAPE_TOWN[1], BBOX_CORNER_RADIUS_METRES * 0.5],
        )
        assert SpatialSite(
            {"name": "half way", "location": (row["lon"], row["lat"])}
        ).save()

        near = SpatialSite.query().within_distance(
            "location", CAPE_TOWN, BBOX_CORNER_RADIUS_METRES
        ).get()

        assert _names(near) == ["half way"]


# ══════════════════════════════════════════════════════════════════
# C4 — the antimeridian is not the long way round
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestAntimeridian:
    def test_the_crossing_is_about_22km_not_40000km(self, gis_db):
        measured = _metres(gis_db, ANTIMERIDIAN_EAST, ANTIMERIDIAN_WEST)
        assert round(measured, 2) == ANTIMERIDIAN_CROSSING_METRES
        # Planar maths on the raw longitudes would give ~359.8 degrees of arc,
        # i.e. ~40 000 km. Two orders of magnitude of headroom either side.
        assert 20_000 < measured < 25_000

    def test_a_50km_radius_on_one_side_finds_the_row_on_the_other(self, gis_db):
        assert SpatialSite({"name": "east", "location": ANTIMERIDIAN_EAST}).save()
        assert SpatialSite({"name": "west", "location": ANTIMERIDIAN_WEST}).save()

        near = SpatialSite.query().within_distance(
            "location", ANTIMERIDIAN_EAST, 50_000
        ).order_by_distance("location", ANTIMERIDIAN_EAST).get()

        assert _names(near) == ["east", "west"]

    def test_a_10km_radius_does_not_reach_across(self, gis_db):
        assert SpatialSite({"name": "east", "location": ANTIMERIDIAN_EAST}).save()
        assert SpatialSite({"name": "west", "location": ANTIMERIDIAN_WEST}).save()

        near = SpatialSite.query().within_distance(
            "location", ANTIMERIDIAN_EAST, 10_000
        ).get()

        assert _names(near) == ["east"]

    def test_select_distance_reports_the_short_way_round(self, gis_db):
        assert SpatialSite({"name": "west", "location": ANTIMERIDIAN_WEST}).save()

        row = (
            SpatialSite.query()
            .select_distance("location", ANTIMERIDIAN_EAST)
            .first()
        )

        assert round(row["metres"], 2) == ANTIMERIDIAN_CROSSING_METRES


# ══════════════════════════════════════════════════════════════════
# C5 — polar points do not blow up
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestPolarPoints:
    def test_distance_from_cape_town_to_a_near_polar_point_is_finite(self, gis_db):
        measured = _metres(gis_db, CAPE_TOWN, NORTH_POLE)
        assert round(measured, 2) == CPT_TO_NORTH_POLE_METRES
        # Half the meridian circumference is ~20 004 km — the hard ceiling for
        # any two points on Earth. A projection blowup exceeds it or returns inf.
        assert 0 < measured < 20_100_000

    def test_two_near_polar_points_on_opposite_meridians_are_metres_apart(
        self, gis_db
    ):
        # 0.001 degrees from the pole on opposite meridians: the great-circle
        # path goes OVER the pole, ~223 m. Planar longitude maths would call
        # this 180 degrees of separation.
        measured = _metres(gis_db, NORTH_POLE, NORTH_POLE_OPPOSITE_MERIDIAN)
        assert round(measured, 2) == ACROSS_THE_NORTH_POLE_METRES
        assert 200 < measured < 250

    def test_a_radius_at_the_pole_finds_polar_rows_and_nothing_else(self, gis_db):
        assert SpatialSite({"name": "pole", "location": NORTH_POLE}).save()
        assert SpatialSite(
            {"name": "pole other side", "location": NORTH_POLE_OPPOSITE_MERIDIAN}
        ).save()
        assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()

        near = SpatialSite.query().within_distance("location", NORTH_POLE, 1_000).get()

        assert sorted(_names(near)) == ["pole", "pole other side"]

    def test_a_tight_radius_at_the_pole_excludes_the_opposite_meridian(self, gis_db):
        assert SpatialSite({"name": "pole", "location": NORTH_POLE}).save()
        assert SpatialSite(
            {"name": "pole other side", "location": NORTH_POLE_OPPOSITE_MERIDIAN}
        ).save()

        near = SpatialSite.query().within_distance("location", NORTH_POLE, 100).get()

        assert _names(near) == ["pole"]

    def test_ordering_from_the_pole_is_finite_and_correctly_ordered(self, gis_db):
        assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()
        assert SpatialSite({"name": "pole", "location": NORTH_POLE}).save()

        rows = (
            SpatialSite.query()
            .select_distance("location", NORTH_POLE)
            .order_by_distance("location", NORTH_POLE)
            .get()
            .records
        )

        assert [row["name"] for row in rows] == ["pole", "Cape Town"]
        assert rows[0]["metres"] == 0.0
        assert round(rows[1]["metres"], 2) == CPT_TO_NORTH_POLE_METRES

    def test_the_polar_point_round_trips_unchanged(self, gis_db):
        assert SpatialSite({"name": "pole", "location": NORTH_POLE}).save()
        reloaded = SpatialSite.select_one("SELECT * FROM spatial_site")
        assert (reloaded.location.lon, reloaded.location.lat) == NORTH_POLE


# ══════════════════════════════════════════════════════════════════
# B5b — a NULL point is not Null Island (the QUERY side)
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestNullIsNotNullIsland:
    @pytest.fixture()
    def db_with_a_device_without_a_fix(self, gis_db):
        assert SpatialSite({"name": "no fix yet", "location": None}).save()
        assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()
        return gis_db

    def test_a_radius_at_null_island_does_not_return_the_null_row(
        self, db_with_a_device_without_a_fix
    ):
        near = SpatialSite.query().within_distance(
            "location", NULL_ISLAND, 100_000
        ).get()

        assert _names(near) == []

    def test_even_a_whole_earth_radius_does_not_return_the_null_row(
        self, db_with_a_device_without_a_fix
    ):
        # Positive control in the same assertion: the located row IS returned,
        # so the empty result above is NULL semantics, not a broken predicate.
        near = SpatialSite.query().within_distance(
            "location", NULL_ISLAND, 20_100_000
        ).get()

        assert _names(near) == ["Cape Town"]

    def test_the_null_row_is_still_in_the_table(
        self, db_with_a_device_without_a_fix
    ):
        rows = SpatialSite.query().order_by("name").get()
        assert _names(rows) == ["Cape Town", "no fix yet"]
        assert SpatialSite.count() == 2

    def test_distance_ordering_does_not_invent_a_position_for_null(
        self, db_with_a_device_without_a_fix
    ):
        # If NULL were coerced to (0, 0) it would be the NEAREST row to Null
        # Island and sort first. It sorts last, with a NULL distance.
        rows = (
            SpatialSite.query()
            .select_distance("location", NULL_ISLAND)
            .order_by_distance("location", NULL_ISLAND)
            .get()
            .records
        )

        assert [row["name"] for row in rows] == ["Cape Town", "no fix yet"]
        assert rows[1]["metres"] is None

    def test_a_bbox_around_null_island_does_not_return_the_null_row(
        self, db_with_a_device_without_a_fix
    ):
        rows = SpatialSite.query().bbox("location", -1.0, -1.0, 1.0, 1.0).get()
        assert _names(rows) == []

    def test_an_intersects_polygon_over_null_island_does_not_either(
        self, db_with_a_device_without_a_fix
    ):
        rows = SpatialSite.query().intersects(
            "location", "POLYGON((-1 -1, 1 -1, 1 1, -1 1, -1 -1))"
        ).get()
        assert _names(rows) == []


# ══════════════════════════════════════════════════════════════════
# B4 — a mismatched SRID is rejected, never silently reprojected
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestSridMismatchIsRejected:
    def test_the_declared_srid_survives_parsing_rather_than_being_rewritten(self):
        # Tina4 must NOT quietly restamp the geometry as 4326 — that would turn
        # a loud engine rejection into a silently mislocated row.
        point = Point.parse("SRID=4269;POINT(18.4241 -33.9249)")
        assert point.srid == 4269
        assert point.ewkt == "SRID=4269;POINT(18.4241 -33.9249)"

    def test_a_geographic_srid_that_is_not_the_columns_is_refused(self, gis_db):
        site = SpatialSite(
            {"name": "wrong srid", "location": "SRID=4269;POINT(18.4241 -33.9249)"}
        )

        assert site.save() is False

        assert "srid" in (site.last_error or "").lower()
        assert SpatialSite.count() == 0

    def test_a_projected_srid_is_refused_by_the_geography_column(self, gis_db):
        site = SpatialSite(
            {"name": "web mercator", "location": "SRID=3857;POINT(2050000 -4020000)"}
        )

        assert site.save() is False

        assert SpatialSite.count() == 0

    def test_nothing_was_reprojected_and_stored_under_another_name(self, gis_db):
        SpatialSite(
            {"name": "wrong srid", "location": "SRID=4269;POINT(18.4241 -33.9249)"}
        ).save()

        # The classic silent-reprojection failure would leave a row here that a
        # radius query then finds at the "right" place.
        near = SpatialSite.query().within_distance(
            "location", CAPE_TOWN, 1_000_000
        ).get()
        assert _names(near) == []

    def test_the_matching_srid_stores_fine_on_the_same_connection(self, gis_db):
        # Positive control, and it proves the refusal did not poison the
        # connection for the next write.
        SpatialSite(
            {"name": "wrong srid", "location": "SRID=4269;POINT(18.4241 -33.9249)"}
        ).save()

        assert SpatialSite(
            {"name": "Cape Town", "location": "SRID=4326;POINT(18.4241 -33.9249)"}
        ).save()
        assert SpatialSite.count() == 1

    def test_a_model_declaring_a_different_srid_creates_that_column_type(self, gis_db):
        # The column follows the FIELD's srid, so a consistent non-4326 model is
        # not blocked — only a value that disagrees with its own column is.
        assert SQLTranslator.point_column_type("postgresql", 4269) == \
            "geography(Point,4269)"


# ══════════════════════════════════════════════════════════════════
# C3b — distance ordering is DETERMINISTIC for equidistant rows
#
# REAL BUG found here: distance alone is not a total order, and PostgreSQL's
# sort is not stable, so a plain UPDATE elsewhere in the table silently
# re-ordered equidistant rows (measured: [1..12] became [4..12, 1, 2, 3], 20/20
# runs). Paging over that skips rows and repeats others. Fixed by appending the
# primary key as a secondary sort key.
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestDistanceOrderingIsDeterministic:
    TIED_ROWS = 12

    @pytest.fixture()
    def tied_db(self, gis_db):
        """Twelve rows at EXACTLY the same location — an exact distance tie."""
        for index in range(1, self.TIED_ROWS + 1):
            assert SpatialSite(
                {"name": f"tied-{index}", "location": JOHANNESBURG}
            ).save()
        return gis_db

    @staticmethod
    def _shuffle_the_heap(db):
        """Rewrite three rows so MVCC moves them to the end of the heap.

        This is the real-world trigger: any ordinary UPDATE anywhere in the
        table changes the physical scan order, and an unstable sort then
        changes the result order of tied rows.
        """
        db.execute("UPDATE spatial_site SET name = name WHERE id IN (1, 2, 3)")
        db.commit()

    def test_equidistant_rows_keep_their_order_after_the_heap_moves(self, tied_db):
        before = _ids(
            SpatialSite.query().order_by_distance("location", CAPE_TOWN).get()
        )
        self._shuffle_the_heap(tied_db)
        after = _ids(
            SpatialSite.query().order_by_distance("location", CAPE_TOWN).get()
        )

        assert before == list(range(1, self.TIED_ROWS + 1))
        assert after == before

    def test_without_the_tie_break_the_same_query_reorders(self, tied_db):
        # The failure mode this fix closes, demonstrated against the real
        # engine rather than asserted from memory. tie_break=False is the
        # documented opt-out and reproduces the pre-fix SQL exactly.
        def unstable_order():
            return _ids(
                SpatialSite.query()
                .order_by_distance("location", CAPE_TOWN, tie_break=False)
                .get()
            )

        before = unstable_order()
        self._shuffle_the_heap(tied_db)

        assert unstable_order() != before

    def test_paging_over_equidistant_rows_visits_every_row_exactly_once(
        self, tied_db
    ):
        page_size = 5
        seen = []
        for page in range(3):
            rows = (
                SpatialSite.query()
                .order_by_distance("location", CAPE_TOWN)
                .limit(page_size, page * page_size)
                .get()
            )
            seen.extend(_ids(rows))
            # A write between pages is exactly what breaks unstable paging.
            self._shuffle_the_heap(tied_db)

        assert sorted(seen) == list(range(1, self.TIED_ROWS + 1))
        assert len(seen) == len(set(seen))

    def test_the_primary_key_is_the_tie_break_in_the_generated_sql(self, gis_db):
        sql = SpatialSite.query().order_by_distance("location", CAPE_TOWN).to_sql()
        assert sql.rstrip().endswith(", id")

    def test_the_tie_break_binds_no_extra_parameters(self, gis_db):
        builder = SpatialSite.query().order_by_distance("location", CAPE_TOWN)
        assert builder._all_params() == [18.4241, -33.9249]

    def test_descending_reverses_the_tie_break_too(self, tied_db):
        ascending = _ids(
            SpatialSite.query().order_by_distance("location", CAPE_TOWN).get()
        )
        descending = _ids(
            SpatialSite.query()
            .order_by_distance("location", CAPE_TOWN, descending=True)
            .get()
        )

        assert descending == list(reversed(ascending))

    def test_an_explicit_tie_break_column_overrides_the_primary_key(self, tied_db):
        rows = (
            SpatialSite.query()
            .order_by_distance("location", CAPE_TOWN, tie_break="name")
            .get()
        )
        # String order, so tied-10 sorts before tied-2 — proves it is 'name'
        # doing the work and not the primary key.
        assert _names(rows)[:3] == ["tied-1", "tied-10", "tied-11"]

    def test_a_raw_builder_without_a_primary_key_adds_no_tie_break(self, gis_db):
        sql = (
            QueryBuilder.from_table("spatial_site", gis_db)
            .order_by_distance("location", CAPE_TOWN)
            .to_sql()
        )
        assert sql.rstrip().endswith(")")

    def test_a_raw_builder_given_a_primary_key_does_add_one(self, gis_db):
        sql = (
            QueryBuilder.from_table("spatial_site", gis_db, primary_key="id")
            .order_by_distance("location", CAPE_TOWN)
            .to_sql()
        )
        assert sql.rstrip().endswith(", id")

    def test_a_hostile_tie_break_column_is_refused_before_any_sql(self, seeded_db):
        builder = SpatialSite.query()
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            builder.order_by_distance(
                "location", CAPE_TOWN, tie_break="id; DROP TABLE spatial_site --"
            )
        assert seeded_db.table_exists("spatial_site") is True
        assert SpatialSite.count() == 3

    def test_ordering_of_genuinely_different_distances_is_unaffected(self, seeded_db):
        rows = SpatialSite.query().order_by_distance("location", CAPE_TOWN).get()
        assert _names(rows) == ["Cape Town", "Johannesburg", "Durban"]


# ══════════════════════════════════════════════════════════════════
# C7 — the GiST index is ACTUALLY used
#
# Correct results with a sequential scan are invisible to every functional
# test and fatal at scale. Measured on this container over 5 000 rows:
# Index Scan 1.7 ms, Seq Scan 145 ms.
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestSpatialIndexIsUsedByThePlanner:
    GIST_INDEX = "spatial_site_location_gist"

    @pytest.fixture()
    def bulk_db(self, gis_db):
        """5 000 real rows plus ANALYZE — below this the planner seq-scans anyway."""
        gis_db.execute(
            "INSERT INTO spatial_site (name, location) "
            "SELECT 'bulk-' || g, ST_SetSRID(ST_MakePoint("
            "-180 + random() * 360, -85 + random() * 170), 4326)::geography "
            "FROM generate_series(1, 5000) g"
        )
        gis_db.commit()
        gis_db.execute("ANALYZE spatial_site")
        gis_db.commit()
        return gis_db

    @staticmethod
    def _index_names(nodes) -> list[str]:
        return [node["Index Name"] for node in nodes if "Index Name" in node]

    @staticmethod
    def _scanned_sequentially(nodes) -> bool:
        return any(node.get("Node Type") == "Seq Scan" for node in nodes)

    def test_the_index_exists_with_the_name_create_table_gave_it(self, bulk_db):
        row = bulk_db.fetch_one(
            "SELECT indexdef FROM pg_indexes WHERE tablename = ? AND indexname = ?",
            ["spatial_site", self.GIST_INDEX],
        )
        assert row is not None
        assert "USING gist" in row["indexdef"]

    def test_within_distance_is_answered_from_the_gist_index(self, bulk_db):
        builder = SpatialSite.query().within_distance(
            "location", CAPE_TOWN, 100_000
        )

        nodes = _explain_nodes(bulk_db, builder)

        assert self.GIST_INDEX in self._index_names(nodes)
        assert not self._scanned_sequentially(nodes)

    def test_dropping_the_index_falls_back_to_a_sequential_scan(self, bulk_db):
        # The proof the assertion above discriminates: same query, same rows,
        # index gone, and the planner really does change its mind.
        bulk_db.execute(f"DROP INDEX {self.GIST_INDEX}")
        bulk_db.commit()

        builder = SpatialSite.query().within_distance(
            "location", CAPE_TOWN, 100_000
        )
        nodes = _explain_nodes(bulk_db, builder)

        assert self.GIST_INDEX not in self._index_names(nodes)
        assert self._scanned_sequentially(nodes)

    def test_bbox_is_answered_from_the_gist_index(self, bulk_db):
        builder = SpatialSite.query().bbox("location", 17.5, -34.5, 19.5, -33.0)

        nodes = _explain_nodes(bulk_db, builder)

        assert self.GIST_INDEX in self._index_names(nodes)
        assert not self._scanned_sequentially(nodes)

    def test_intersects_is_answered_from_the_gist_index(self, bulk_db):
        builder = SpatialSite.query().intersects(
            "location",
            "POLYGON((17.5 -34.5, 19.5 -34.5, 19.5 -33, 17.5 -33, 17.5 -34.5))",
        )

        nodes = _explain_nodes(bulk_db, builder)

        assert self.GIST_INDEX in self._index_names(nodes)
        assert not self._scanned_sequentially(nodes)

    def test_the_indexed_query_still_returns_the_right_rows(self, bulk_db):
        # An index scan that returns the wrong rows is worse than a seq scan.
        assert SpatialSite({"name": "Cape Town", "location": CAPE_TOWN}).save()

        indexed = _names(
            SpatialSite.query().within_distance("location", CAPE_TOWN, 1_000).get()
        )
        bulk_db.execute(f"DROP INDEX {self.GIST_INDEX}")
        bulk_db.commit()
        unindexed = _names(
            SpatialSite.query().within_distance("location", CAPE_TOWN, 1_000).get()
        )

        assert indexed == unindexed
        assert "Cape Town" in indexed

    def test_a_model_that_opted_out_of_the_index_has_none(self, bulk_db):
        assert SpatialNoIndexSite.create_table() is True
        rows = bulk_db.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = ?",
            ["spatial_no_index_site"],
            0,
        )
        assert not [
            row for row in rows.records if row["indexname"].endswith("_gist")
        ]


# ══════════════════════════════════════════════════════════════════
# B1b — full double precision survives the round trip
# ══════════════════════════════════════════════════════════════════

# 7 decimal places of a degree is ~1.1 cm — the precision a survey-grade GNSS
# fix carries, and the point at which a text round trip starts losing digits.
PRECISE_POINT = (18.4241234, -33.9249876)
ONE_TEN_MILLIONTH_EAST = (18.4241235, -33.9249876)


@postgis_required
class TestFullCoordinatePrecision:
    def test_seven_decimal_places_survive_save_and_reload_exactly(self, gis_db):
        assert SpatialSite({"name": "precise", "location": PRECISE_POINT}).save()

        reloaded = SpatialSite.select_one("SELECT * FROM spatial_site")

        # Numeric identity, not a formatted-string comparison: a string compare
        # would pass even if the value had been rounded and re-rendered.
        assert reloaded.location.lon == PRECISE_POINT[0]
        assert reloaded.location.lat == PRECISE_POINT[1]

    @pytest.mark.parametrize(
        "assigned",
        [
            PRECISE_POINT,
            Point(*PRECISE_POINT),
            "POINT(18.4241234 -33.9249876)",
            "SRID=4326;POINT(18.4241234 -33.9249876)",
            {"type": "Point", "coordinates": [18.4241234, -33.9249876]},
        ],
    )
    def test_every_input_shape_keeps_all_seven_places(self, gis_db, assigned):
        assert SpatialSite({"name": "precise", "location": assigned}).save()

        reloaded = SpatialSite.select_one("SELECT * FROM spatial_site")

        assert (reloaded.location.lon, reloaded.location.lat) == PRECISE_POINT

    def test_a_one_ten_millionth_degree_difference_is_not_rounded_away(self, gis_db):
        assert SpatialSite({"name": "a", "location": PRECISE_POINT}).save()
        assert SpatialSite({"name": "b", "location": ONE_TEN_MILLIONTH_EAST}).save()

        rows = SpatialSite.select("SELECT * FROM spatial_site ORDER BY name")

        assert rows[0].location.lon != rows[1].location.lon
        assert rows[0].location.lon == PRECISE_POINT[0]
        assert rows[1].location.lon == ONE_TEN_MILLIONTH_EAST[0]

    def test_the_engine_agrees_they_are_about_a_centimetre_apart(self, gis_db):
        measured = _metres(gis_db, PRECISE_POINT, ONE_TEN_MILLIONTH_EAST)
        assert 0.0 < measured < 0.02

    def test_the_geojson_output_carries_the_full_precision(self, gis_db):
        assert SpatialSite({"name": "precise", "location": PRECISE_POINT}).save()

        reloaded = SpatialSite.select_one("SELECT * FROM spatial_site")
        geometry = reloaded.to_dict()["location"]

        assert geometry["coordinates"] == [PRECISE_POINT[0], PRECISE_POINT[1]]
        assert json.loads(reloaded.to_json())["location"]["coordinates"] == [
            PRECISE_POINT[0], PRECISE_POINT[1]
        ]

    def test_an_update_to_a_neighbouring_value_is_stored_not_ignored(self, gis_db):
        site = SpatialSite({"name": "precise", "location": PRECISE_POINT})
        assert site.save()

        site.location = ONE_TEN_MILLIONTH_EAST
        assert site.save()

        reloaded = SpatialSite.select_one("SELECT * FROM spatial_site")
        assert reloaded.location.lon == ONE_TEN_MILLIONTH_EAST[0]


# ══════════════════════════════════════════════════════════════════
# geometry_binding — the general-geometry coercion funnel (pure logic)
# ══════════════════════════════════════════════════════════════════


class TestGeometryBinding:
    def test_a_point_becomes_ewkt(self):
        assert geometry_binding(Point(*CAPE_TOWN)) == (
            "SRID=4326;POINT(18.4241 -33.9249)", "ewkt"
        )

    def test_a_tuple_becomes_ewkt(self):
        assert geometry_binding(CAPE_TOWN) == (
            "SRID=4326;POINT(18.4241 -33.9249)", "ewkt"
        )

    def test_plain_wkt_gains_the_srid_so_the_engine_never_guesses(self):
        value, form = geometry_binding("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")
        assert form == "ewkt"
        assert value == "SRID=4326;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"

    def test_ewkt_keeps_its_own_srid(self):
        value, _ = geometry_binding("SRID=4269;POLYGON((0 0, 1 0, 1 1, 0 0))")
        assert value.startswith("SRID=4269;")

    def test_a_custom_srid_is_applied_to_plain_wkt(self):
        value, _ = geometry_binding("LINESTRING(0 0, 1 1)", srid=3857)
        assert value == "SRID=3857;LINESTRING(0 0, 1 1)"

    @pytest.mark.parametrize(
        "wkt",
        [
            "POINT(1 2)",
            "LINESTRING(0 0, 1 1)",
            "POLYGON((0 0, 1 0, 1 1, 0 0))",
            "MULTIPOINT((0 0), (1 1))",
            "MULTILINESTRING((0 0, 1 1))",
            "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)))",
            "GEOMETRYCOLLECTION(POINT(1 2))",
            "POLYGON EMPTY",
            "  polygon ((0 0, 1 0, 1 1, 0 0))  ",
        ],
    )
    def test_every_ogc_geometry_type_is_accepted(self, wkt):
        value, form = geometry_binding(wkt)
        assert form == "ewkt"
        assert value.startswith("SRID=4326;")

    def test_a_geojson_polygon_is_bound_as_json(self):
        polygon = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }
        value, form = geometry_binding(polygon)
        assert form == "geojson"
        assert json.loads(value) == polygon

    def test_a_geojson_feature_is_unwrapped_to_its_geometry(self):
        feature = {
            "type": "Feature",
            "properties": {"name": "zone"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        }
        value, form = geometry_binding(feature)
        assert form == "geojson"
        assert json.loads(value)["type"] == "Polygon"

    def test_a_geojson_geometrycollection_is_accepted(self):
        value, form = geometry_binding(
            {"type": "GeometryCollection",
             "geometries": [{"type": "Point", "coordinates": [1, 2]}]}
        )
        assert form == "geojson"
        assert json.loads(value)["type"] == "GeometryCollection"

    # ── negative ──

    def test_a_bare_csv_string_is_refused(self):
        with pytest.raises(ValueError, match="cannot read"):
            geometry_binding("18.4241,-33.9249")

    def test_an_sql_fragment_is_refused(self):
        with pytest.raises(ValueError, match="cannot read"):
            geometry_binding("1=1 OR TRUE")

    def test_an_unknown_geojson_type_is_refused(self):
        with pytest.raises(ValueError, match="GeoJSON 'type' must be one of"):
            geometry_binding({"type": "Circle", "coordinates": [0, 0]})

    def test_geojson_without_coordinates_is_refused(self):
        with pytest.raises(ValueError, match="'coordinates' must be a list"):
            geometry_binding({"type": "Polygon"})

    def test_a_geometrycollection_without_geometries_is_refused(self):
        with pytest.raises(ValueError, match="'geometries' list"):
            geometry_binding({"type": "GeometryCollection"})

    def test_an_unsupported_type_is_refused_naming_it(self):
        with pytest.raises(ValueError, match="unsupported type int"):
            geometry_binding(42)


# ══════════════════════════════════════════════════════════════════
# New dialect rules — SQL shape only, no DB needed
# ══════════════════════════════════════════════════════════════════


class TestNewSpatialDialectRules:
    def test_distance_as_aliases_the_expression(self):
        sql = SQLTranslator.distance_as("postgresql", "location", "metres")
        assert sql == (
            "ST_Distance(location, ST_SetSRID(ST_MakePoint(?, ?), 4326)"
            "::geography) AS metres"
        )
        assert sql.count("?") == 2

    def test_geometry_literal_ewkt_is_one_placeholder(self):
        assert SQLTranslator.geometry_literal("postgresql", "ewkt") == \
            "ST_GeogFromText(?)"

    def test_geometry_literal_geojson_stamps_the_srid(self):
        assert SQLTranslator.geometry_literal("postgresql", "geojson", 4326) == \
            "ST_SetSRID(ST_GeomFromGeoJSON(?), 4326)::geography"

    def test_intersects_fragment_has_one_placeholder(self):
        sql = SQLTranslator.intersects("postgresql", "location")
        assert sql == "ST_Intersects(location, ST_GeogFromText(?))"

    def test_intersects_geojson_form(self):
        sql = SQLTranslator.intersects("postgresql", "location", "geojson")
        assert "ST_GeomFromGeoJSON(?)" in sql

    def test_bbox_fragment_has_four_placeholders(self):
        sql = SQLTranslator.bbox("postgresql", "location")
        assert sql == (
            "ST_Intersects(location, ST_MakeEnvelope(?, ?, ?, ?, 4326)::geography)"
        )
        assert sql.count("?") == 4

    # ── negative ──

    def test_an_unknown_geometry_form_is_refused(self):
        with pytest.raises(ValueError, match="geometry form"):
            SQLTranslator.geometry_literal("postgresql", "shapefile")

    def test_a_hostile_result_alias_is_refused(self):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SQLTranslator.distance_as(
                "postgresql", "location", "m FROM spatial_site; DROP TABLE x --"
            )

    @pytest.mark.parametrize("rule", ["intersects", "bbox"])
    def test_a_hostile_column_name_is_refused(self, rule):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            getattr(SQLTranslator, rule)("postgresql", "location); DROP TABLE x --")

    @pytest.mark.parametrize("engine", ["sqlite", "mysql", "mssql", "firebird"])
    def test_every_new_rule_refuses_a_non_spatial_engine(self, engine):
        for call in (
            lambda: SQLTranslator.distance_as(engine, "location", "metres"),
            lambda: SQLTranslator.geometry_literal(engine),
            lambda: SQLTranslator.intersects(engine, "location"),
            lambda: SQLTranslator.bbox(engine, "location"),
        ):
            with pytest.raises(SpatialNotSupportedError, match=engine):
                call()

    def test_the_identifier_validator_is_public_for_the_builder(self):
        assert SQLTranslator.identifier("created_at") == "created_at"
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SQLTranslator.identifier("a b")


# ══════════════════════════════════════════════════════════════════
# select_distance() + _select_params — SELECT params bind FIRST
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestSelectDistance:
    def test_the_distance_comes_back_beside_the_row(self, seeded_db):
        rows = (
            SpatialSite.query()
            .select_distance("location", JOHANNESBURG)
            .order_by("name")
            .get()
            .records
        )

        by_name = {row["name"]: row["metres"] for row in rows}
        assert round(by_name["Cape Town"], 2) == CPT_TO_JNB_METRES
        assert round(by_name["Durban"], 2) == JNB_TO_DBN_METRES
        assert by_name["Johannesburg"] == 0.0

    def test_the_row_columns_are_still_there_alongside_it(self, seeded_db):
        row = (
            SpatialSite.query()
            .select_distance("location", CAPE_TOWN)
            .where("name = ?", ["Cape Town"])
            .first()
        )
        assert row["name"] == "Cape Town"
        assert row["id"] is not None
        assert row["metres"] == 0.0

    def test_a_custom_alias_names_the_column(self, seeded_db):
        row = (
            SpatialSite.query()
            .select_distance("location", JOHANNESBURG, alias="distance_m")
            .where("name = ?", ["Durban"])
            .first()
        )
        assert round(row["distance_m"], 2) == JNB_TO_DBN_METRES
        assert "metres" not in row

    def test_it_composes_with_an_explicit_select_list(self, seeded_db):
        row = (
            SpatialSite.query()
            .select("name")
            .select_distance("location", JOHANNESBURG)
            .where("name = ?", ["Durban"])
            .first()
        )
        assert set(row.keys()) == {"name", "metres"}

    def test_select_params_bind_before_where_and_order_by_params(self, seeded_db):
        # THE param-order test. Three clauses, three different bound points, all
        # in one query. If _all_params() were in any other order the string
        # "Durban" and a float would swap places and PostgreSQL would reject
        # `name = <double precision>` outright — and if it did not, the returned
        # metres would be measured from the WRONG point.
        builder = (
            SpatialSite.query()
            .select_distance("location", JOHANNESBURG)
            .where("name = ?", ["Durban"])
            .order_by_distance("location", CAPE_TOWN)
        )

        sql = builder.to_sql()
        assert sql.index("SELECT") < sql.index("WHERE") < sql.index("ORDER BY")
        assert builder._all_params() == [
            28.0473, -26.2041,   # SELECT  — Johannesburg
            "Durban",            # WHERE
            18.4241, -33.9249,   # ORDER BY — Cape Town
        ]

        row = builder.first()
        assert row["name"] == "Durban"
        assert round(row["metres"], 2) == JNB_TO_DBN_METRES
        assert round(row["metres"], 2) != CPT_TO_DBN_METRES

    def test_two_selected_distances_bind_in_the_order_they_were_added(self, seeded_db):
        row = (
            SpatialSite.query()
            .select_distance("location", JOHANNESBURG, alias="from_jnb")
            .select_distance("location", CAPE_TOWN, alias="from_cpt")
            .where("name = ?", ["Durban"])
            .first()
        )
        assert round(row["from_jnb"], 2) == JNB_TO_DBN_METRES
        assert round(row["from_cpt"], 2) == CPT_TO_DBN_METRES

    def test_the_full_nearest_n_with_distances_query_works_end_to_end(self, seeded_db):
        assert SpatialSite(
            {"name": "Port Elizabeth", "location": PORT_ELIZABETH}
        ).save()

        rows = (
            SpatialSite.query()
            .select_distance("location", CAPE_TOWN)
            .within_distance("location", CAPE_TOWN, 700_000)
            .order_by_distance("location", CAPE_TOWN)
            .limit(2)
            .get()
            .records
        )

        assert [row["name"] for row in rows] == ["Cape Town", "Port Elizabeth"]
        assert rows[0]["metres"] == 0.0
        assert round(rows[1]["metres"], 2) == CPT_TO_PLZ_METRES

    def test_count_ignores_the_selected_distance_and_restores_the_builder(
        self, seeded_db
    ):
        builder = (
            SpatialSite.query()
            .select_distance("location", JOHANNESBURG)
            .where("name != ?", ["Durban"])
            .order_by_distance("location", CAPE_TOWN)
        )

        assert builder.count() == 2
        assert builder.exists() is True

        # The builder must still produce the full query afterwards — count()
        # borrows the columns and the ORDER BY, it does not consume them.
        rows = builder.get().records
        assert [row["name"] for row in rows] == ["Cape Town", "Johannesburg"]
        assert round(rows[0]["metres"], 2) == CPT_TO_JNB_METRES

    def test_select_after_select_distance_drops_the_orphaned_parameters(
        self, seeded_db
    ):
        # An orphaned bound value with no placeholder left would silently shift
        # every parameter after it, so select() clears them with the columns.
        builder = (
            SpatialSite.query()
            .select_distance("location", JOHANNESBURG)
            .select("name")
            .where("name = ?", ["Durban"])
        )

        assert builder._select_params == []
        assert "ST_Distance" not in builder.to_sql()
        assert builder._all_params() == ["Durban"]
        assert _names(builder.get()) == ["Durban"]

    def test_no_coordinate_is_ever_interpolated_into_the_sql(self, gis_db):
        sql = (
            SpatialSite.query()
            .select_distance("location", CAPE_TOWN)
            .to_sql()
        )
        for literal in ("18.4241", "-33.9249"):
            assert literal not in sql
        assert sql.count("?") == 2

    # ── negative ──

    def test_a_hostile_alias_never_reaches_the_sql(self, seeded_db):
        builder = SpatialSite.query()
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            builder.select_distance(
                "location", CAPE_TOWN, alias="m FROM x; DROP TABLE spatial_site --"
            )
        assert builder._select_params == []
        assert builder._columns == ["*"]
        assert seeded_db.table_exists("spatial_site") is True
        assert SpatialSite.count() == 3

    def test_a_hostile_point_value_never_reaches_the_sql(self, seeded_db):
        builder = SpatialSite.query()
        with pytest.raises(ValueError, match="cannot read"):
            builder.select_distance(
                "location", "POINT(0 0)); DROP TABLE spatial_site; --"
            )
        assert builder._select_params == []
        assert SpatialSite.count() == 3

    def test_a_hostile_column_name_is_refused(self, seeded_db):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SpatialSite.query().select_distance(
                "location); DROP TABLE spatial_site; --", CAPE_TOWN
            )
        assert SpatialSite.count() == 3

    def test_it_raises_on_sqlite_at_the_call_site(self, tmp_path):
        connection = Database(f"sqlite:///{tmp_path / 'plain.db'}")
        try:
            builder = QueryBuilder.from_table("spatial_site", connection)
            with pytest.raises(SpatialNotSupportedError, match="sqlite"):
                builder.select_distance("location", CAPE_TOWN)
            assert builder._select_params == []
        finally:
            connection.close()


# ══════════════════════════════════════════════════════════════════
# count() drops ORDER BY — behaviour change on a shared method
# ══════════════════════════════════════════════════════════════════


@postgis_required
class TestCountDropsOrderBy:
    def test_a_plain_order_by_no_longer_breaks_count_on_postgresql(self, seeded_db):
        # PostgreSQL/MSSQL reject a non-aggregated ORDER BY expression beside
        # COUNT(*), so this raised before the fix.
        assert SpatialSite.query().order_by("name DESC").count() == 3

    def test_distance_ordering_survives_count(self, seeded_db):
        assert SpatialSite.query().order_by_distance("location", CAPE_TOWN).count() == 3

    def test_the_order_by_is_restored_after_the_count(self, seeded_db):
        builder = SpatialSite.query().order_by_distance("location", DURBAN)
        assert builder.count() == 3
        assert _names(builder.get()) == ["Durban", "Johannesburg", "Cape Town"]

    def test_count_matches_the_row_count_of_the_ordered_query(self, seeded_db):
        builder = (
            SpatialSite.query()
            .within_distance("location", JOHANNESBURG, 600_000)
            .order_by_distance("location", JOHANNESBURG)
        )
        assert builder.count() == len(builder.get().records)

    def test_where_and_having_parameters_still_bind_for_the_count(self, seeded_db):
        assert (
            SpatialSite.query()
            .where("name != ?", ["Durban"])
            .order_by("name")
            .count()
        ) == 2


# ══════════════════════════════════════════════════════════════════
# intersects() — the geofence predicate
# ══════════════════════════════════════════════════════════════════

# A polygon around the Cape Peninsula only — excludes JNB, DUR and PLZ.
CAPE_ZONE_WKT = "POLYGON((17.5 -34.5, 19.5 -34.5, 19.5 -33.0, 17.5 -33.0, 17.5 -34.5))"
CAPE_ZONE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[17.5, -34.5], [19.5, -34.5], [19.5, -33.0],
                     [17.5, -33.0], [17.5, -34.5]]],
}
# A polygon over the Highveld / KZN — JNB and DUR, not CPT.
INLAND_ZONE_WKT = "POLYGON((25.0 -31.0, 32.0 -31.0, 32.0 -25.0, 25.0 -25.0, 25.0 -31.0))"


@postgis_required
class TestIntersects:
    def test_a_point_inside_the_polygon_is_returned(self, seeded_db):
        assert _names(
            SpatialSite.query().intersects("location", CAPE_ZONE_WKT).get()
        ) == ["Cape Town"]

    def test_points_outside_the_polygon_are_not(self, seeded_db):
        found = _names(
            SpatialSite.query().intersects("location", CAPE_ZONE_WKT).get()
        )
        assert "Johannesburg" not in found
        assert "Durban" not in found

    def test_a_polygon_covering_two_cities_returns_both(self, seeded_db):
        found = sorted(
            _names(SpatialSite.query().intersects("location", INLAND_ZONE_WKT).get())
        )
        assert found == ["Durban", "Johannesburg"]

    def test_a_geojson_polygon_gives_the_identical_result(self, seeded_db):
        from_wkt = _names(
            SpatialSite.query().intersects("location", CAPE_ZONE_WKT).get()
        )
        from_geojson = _names(
            SpatialSite.query().intersects("location", CAPE_ZONE_GEOJSON).get()
        )
        assert from_geojson == from_wkt == ["Cape Town"]

    def test_a_geojson_feature_wrapper_works_too(self, seeded_db):
        feature = {"type": "Feature", "properties": {}, "geometry": CAPE_ZONE_GEOJSON}
        assert _names(
            SpatialSite.query().intersects("location", feature).get()
        ) == ["Cape Town"]

    def test_a_point_geometry_matches_only_the_identical_point(self, seeded_db):
        assert _names(
            SpatialSite.query().intersects("location", CAPE_TOWN).get()
        ) == ["Cape Town"]

    def test_an_ewkt_polygon_keeps_its_srid(self, seeded_db):
        assert _names(
            SpatialSite.query().intersects("location", f"SRID=4326;{CAPE_ZONE_WKT}").get()
        ) == ["Cape Town"]

    def test_it_composes_with_where_ordering_and_a_selected_distance(self, seeded_db):
        builder = (
            SpatialSite.query()
            .select_distance("location", CAPE_TOWN)
            .intersects("location", INLAND_ZONE_WKT)
            .where("name != ?", ["Durban"])
            .order_by_distance("location", CAPE_TOWN)
        )

        assert builder._all_params() == [
            18.4241, -33.9249,                  # SELECT
            f"SRID=4326;{INLAND_ZONE_WKT}",     # WHERE (intersects)
            "Durban",                            # WHERE
            18.4241, -33.9249,                  # ORDER BY
        ]
        rows = builder.get().records
        assert [row["name"] for row in rows] == ["Johannesburg"]
        assert round(rows[0]["metres"], 2) == CPT_TO_JNB_METRES

    def test_no_coordinate_is_interpolated_into_the_sql(self, gis_db):
        builder = SpatialSite.query().intersects("location", CAPE_ZONE_WKT)
        sql = builder.to_sql()
        assert "17.5" not in sql
        assert sql.count("?") == 1
        assert builder._params == [f"SRID=4326;{CAPE_ZONE_WKT}"]

    def test_an_empty_zone_returns_no_rows_not_every_row(self, seeded_db):
        empty_zone = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        assert _names(
            SpatialSite.query().intersects("location", empty_zone).get()
        ) == []

    # ── negative ──

    def test_a_garbage_geometry_is_refused_before_any_sql_runs(self, seeded_db):
        builder = SpatialSite.query()
        with pytest.raises(ValueError, match="cannot read"):
            builder.intersects("location", "18.4241,-33.9249")
        assert builder._wheres == []
        assert builder._params == []
        assert SpatialSite.count() == 3

    def test_an_injected_geometry_string_is_parameterised_not_executed(
        self, seeded_db
    ):
        # This one LOOKS like WKT so it passes the client-side gate — which is
        # the point: safety comes from binding, not from filtering. PostGIS
        # rejects the malformed geometry and the table is untouched.
        hostile = "POLYGON((0 0, 1 0, 1 1, 0 0))'); DROP TABLE spatial_site; --"
        with pytest.raises(Exception):
            SpatialSite.query().intersects("location", hostile).get()

        assert seeded_db.table_exists("spatial_site") is True
        assert SpatialSite.count() == 3

    def test_a_hostile_column_name_is_refused(self, seeded_db):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SpatialSite.query().intersects(
                "location); DROP TABLE spatial_site; --", CAPE_ZONE_WKT
            )
        assert SpatialSite.count() == 3

    def test_a_geojson_of_the_wrong_shape_is_refused(self, seeded_db):
        with pytest.raises(ValueError, match="GeoJSON 'type' must be one of"):
            SpatialSite.query().intersects("location", {"type": "Rectangle"})

    def test_it_raises_on_sqlite_at_the_call_site(self, tmp_path):
        connection = Database(f"sqlite:///{tmp_path / 'plain.db'}")
        try:
            builder = QueryBuilder.from_table("spatial_site", connection)
            with pytest.raises(SpatialNotSupportedError, match="sqlite"):
                builder.intersects("location", CAPE_ZONE_WKT)
            assert builder._wheres == []
        finally:
            connection.close()


# ══════════════════════════════════════════════════════════════════
# bbox() — the map-viewport predicate
# ══════════════════════════════════════════════════════════════════

CAPE_VIEWPORT = (17.5, -34.5, 19.5, -33.0)
INLAND_VIEWPORT = (25.0, -31.0, 32.0, -25.0)


@postgis_required
class TestBbox:
    def test_a_point_inside_the_box_is_returned(self, seeded_db):
        assert _names(
            SpatialSite.query().bbox("location", *CAPE_VIEWPORT).get()
        ) == ["Cape Town"]

    def test_points_outside_the_box_are_not(self, seeded_db):
        found = _names(SpatialSite.query().bbox("location", *CAPE_VIEWPORT).get())
        assert "Johannesburg" not in found
        assert "Durban" not in found

    def test_a_box_covering_two_cities_returns_both(self, seeded_db):
        assert sorted(
            _names(SpatialSite.query().bbox("location", *INLAND_VIEWPORT).get())
        ) == ["Durban", "Johannesburg"]

    def test_it_agrees_with_the_equivalent_intersects_polygon(self, seeded_db):
        from_bbox = sorted(
            _names(SpatialSite.query().bbox("location", *INLAND_VIEWPORT).get())
        )
        from_polygon = sorted(
            _names(SpatialSite.query().intersects("location", INLAND_ZONE_WKT).get())
        )
        assert from_bbox == from_polygon

    def test_a_point_on_the_box_edge_is_included(self, seeded_db):
        # Documented contract: the envelope is a closed polygon, so its boundary
        # is inside. Cape Town sits exactly on the west and north edges here.
        assert _names(
            SpatialSite.query()
            .bbox("location", CAPE_TOWN[0], -34.5, 19.5, CAPE_TOWN[1])
            .get()
        ) == ["Cape Town"]

    def test_a_zero_area_box_at_a_stored_point_still_finds_it(self, seeded_db):
        assert _names(
            SpatialSite.query()
            .bbox("location", CAPE_TOWN[0], CAPE_TOWN[1], CAPE_TOWN[0], CAPE_TOWN[1])
            .get()
        ) == ["Cape Town"]

    def test_it_composes_with_a_radius_and_keeps_param_order(self, seeded_db):
        builder = (
            SpatialSite.query()
            .bbox("location", *INLAND_VIEWPORT)
            .within_distance("location", JOHANNESBURG, 100_000)
        )

        assert builder._all_params() == [
            25.0, -31.0, 32.0, -25.0,   # bbox corners
            28.0473, -26.2041, 100_000.0,  # within_distance
        ]
        assert _names(builder.get()) == ["Johannesburg"]

    def test_no_ordinate_is_interpolated_into_the_sql(self, gis_db):
        builder = SpatialSite.query().bbox("location", *CAPE_VIEWPORT)
        sql = builder.to_sql()
        for literal in ("17.5", "-34.5", "19.5", "-33.0"):
            assert literal not in sql
        assert sql.count("?") == 4
        assert builder._params == [17.5, -34.5, 19.5, -33.0]

    def test_a_box_over_open_ocean_returns_nothing_not_everything(self, seeded_db):
        assert _names(
            SpatialSite.query().bbox("location", -40.0, -10.0, -30.0, 0.0).get()
        ) == []

    # ── negative ──

    def test_a_swapped_corner_order_returns_nothing_rather_than_wrong_rows(
        self, seeded_db
    ):
        # (lat, lon) instead of (lon, lat) for the inland viewport stays inside
        # the legal ranges, so no validation can catch it — but it selects a
        # patch of the Atlantic and the developer sees an empty map at once.
        assert _names(
            SpatialSite.query().bbox("location", -31.0, 25.0, -25.0, 32.0).get()
        ) == []

    def test_an_inside_out_box_is_refused_naming_the_axis(self, seeded_db):
        builder = SpatialSite.query()
        with pytest.raises(ValueError, match="min_lon .* is east of max_lon"):
            builder.bbox("location", 19.5, -34.5, 17.5, -33.0)
        assert builder._wheres == []
        assert builder._params == []

    def test_an_inverted_latitude_range_is_refused(self, gis_db):
        with pytest.raises(ValueError, match="min_lat .* is north of max_lat"):
            SpatialSite.query().bbox("location", 17.5, -33.0, 19.5, -34.5)

    @pytest.mark.parametrize(
        "corners,offender",
        [
            ((-181.0, -34.5, 19.5, -33.0), "min_lon"),
            ((17.5, -91.0, 19.5, -33.0), "min_lat"),
            ((17.5, -34.5, 181.0, -33.0), "max_lon"),
            ((17.5, -34.5, 19.5, 91.0), "max_lat"),
        ],
    )
    def test_an_out_of_range_ordinate_is_refused_naming_it(
        self, gis_db, corners, offender
    ):
        with pytest.raises(ValueError, match=f"{offender} .* is out of range"):
            SpatialSite.query().bbox("location", *corners)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_nan_and_infinity_are_refused(self, gis_db, bad):
        with pytest.raises(ValueError, match="must be finite"):
            SpatialSite.query().bbox("location", bad, -34.5, 19.5, -33.0)

    def test_a_non_numeric_ordinate_is_refused(self, seeded_db):
        builder = SpatialSite.query()
        with pytest.raises(ValueError, match="min_lon must be a number"):
            builder.bbox("location", "17.5); DROP TABLE spatial_site --",
                         -34.5, 19.5, -33.0)
        assert builder._params == []
        assert seeded_db.table_exists("spatial_site") is True
        assert SpatialSite.count() == 3

    def test_a_hostile_column_name_is_refused(self, seeded_db):
        with pytest.raises(ValueError, match="not a valid SQL identifier"):
            SpatialSite.query().bbox(
                "location); DROP TABLE spatial_site; --", *CAPE_VIEWPORT
            )
        assert SpatialSite.count() == 3

    def test_it_raises_on_sqlite_at_the_call_site(self, tmp_path):
        connection = Database(f"sqlite:///{tmp_path / 'plain.db'}")
        try:
            builder = QueryBuilder.from_table("spatial_site", connection)
            with pytest.raises(SpatialNotSupportedError, match="sqlite"):
                builder.bbox("location", *CAPE_VIEWPORT)
            assert builder._wheres == []
        finally:
            connection.close()
