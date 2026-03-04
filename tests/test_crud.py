#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import json
import datetime
from decimal import Decimal

from tina4_python.CRUD import CRUD
from tina4_python.DatabaseResult import DatabaseResult


# --- strip_sql_pagination ---

class TestStripSqlPagination:
    def setup_method(self):
        self.crud = CRUD()

    def test_mysql_limit(self):
        sql = "SELECT * FROM users LIMIT 10"
        assert "LIMIT" not in self.crud.strip_sql_pagination(sql)

    def test_mysql_limit_offset(self):
        sql = "SELECT * FROM users LIMIT 10 OFFSET 20"
        result = self.crud.strip_sql_pagination(sql)
        assert "LIMIT" not in result
        assert "OFFSET" not in result

    def test_mysql_limit_comma(self):
        sql = "SELECT * FROM users LIMIT 10, 20"
        assert "LIMIT" not in self.crud.strip_sql_pagination(sql)

    def test_postgres_limit_offset(self):
        sql = "SELECT * FROM products LIMIT 25 OFFSET 50"
        result = self.crud.strip_sql_pagination(sql)
        assert "LIMIT" not in result
        assert "OFFSET" not in result

    def test_firebird_first_skip(self):
        sql = "SELECT FIRST 10 SKIP 20 * FROM orders"
        result = self.crud.strip_sql_pagination(sql)
        assert "FIRST" not in result
        assert "SKIP" not in result

    def test_mssql_offset_fetch(self):
        sql = "SELECT * FROM items OFFSET 10 ROWS FETCH NEXT 25 ROWS ONLY"
        result = self.crud.strip_sql_pagination(sql)
        assert "OFFSET" not in result
        assert "FETCH" not in result

    def test_oracle_rownum(self):
        sql = "SELECT * FROM data WHERE ROWNUM <= 100"
        assert "ROWNUM" not in self.crud.strip_sql_pagination(sql)

    def test_no_pagination(self):
        sql = "SELECT id, name FROM users WHERE active = 1"
        assert self.crud.strip_sql_pagination(sql) == sql.strip()

    def test_empty_string(self):
        assert self.crud.strip_sql_pagination("") == ""

    def test_none_input(self):
        assert self.crud.strip_sql_pagination(None) is None

    def test_case_insensitive(self):
        sql = "SELECT * FROM users limit 10 offset 5"
        result = self.crud.strip_sql_pagination(sql)
        assert "limit" not in result.lower()

    def test_trailing_semicolon(self):
        sql = "SELECT * FROM users LIMIT 10;"
        result = self.crud.strip_sql_pagination(sql)
        assert not result.endswith(";")


# --- get_table_name ---

class TestGetTableName:
    def setup_method(self):
        self.crud = CRUD()

    def test_simple_select(self):
        assert self.crud.get_table_name("SELECT * FROM users") == "users"

    def test_select_with_alias(self):
        assert self.crud.get_table_name("SELECT * FROM users AS u") == "users"

    def test_select_with_where(self):
        assert self.crud.get_table_name("SELECT * FROM orders WHERE id = 1") == "orders"

    def test_select_with_limit(self):
        assert self.crud.get_table_name("SELECT * FROM products LIMIT 10") == "products"

    def test_select_with_join(self):
        result = self.crud.get_table_name("SELECT * FROM users JOIN orders ON users.id = orders.user_id")
        assert result in ("users", "orders")

    def test_cached_table_name(self):
        self.crud.table_name = "cached_table"
        assert self.crud.get_table_name("SELECT * FROM other") == "cached_table"

    def test_no_from_clause(self):
        assert self.crud.get_table_name("SELECT 1") is None


# --- to_array ---

class TestToArray:
    def test_empty_records(self):
        crud = CRUD()
        crud.records = []
        crud.error = None
        assert crud.to_array() == []

    def test_basic_records(self):
        crud = CRUD()
        crud.records = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        crud.error = None
        result = crud.to_array()
        assert len(result) == 2
        assert result[0]["name"] == "Alice"

    def test_decimal_conversion(self):
        crud = CRUD()
        crud.records = [{"price": Decimal("19.99"), "tax": Decimal("1.50")}]
        crud.error = None
        result = crud.to_array()
        assert result[0]["price"] == 19.99
        assert isinstance(result[0]["price"], float)

    def test_datetime_conversion(self):
        crud = CRUD()
        dt = datetime.datetime(2025, 6, 15, 10, 30)
        crud.records = [{"created": dt}]
        crud.error = None
        result = crud.to_array()
        assert result[0]["created"] == "2025-06-15T10:30:00"

    def test_date_conversion(self):
        crud = CRUD()
        d = datetime.date(2025, 1, 1)
        crud.records = [{"date": d}]
        crud.error = None
        result = crud.to_array()
        assert result[0]["date"] == "2025-01-01"

    def test_bytes_base64_encode(self):
        crud = CRUD()
        crud.records = [{"data": b"hello"}]
        crud.error = None
        result = crud.to_array()
        import base64
        assert result[0]["data"] == base64.b64encode(b"hello").decode("utf-8")

    def test_bytes_no_base64(self):
        crud = CRUD()
        crud.records = [{"data": b"hello"}]
        crud.error = None
        result = crud.to_array(base64_encode=False)
        assert result[0]["data"] == "hello"

    def test_error_returns_dict(self):
        crud = CRUD()
        crud.error = "something went wrong"
        result = crud.to_array()
        assert result == {"error": "something went wrong"}

    def test_filter_function(self):
        crud = CRUD()
        crud.records = [{"id": 1, "name": "alice"}]
        crud.error = None
        result = crud.to_array(filter_fn=lambda r: {**r, "name": r["name"].upper()})
        assert result[0]["name"] == "ALICE"


# --- to_json ---

class TestToJson:
    def test_to_json(self):
        crud = CRUD()
        crud.records = [{"id": 1}]
        crud.error = None
        result = crud.to_json()
        parsed = json.loads(result)
        assert parsed[0]["id"] == 1

    def test_to_list_alias(self):
        crud = CRUD()
        crud.records = [{"a": 1}]
        crud.error = None
        assert crud.to_list() == crud.to_array()


# --- CRUD iteration & indexing ---

class TestCrudIteration:
    def test_iter(self):
        crud = CRUD()
        crud.records = [{"id": 1}, {"id": 2}]
        crud.error = None
        result = list(crud)
        assert len(result) == 2

    def test_getitem(self):
        crud = CRUD()
        crud.records = [{"id": 1}, {"id": 2}]
        assert crud[0] == {"id": 1}
        assert crud[1] == {"id": 2}

    def test_getitem_out_of_range(self):
        crud = CRUD()
        crud.records = [{"id": 1}]
        assert crud[5] == {}

    def test_str(self):
        crud = CRUD()
        crud.records = [{"id": 1}]
        crud.error = None
        result = str(crud)
        assert json.loads(result) == [{"id": 1}]


# --- DatabaseResult ---

class TestDatabaseResult:
    def test_init_defaults(self):
        dr = DatabaseResult()
        assert dr.records == []
        assert dr.columns == []
        assert dr.count == 0
        assert dr.total_count == 0
        assert dr.error is None

    def test_init_with_data(self):
        records = [{"id": 1}, {"id": 2}]
        dr = DatabaseResult(records, ["id"], count=10, limit=5, skip=0)
        assert dr.count == 2
        assert dr.total_count == 10
        assert dr.limit == 5
        assert dr.skip == 0

    def test_to_paginate(self):
        records = [{"id": 1, "name": "Alice"}]
        dr = DatabaseResult(records, ["id", "name"], count=100, limit=10, skip=20)
        result = dr.to_paginate()
        assert result["recordsTotal"] == 100
        assert result["recordsOffset"] == 20
        assert result["recordCount"] == 1
        assert result["fields"] == ["id", "name"]
        assert len(result["data"]) == 1

    def test_to_csv(self):
        records = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        dr = DatabaseResult(records, ["id", "name"])
        csv_output = dr.to_csv()
        lines = csv_output.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert '"id"' in lines[0]
        assert '"Alice"' in lines[1]

    def test_to_csv_empty(self):
        dr = DatabaseResult()
        assert dr.to_csv() == ""

    def test_to_csv_no_records(self):
        dr = DatabaseResult(columns=["id", "name"])
        csv_output = dr.to_csv()
        lines = csv_output.strip().split("\n")
        assert len(lines) == 1  # header only
