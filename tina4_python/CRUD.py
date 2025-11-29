#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

import base64
import datetime
from decimal import Decimal

from tina4_python.Debug import Debug
import re
from tina4_python.Template import Template
from tina4_python.Constant import TINA4_DELETE, TINA4_POST, TINA4_GET, HTTP_OK, APPLICATION_JSON
from tina4_python.Router import Router
import tina4_python
import os
import shutil
import json

class CRUD:
    """
    CRUD - Automatic Create, Read, Update & Delete interface generator for Tina4.

    Takes a DatabaseResult object (usually from await conn.query(...)) and instantly
    turns it into a fully functional, searchable, paginated HTML + JSON CRUD interface
    using a single Twig template.

    Features
    --------
    • Zero-configuration table detection from any SELECT query
    • Automatic RESTful route registration (GET/POST/DELETE)
    • Built-in server-side search & pagination
    • Safe JSON serialization (Decimal → float, datetime → ISO, bytes → base64)
    • Per-table template auto-copy for easy customization
    • Works with SQLite, PostgreSQL, MySQL/MariaDB, MSSQL, Firebird and more

    Example
    -------
    result = await conn.query("SELECT * FROM articles")
    return await result.crud.to_crud(request, {"primary_key": "id", "limit": 25})
    """

    def __init__(self):
        """Initialize the CRUD helper with empty state."""
        self.records = []               # List of raw record dictionaries from the last fetch
        self.dba = None                 # Reference to the underlying Database connection
        self.columns = []               # Column names (list or dict with metadata)
        self.search = ""                  # Current search term
        self.search_columns = []        # Explicit list of columns to search (optional)
        self.total_count = 0            # Total records matching the query (ignoring pagination)
        self.sql = None                 # Original SQL used for the result set
        self.error = ""                 # Error message if something went wrong
        self.table_name = None          # Detected or overridden table name

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

        Args:
            sql (str): The SQL statement to clean.

        Returns:
            str: SQL without any pagination clauses.
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
        Extract the main table name from a SELECT query.

        Looks for the last FROM clause that is not inside a sub-query.
        Result is cached in self.table_name.

        Args:
            query (str): SQL query string.

        Returns:
            str | None: Table name or None if not detectable.
        """

        if self.table_name is not None:
            return self.table_name

        # Remove LIMIT and everything after
        query = re.sub(r'\s+LIMIT\s+.*$', '', query, flags=re.I)
        # Find the innermost FROM table (non-subquery)
        from_parts = re.findall(r'\bFROM\s+([a-zA-Z0-9_]+)(?:\s+AS\s+\w+)?(?:\s+|$|\))', query, re.I)
        return from_parts[-1] if from_parts else None

    def ensure_crud_template(self, filename: str):
        """
        Ensure a CRUD Twig template exists in src/templates/crud/.

        If the template does not exist it is copied from the package default
        (templates/components/crud.twig) so developers can customize it per table
        without touching the core library.

        Args:
            filename (str): Desired filename inside src/templates/crud (e.g. "articles.twig").

        Returns:
            str: Full filesystem path to the (now existing) template.
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
        """
        Generate a complete CRUD interface for the current result set.

        Automatically registers four routes under the current request URL:
          • GET    /url/table_name           → JSON for DataTables (with search & pagination)
          • POST   /url/table_name           → create record
          • POST   /url/table_name/{id}      → update record
          • DELETE /url/table_name/{id}      → delete record

        Returns the rendered HTML page using the table-specific Twig template.

        Args:
            request: Tina4 Request object (provides base URL and params).
            options (dict, optional): Configuration dictionary:
                - primary_key (str): default "id"
                - limit (int): default 10
                - offset (int): default 0
                - search (str): default ""
                - search_columns (list): columns to search
                - name (str): custom route/template name (defaults to table name)

        Returns:
            str: Rendered HTML page (or JSON on AJAX calls).
        """
        try:
            table_name = self.get_table_name(self.sql)

            if table_name is not None and self.table_name is None:
                self.table_name = table_name

            table_nice_name = Template.get_nice_label(table_name)

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

            crud_name = table_name
            if "name" in options:
                crud_name = options["name"]

            twig_file = self.ensure_crud_template(crud_name + ".twig")

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
                return response({"message": f"<script>showMessage('{table_nice_name} Record updated');</script>", "post": request.body}, HTTP_OK, APPLICATION_JSON)

            async def delete_record(request, response):
                Debug.info("CRUD DELETE", table_name, request.params)
                self.dba.delete(table_name, {options["primary_key"] : request.params[options["primary_key"]]})
                self.dba.commit()
                return response({"message": f"<script>showMessage('{table_nice_name} Record deleted');</script>"}, HTTP_OK, APPLICATION_JSON)

            Router.add(TINA4_GET, os.path.join(request.url, crud_name).replace("\\", "/"), get_record)
            Router.add(TINA4_POST, os.path.join(request.url, crud_name).replace("\\", "/"), post_record)
            Router.add(TINA4_POST, os.path.join(request.url, crud_name, "{"+options["primary_key"]+"}").replace("\\", "/"), update_record)
            Router.add(TINA4_DELETE, os.path.join(request.url, crud_name, "{"+options["primary_key"]+"}").replace("\\", "/"), delete_record)

            fields = []
            for column in self.columns:
                fields.append({"name": column, "label": Template.get_nice_label(column)})

            html = Template.render(twig_file.replace(os.path.join(tina4_python.root_path, "src", "templates"), "").replace("\\", "/"),
                                   {"columns": fields, "records": self.to_array(),
                                    "table_name": crud_name,
                                    "total_records": self.total_count,
                                    "options": options})

            return html
        except Exception as e:
            return "Error rendering CRUD: "+str(e)

    def to_array(self, _filter=None):
        """
        Convert the internal records to a JSON-serializable list of dictionaries.

        Handles non-JSON-native types:
          • Decimal      → float
          • datetime/date → ISO 8601 string
          • bytes/memoryview → base64 encoded string

        Args:
            _filter (callable, optional): Function applied to each record dict before returning.

        Returns:
            list[dict]: Serializable records.
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
        """Alias of to_array() for readability."""
        return self.to_array(_filter)

    def to_json(self, _filter=None):
        """Return records as a JSON encoded string."""
        return json.dumps(self.to_array(_filter))

    def __iter__(self):
        """Allow iteration over records (yields results from to_array())."""
        return iter(self.to_array())

    def __getitem__(self, item):
        """Support indexing like a list: crud[0] → first raw record."""
        if item < len(self.records):
            return self.records[item]
        else:
            return {}

    def __str__(self):
        """String representation is the JSON output."""
        return self.to_json()
