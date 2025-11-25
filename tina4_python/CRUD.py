import base64
import datetime
from decimal import Decimal

from tina4_python.Debug import Debug
import re
from tina4_python.Template import Template
from tina4_python.Constant import *
from tina4_python.Router import Router
import tina4_python
import os
import shutil
import json

class CRUD:

    def __init__(self):
        self.records = []
        self.dba = None
        self.columns = []
        self.search = ""
        self.search_columns = []
        self.total_count = 0
        self.sql = None
        self.error = ""

    def strip_sql_pagination(self, sql: str) -> str:
        """
        Remove ALL known SQL pagination syntaxes from a query.

        Supported dialects:
          - MySQL / MariaDB: LIMIT 10, 20, or LIMIT 20 OFFSET 10
          - PostgreSQL / SQLite:      LIMIT 10 OFFSET 20
          - Firebird:                 FIRST 10 SKIP 20
          - SQL Server (MSSQL): OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY
          - Oracle (12c+): OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY
          - Oracle (older): WHERE ROWNUM <= 10 (partial support)

        Safe for nested subqueries, comments, and mixed cases.
        """

        if not sql or not sql.strip():
            return sql

        sql = sql.strip()

        # ------------------------------------------------------------------
        # 1. SQL Server / Oracle 12c+ : OFFSET ... FETCH ...
        # ------------------------------------------------------------------
        sql = re.sub(
            r'''
            \bOFFSET\b\s+\d+\s+ROWS?
            (?:\s+\bFETCH\s+(?:FIRST|NEXT)\b\s+\d+\s+ROWS?\s+(?:ONLY|WITH\s+TIES))?
            ''',
            '',
            sql,
            flags=re.IGNORECASE | re.VERBOSE
        )

        # ------------------------------------------------------------------
        # 2. Firebird: FIRST n SKIP m
        # ------------------------------------------------------------------
        sql = re.sub(
            r'\b(?:FIRST\s+\d+\s+)?SKIP\s+\d+|\bFIRST\s+\d+(?:\s+SKIP\s+\d+)?',
            '',
            sql,
            flags=re.IGNORECASE
        )

        # ------------------------------------------------------------------
        # 3. Standard LIMIT / OFFSET (MySQL, PostgreSQL, SQLite, etc.)
        # ------------------------------------------------------------------
        sql = re.sub(
            r'''
            \bLIMIT\b
            \s+
            (?:\d+\s*,\s*\d+|\d+)
            (?:\s+\bOFFSET\b\s+\d+)?
            \s*
            (?:--.*|/\*.*?\*/)?   # optional trailing comments
            \s*;?\s*$
            ''',
            '',
            sql,
            flags=re.IGNORECASE | re.VERBOSE
        )

        # ------------------------------------------------------------------
        # 4. Oracle old style: WHERE ROWNUM <= n  (best effort)
        # ------------------------------------------------------------------
        sql = re.sub(
            r'\bWHERE\s+ROWNUM\s*(?:<=|<|=)\s*\d+',
            '',
            sql,
            flags=re.IGNORECASE
        )

        # ------------------------------------------------------------------
        # Final cleanup
        # ------------------------------------------------------------------
        sql = re.sub(r'\s+$', '', sql)           # trailing whitespace
        sql = re.sub(r';\s*$', '', sql)          # trailing semicolon
        sql = re.sub(r'\s+WHERE\s*$', ' WHERE', sql)  # fix dangling WHERE

        return sql.strip()

    def get_table_name(self, query):
        """
        Gets the table name
        :param query:
        :return:
        """
        # Remove LIMIT and everything after
        query = re.sub(r'\s+LIMIT\s+.*$', '', query, flags=re.I)
        # Find the innermost FROM table (non-subquery)
        from_parts = re.findall(r'\bFROM\s+([a-zA-Z0-9_]+)(?:\s+AS\s+\w+)?(?:\s+|$|\))', query, re.I)
        return from_parts[-1] if from_parts else None

    def ensure_crud_template(self, filename: str):
        """
        Checks to see if the template exists otherwise copies it over
        :param filename:
        :return:
        """
        root = tina4_python.root_path
        target_dir = os.path.join(root, "src", "templates", "crud")
        target_path = os.path.join(target_dir, filename)
        Debug.info("CRUD Template", target_path)

        if os.path.exists(target_path):
            return target_path  # already exists

        os.makedirs(target_dir, exist_ok=True)

        source_path = os.path.join(os.path.dirname(__file__), "templates", "components", "crud.twig")

        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Default template {filename} not found")

        shutil.copy(source_path, target_path)
        return target_path

    def to_crud(self, request, options=None):
        table_name = self.get_table_name(self.sql)
        table_nice_name = Template.get_nice_label(table_name)
        twig_file = self.ensure_crud_template(table_name + ".twig")

        if options is None:
            options = {}

        if "primary_key" not in options:
            options["primary_key"] = "id"

        if "limit" not in options:
            options["limit"] = 10

        if "offset" not in options:
            options["offset"] = 0

        if "search" not in options:
            options["search"] = ""

        if "search_columns" in options:
            self.search_columns = options["search_columns"]

        async def get_record(request, response):
            limit = int(request.params.get("limit", options.get("limit", 10)))
            offset = int(request.params.get("offset", options.get("offset", 0)))
            search = request.params.get("search", "").strip()
            self.search = search
            options["search"] = search


            # Use defined columns or fallback
            if not "search_columns" in options:
                search_columns = self.columns
                if isinstance(search_columns, dict):
                    search_columns = [c["name"] for c in search_columns if "name" in c]
            else:
                search_columns = options["search_columns"]

            # Execute fetch with search
            result = self.dba.fetch(
                sql=self.strip_sql_pagination(self.sql),
                limit=limit,
                skip=offset,
                search=search,
                search_columns=search_columns
            )

            self.records = result.records
            self.total_count = result.total_count
            self.limit = limit
            self.skip = offset

            return response(self.to_crud(request, options), HTTP_OK, APPLICATION_JSON)

        async def post_record(request, response):
            Debug.info("CRUD CREATE", table_name, request.body)
            self.dba.insert(table_name, request.body, primary_key=options["primary_key"])
            self.dba.commit()
            return response({"message": f"<script>showMessage('{table_nice_name} Record added');</script>"}, HTTP_OK, APPLICATION_JSON)

        async def update_record(request, response):
            Debug.info("CRUD UPDATE", table_name, request.params, request.body)
            self.dba.update(table_name, request.body, primary_key=options["primary_key"])
            self.dba.commit()
            return response({"message": f"<script>showMessage('{table_nice_name}  Record updated');</script>", "post": request.body}, HTTP_OK, APPLICATION_JSON)

        async def delete_record(request, response):
            Debug.info("CRUD DELETE", table_name, request.params)
            self.dba.delete(table_name, {options["primary_key"] : request.params[options["primary_key"]]})
            self.dba.commit()
            return response({"message": f"<script>showMessage('{table_nice_name}  Record deleted');</script>"}, HTTP_OK, APPLICATION_JSON)

        Router.add(TINA4_GET, os.path.join(request.url, table_name).replace("\\", "/"), get_record)
        Router.add(TINA4_POST, os.path.join(request.url, table_name).replace("\\", "/"), post_record)
        Router.add(TINA4_POST, os.path.join(request.url, table_name, "{"+options["primary_key"]+"}").replace("\\", "/"), update_record)
        Router.add(TINA4_DELETE, os.path.join(request.url, table_name, "{"+options["primary_key"]+"}").replace("\\", "/"), delete_record)

        fields = []
        for column in self.columns:
            fields.append({"name": column, "label": Template.get_nice_label(column)})

        html = Template.render(twig_file.replace(os.path.join(tina4_python.root_path, "src", "templates"), "").replace("\\", "/"),
                               {"columns": fields, "records": self.to_array(),
                                "table_name": table_name,
                                "total_records": self.total_count,
                                "options": options})

        return html


    def to_array(self, _filter=None):
        """
        Creates an array or list of the items
        :return:
        """
        if self.error is not None:
            return {"error": self.error}
        elif len(self.records) > 0:
            # check all the records - if we get bytes we base64encode them for the json to work
            json_records = []
            for record in self.records:
                json_record = {}
                for key in record:
                    if isinstance(record[key], Decimal):
                        json_record[key] = float(record[key])
                    elif isinstance(record[key], (datetime.date, datetime.datetime)):
                        json_record[key] = record[key].isoformat()
                    elif isinstance(record[key], memoryview):
                        json_record[key] = base64.b64encode(record[key].tobytes()).decode('utf-8')
                    elif isinstance(record[key], bytes):
                        json_record[key] = base64.b64encode(record[key]).decode('utf-8')
                    else:
                        json_record[key] = record[key]

                if _filter is not None:
                    json_record = _filter(json_record)

                json_records.append(json_record)

            return json_records
        else:
            return []

    def to_list(self, _filter=None):
        return self.to_array(_filter)

    def to_json(self, _filter=None):
        return json.dumps(self.to_array(_filter))

    def __iter__(self):
        return iter(self.to_array())

    def __getitem__(self, item):
        if item < len(self.records):
            return self.records[item]
        else:
            return {}

    def __str__(self):
        return self.to_json()
