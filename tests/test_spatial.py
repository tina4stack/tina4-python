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
from tina4_python.query_builder import QueryBuilder

# ── Known-answer geography fixtures (lon, lat) ──────────────────────
CAPE_TOWN = (18.4241, -33.9249)
JOHANNESBURG = (28.0473, -26.2041)
DURBAN = (31.0218, -29.8587)

CPT_TO_JNB_METRES = 1_261_119.44
CPT_TO_DBN_METRES = 1_273_094.55
JNB_TO_DBN_METRES = 499_521.49

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
