# Tina4 MongoDB Driver — Uses pymongo (optional).
"""
MongoDB adapter using pymongo.

    db = Database("mongodb://user:pass@localhost:27017/mydb")
    db = Database("pymongo://user:pass@localhost:27017/mydb")

Requires: pip install pymongo

SQL is transparently translated to MongoDB operations so the same API
surface works regardless of engine.  Full SQL is not supported — JOINs
are silently ignored.  Aggregation beyond what simple regex parsing can
handle should be done with native pymongo via db.adapter._collection().
"""
import re
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


# ── SQL → MongoDB translation helpers ─────────────────────────────────────────

def _sql_like_to_regex(pattern: str) -> str:
    """Convert a SQL LIKE pattern (% and _) to a Python regex string."""
    regex = re.escape(pattern)
    regex = regex.replace(r"\%", ".*").replace(r"\_", ".")
    return regex


def _parse_where(where_clause: str, params: list) -> dict:
    """
    Parse a simple SQL WHERE clause into a MongoDB filter dict.

    Supports:
      =, !=, <>, >, >=, <, <=, LIKE, NOT LIKE, IN, NOT IN,
      IS NULL, IS NOT NULL, BETWEEN, AND, OR

    Params are consumed left-to-right as placeholders (?) are encountered.
    Returns a MongoDB filter dict.
    """
    if not where_clause or not where_clause.strip():
        return {}

    # Work with a mutable list so recursive calls can share the cursor.
    param_queue = list(params or [])
    return _parse_or(where_clause.strip(), param_queue)


def _next_param(param_queue: list):
    return param_queue.pop(0) if param_queue else None


def _parse_or(expr: str, param_queue: list) -> dict:
    """Split on top-level OR and combine with $or."""
    parts = _split_top_level(expr, r"\bOR\b")
    if len(parts) == 1:
        return _parse_and(parts[0], param_queue)
    clauses = [_parse_and(p.strip(), param_queue) for p in parts]
    return {"$or": clauses}


def _parse_and(expr: str, param_queue: list) -> dict:
    """Split on top-level AND and merge into a single dict (implicit AND)."""
    parts = _split_top_level(expr, r"\bAND\b")
    result: dict = {}
    for part in parts:
        sub = _parse_condition(part.strip(), param_queue)
        # Merge — if a key already exists we need $and
        for k, v in sub.items():
            if k in result:
                existing = result.pop(k)
                result.setdefault("$and", [])
                result["$and"].append({k: existing})
                result["$and"].append({k: v})
            else:
                result[k] = v
    return result


def _split_top_level(expr: str, pattern: str) -> list[str]:
    """Split expr on pattern but ignore matches inside parentheses."""
    parts = []
    depth = 0
    current: list[str] = []
    i = 0
    expr_upper = expr.upper()
    # Build a compiled pattern for the keyword
    kw_re = re.compile(pattern, re.IGNORECASE)

    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
            current.append(ch)
            i += 1
        elif ch == ")":
            depth -= 1
            current.append(ch)
            i += 1
        elif depth == 0:
            m = kw_re.match(expr, i)
            if m:
                parts.append("".join(current).strip())
                current = []
                i = m.end()
            else:
                current.append(ch)
                i += 1
        else:
            current.append(ch)
            i += 1

    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _parse_condition(cond: str, param_queue: list) -> dict:
    """Parse a single predicate into a MongoDB filter fragment."""
    cond = cond.strip()

    # Strip outer parentheses
    while cond.startswith("(") and cond.endswith(")"):
        inner = cond[1:-1].strip()
        # Make sure the parens actually match at the outermost level
        depth = 0
        balanced = True
        for i, ch in enumerate(inner):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
        if balanced and depth == 0:
            cond = inner
        else:
            break

    # IS NULL / IS NOT NULL
    m = re.match(r"^(\w+)\s+IS\s+NOT\s+NULL$", cond, re.IGNORECASE)
    if m:
        return {m.group(1): {"$ne": None}}

    m = re.match(r"^(\w+)\s+IS\s+NULL$", cond, re.IGNORECASE)
    if m:
        return {m.group(1): None}

    # BETWEEN ? AND ?
    m = re.match(r"^(\w+)\s+BETWEEN\s+\?\s+AND\s+\?$", cond, re.IGNORECASE)
    if m:
        lo = _next_param(param_queue)
        hi = _next_param(param_queue)
        return {m.group(1): {"$gte": lo, "$lte": hi}}

    # NOT LIKE
    m = re.match(r"^(\w+)\s+NOT\s+LIKE\s+\?$", cond, re.IGNORECASE)
    if m:
        val = _next_param(param_queue)
        return {m.group(1): {"$not": re.compile(_sql_like_to_regex(str(val)), re.IGNORECASE)}}

    # LIKE
    m = re.match(r"^(\w+)\s+LIKE\s+\?$", cond, re.IGNORECASE)
    if m:
        val = _next_param(param_queue)
        return {m.group(1): re.compile(_sql_like_to_regex(str(val)), re.IGNORECASE)}

    # NOT IN (?,?,...)
    m = re.match(r"^(\w+)\s+NOT\s+IN\s*\(([^)]+)\)$", cond, re.IGNORECASE)
    if m:
        placeholders = m.group(2)
        count = placeholders.count("?")
        values = [_next_param(param_queue) for _ in range(count)]
        return {m.group(1): {"$nin": values}}

    # IN (?,?,...)
    m = re.match(r"^(\w+)\s+IN\s*\(([^)]+)\)$", cond, re.IGNORECASE)
    if m:
        placeholders = m.group(2)
        count = placeholders.count("?")
        values = [_next_param(param_queue) for _ in range(count)]
        return {m.group(1): {"$in": values}}

    # Comparison operators: >=, <=, !=, <>, >, <, =
    for op_sql, op_mongo in [(">=", "$gte"), ("<=", "$lte"),
                              ("!=", "$ne"), ("<>", "$ne"),
                              (">", "$gt"), ("<", "$lt")]:
        m = re.match(rf"^(\w+)\s*{re.escape(op_sql)}\s*\?$", cond, re.IGNORECASE)
        if m:
            val = _next_param(param_queue)
            return {m.group(1): {op_mongo: val}}

    # Equality: field = ?
    m = re.match(r"^(\w+)\s*=\s*\?$", cond, re.IGNORECASE)
    if m:
        val = _next_param(param_queue)
        return {m.group(1): val}

    # Equality with literal (no placeholder): field = 'value' or field = 123
    m = re.match(r"^(\w+)\s*=\s*'(.+)'$", cond, re.IGNORECASE)
    if m:
        return {m.group(1): m.group(2)}

    m = re.match(r"^(\w+)\s*=\s*(\d+(?:\.\d+)?)$", cond, re.IGNORECASE)
    if m:
        raw = m.group(2)
        return {m.group(1): float(raw) if "." in raw else int(raw)}

    # Nested OR/AND inside parentheses
    m = re.match(r"^\((.+)\)$", cond, re.DOTALL)
    if m:
        return _parse_or(m.group(1).strip(), param_queue)

    # Fallback — return empty filter (no crash)
    return {}


def _parse_select_sql(sql: str, params: list, limit: int, offset: int) -> dict:
    """
    Break a SELECT statement into its MongoDB-equivalent components.

    Returns a dict with keys:
        collection, projection, mongo_filter, sort, skip, limit
    """
    sql = sql.strip()

    # -- Strip trailing semicolon
    sql = sql.rstrip(";").strip()

    # -- Extract LIMIT/OFFSET from the SQL (may override the function args)
    limit_in_sql = limit
    offset_in_sql = offset
    m = re.search(r"\bLIMIT\s+(\d+)\s+OFFSET\s+(\d+)\s*$", sql, re.IGNORECASE)
    if m:
        limit_in_sql = int(m.group(1))
        offset_in_sql = int(m.group(2))
        sql = sql[:m.start()].strip()
    else:
        m = re.search(r"\bOFFSET\s+(\d+)\s*$", sql, re.IGNORECASE)
        if m:
            offset_in_sql = int(m.group(1))
            sql = sql[:m.start()].strip()
        m = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
        if m:
            limit_in_sql = int(m.group(1))
            sql = sql[:m.start()].strip()

    # -- Extract ORDER BY
    sort_list = []
    m = re.search(r"\bORDER\s+BY\s+(.+)$", sql, re.IGNORECASE)
    if m:
        order_str = m.group(1).strip()
        sql = sql[:m.start()].strip()
        for item in re.split(r",\s*", order_str):
            item = item.strip()
            parts = item.rsplit(None, 1)
            if len(parts) == 2 and parts[1].upper() == "DESC":
                sort_list.append((parts[0], -1))
            elif len(parts) == 2 and parts[1].upper() == "ASC":
                sort_list.append((parts[0], 1))
            else:
                sort_list.append((parts[0], 1))

    # -- Extract WHERE
    where_clause = ""
    m = re.search(r"\bWHERE\s+(.+)$", sql, re.IGNORECASE)
    if m:
        where_clause = m.group(1).strip()
        sql = sql[:m.start()].strip()

    # -- Extract FROM … collection
    collection = ""
    m = re.search(r"\bFROM\s+(\w+)", sql, re.IGNORECASE)
    if m:
        collection = m.group(1)
        sql = sql[:m.start()].strip()

    # -- Extract SELECT columns → projection
    projection = {}
    m = re.match(r"^SELECT\s+(.+)$", sql, re.IGNORECASE | re.DOTALL)
    if m:
        col_str = m.group(1).strip()
        if col_str != "*":
            # Handle aliases: col AS alias  or just col
            for col_expr in re.split(r",\s*", col_str):
                col_expr = col_expr.strip()
                alias_m = re.match(r"(\w+)\s+AS\s+(\w+)", col_expr, re.IGNORECASE)
                if alias_m:
                    projection[alias_m.group(1)] = 1
                else:
                    projection[col_expr] = 1

    # If _id not explicitly requested and we have a real projection, exclude it
    if projection and "_id" not in projection:
        projection["_id"] = 0

    mongo_filter = _parse_where(where_clause, params)

    return {
        "collection": collection,
        "projection": projection,
        "mongo_filter": mongo_filter,
        "sort": sort_list,
        "skip": offset_in_sql,
        "limit": limit_in_sql,
    }


def _infer_type(value) -> str:
    """Return a rough SQL-style type string from a Python value."""
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "DOUBLE"
    if isinstance(value, (bytes, bytearray)):
        return "BLOB"
    return "VARCHAR"


# ── Adapter ───────────────────────────────────────────────────────────────────

class MongoDBAdapter(DatabaseAdapter):
    """MongoDB database driver using pymongo.

    All standard tina4 Database methods work — SQL is translated to
    MongoDB operations internally.  JOINs are not supported.
    """

    def __init__(self):
        super().__init__()
        self._client = None   # pymongo.MongoClient
        self._db = None       # pymongo.database.Database
        self._session = None  # pymongo.client_session (for transactions)
        self._in_transaction: bool = False

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to MongoDB.

        Connection string: mongodb://user:pass@host:port/dbname
                           pymongo://user:pass@host:port/dbname

        Credentials priority: URL > username/password params.
        """
        try:
            import pymongo
        except ImportError:
            raise ImportError(
                "pymongo is required for MongoDB connections. "
                "Install: pip install pymongo"
            )

        # Normalise the scheme so MongoClient accepts it
        normalised = re.sub(r"^pymongo://", "mongodb://", connection_string)

        parsed = urlparse(normalised)

        # Inject credentials if not in the URL
        u = parsed.username or username or ""
        p = parsed.password or password or ""
        dbname = parsed.path.lstrip("/") if parsed.path else "tina4"

        # Build a clean mongodb:// URI for MongoClient
        if u and p:
            from urllib.parse import quote_plus
            auth = f"{quote_plus(u)}:{quote_plus(p)}@"
        elif u:
            from urllib.parse import quote_plus
            auth = f"{quote_plus(u)}@"
        else:
            auth = ""

        host = parsed.hostname or "localhost"
        port = parsed.port or 27017
        uri = f"mongodb://{auth}{host}:{port}/{dbname}"

        self._client = pymongo.MongoClient(uri, **kwargs)
        self._db = self._client[dbname]

    def close(self):
        if self._session:
            try:
                self._session.end_session()
            except Exception:
                pass
            self._session = None
        if self._client:
            self._client.close()
            self._client = None
        self._db = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _collection(self, name: str):
        """Return a pymongo collection object."""
        return self._db[name]

    def _session_kwargs(self) -> dict:
        """Return session kwarg dict if inside a transaction, else empty."""
        return {"session": self._session} if self._session else {}

    # ── Execute (write operations) ────────────────────────────────────────────

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        """Execute a write SQL statement against MongoDB.

        Supported: CREATE TABLE, DROP TABLE, INSERT INTO, UPDATE, DELETE.
        """
        params = list(params or [])
        sql_stripped = sql.strip().rstrip(";")
        sql_upper = sql_stripped.upper().lstrip()

        # CREATE TABLE → create collection (schema-less, so column defs ignored)
        m = re.match(
            r"CREATE\s+(?:TABLE|COLLECTION)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            sql_stripped, re.IGNORECASE
        )
        if m:
            col_name = m.group(1)
            if col_name not in self._db.list_collection_names(**self._session_kwargs()):
                self._db.create_collection(col_name, **self._session_kwargs())
            return DatabaseResult(affected_rows=0, sql=sql, adapter=self)

        # DROP TABLE → drop collection
        m = re.match(r"DROP\s+(?:TABLE|COLLECTION)\s+(?:IF\s+EXISTS\s+)?(\w+)",
                     sql_stripped, re.IGNORECASE)
        if m:
            self._db.drop_collection(m.group(1), **self._session_kwargs())
            return DatabaseResult(affected_rows=1, sql=sql, adapter=self)

        # INSERT INTO table (col1, col2, ...) VALUES (?, ?, ...)
        m = re.match(
            r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
            sql_stripped, re.IGNORECASE
        )
        if m:
            col_name = m.group(1)
            columns = [c.strip() for c in m.group(2).split(",")]
            placeholders = m.group(3)
            count = placeholders.count("?")
            values = [params.pop(0) if params else None for _ in range(count)]
            doc = dict(zip(columns, values))
            result = self._collection(col_name).insert_one(
                doc, **self._session_kwargs()
            )
            last_id = str(result.inserted_id)
            if not self._in_transaction and self.autocommit:
                pass  # MongoDB writes are immediately durable
            return DatabaseResult(
                affected_rows=1,
                last_id=last_id,
                sql=sql,
                adapter=self,
            )

        # UPDATE table SET col=?, col2=? WHERE ...
        m = re.match(
            r"UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$",
            sql_stripped, re.IGNORECASE | re.DOTALL
        )
        if m:
            col_name = m.group(1)
            set_clause = m.group(2).strip()
            where_clause = (m.group(3) or "").strip()

            # Parse SET clause — each assignment: col = ?
            set_doc = {}
            for assignment in re.split(r",\s*", set_clause):
                am = re.match(r"(\w+)\s*=\s*\?", assignment.strip())
                if am:
                    set_doc[am.group(1)] = params.pop(0) if params else None

            mongo_filter = _parse_where(where_clause, params)
            result = self._collection(col_name).update_many(
                mongo_filter, {"$set": set_doc}, **self._session_kwargs()
            )
            return DatabaseResult(
                affected_rows=result.modified_count,
                sql=sql,
                adapter=self,
            )

        # DELETE FROM table WHERE ...
        m = re.match(
            r"DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?$",
            sql_stripped, re.IGNORECASE | re.DOTALL
        )
        if m:
            col_name = m.group(1)
            where_clause = (m.group(2) or "").strip()
            mongo_filter = _parse_where(where_clause, params)
            result = self._collection(col_name).delete_many(
                mongo_filter, **self._session_kwargs()
            )
            return DatabaseResult(
                affected_rows=result.deleted_count,
                sql=sql,
                adapter=self,
            )

        # Unknown / unsupported statement — return empty result rather than crashing
        return DatabaseResult(affected_rows=0, sql=sql, adapter=self)

    # ── Fetch (read operations) ────────────────────────────────────────────────

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        """Execute a SELECT and return multiple rows."""
        params = list(params or [])
        sql = sql.strip().rstrip(";")

        parsed = _parse_select_sql(sql, params, limit, offset)
        col_name = parsed["collection"]
        if not col_name:
            return DatabaseResult(records=[], count=0, sql=sql, adapter=self)

        collection = self._collection(col_name)
        mongo_filter = parsed["mongo_filter"]
        projection = parsed["projection"] or None

        # Total count (before skip/limit)
        try:
            total = collection.count_documents(
                mongo_filter, **self._session_kwargs()
            )
        except Exception:
            total = 0

        cursor = collection.find(
            mongo_filter,
            projection,
            **self._session_kwargs()
        )

        if parsed["sort"]:
            cursor = cursor.sort(parsed["sort"])

        cursor = cursor.skip(parsed["skip"]).limit(parsed["limit"])

        rows = [_doc_to_dict(doc) for doc in cursor]

        return DatabaseResult(
            records=rows,
            count=total,
            sql=sql,
            adapter=self,
        )

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        """Execute a SELECT and return a single row or None."""
        params = list(params or [])
        sql = sql.strip().rstrip(";")

        parsed = _parse_select_sql(sql, params, limit=1, offset=0)
        col_name = parsed["collection"]
        if not col_name:
            return None

        collection = self._collection(col_name)
        projection = parsed["projection"] or None

        doc = collection.find_one(
            parsed["mongo_filter"],
            projection,
            **self._session_kwargs()
        )
        return _doc_to_dict(doc) if doc else None

    # ── Convenience write methods ─────────────────────────────────────────────

    def insert(self, table: str, data: dict) -> DatabaseResult:
        result = self._collection(table).insert_one(
            dict(data), **self._session_kwargs()
        )
        return DatabaseResult(
            affected_rows=1,
            last_id=str(result.inserted_id),
            sql=f"INSERT INTO {table}",
            adapter=self,
        )

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        mongo_filter = _parse_where(filter_sql, list(params or []))
        result = self._collection(table).update_many(
            mongo_filter, {"$set": data}, **self._session_kwargs()
        )
        return DatabaseResult(
            affected_rows=result.modified_count,
            sql=f"UPDATE {table}",
            adapter=self,
        )

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        mongo_filter = _parse_where(filter_sql, list(params or []))
        result = self._collection(table).delete_many(
            mongo_filter, **self._session_kwargs()
        )
        return DatabaseResult(
            affected_rows=result.deleted_count,
            sql=f"DELETE FROM {table}",
            adapter=self,
        )

    # ── Transactions ──────────────────────────────────────────────────────────

    def start_transaction(self):
        """Begin a MongoDB multi-document transaction (requires replica set)."""
        if self._session is None:
            self._session = self._client.start_session()
        self._session.start_transaction()
        self._in_transaction = True

    def commit(self):
        if self._session and self._in_transaction:
            self._session.commit_transaction()
        self._in_transaction = False

    def rollback(self):
        if self._session and self._in_transaction:
            self._session.abort_transaction()
        self._in_transaction = False

    # ── Schema inspection ─────────────────────────────────────────────────────

    def table_exists(self, name: str) -> bool:
        return name in self._db.list_collection_names(**self._session_kwargs())

    def get_tables(self) -> list[str]:
        return sorted(self._db.list_collection_names(**self._session_kwargs()))

    def get_columns(self, table: str) -> list[dict]:
        """Sample up to 100 documents and return all unique keys as columns.

        Type is inferred from the first non-None value encountered for each key.
        _id is always listed first as the primary key.
        """
        collection = self._collection(table)
        sample = list(collection.find({}, limit=100, **self._session_kwargs()))

        key_types: dict[str, str] = {}
        for doc in sample:
            for k, v in doc.items():
                if k not in key_types:
                    key_types[k] = _infer_type(v)

        if not key_types:
            # Empty collection — return a minimal schema hint
            return [{"name": "_id", "type": "VARCHAR", "nullable": False,
                     "default": None, "primary_key": True}]

        columns = []
        # _id first
        if "_id" in key_types:
            columns.append({
                "name": "_id",
                "type": key_types["_id"],
                "nullable": False,
                "default": None,
                "primary_key": True,
            })
        for k, t in key_types.items():
            if k == "_id":
                continue
            columns.append({
                "name": k,
                "type": t,
                "nullable": True,
                "default": None,
                "primary_key": False,
            })
        return columns

    # ── ID generation ─────────────────────────────────────────────────────────

    def get_next_id(self, table: str, pk_column: str = "id") -> int:
        """Atomically increment and return the next integer ID.

        Uses a tina4_sequences collection with findOneAndUpdate($inc) so the
        operation is race-safe on standalone instances and replica sets alike.
        Seeds from MAX(pk_column) on first use.
        """
        sequences = self._db["tina4_sequences"]
        seq_name = f"{table}.{pk_column}"

        # Check if the sequence document exists; seed if missing
        doc = sequences.find_one({"seq_name": seq_name}, **self._session_kwargs())
        if doc is None:
            # Seed from current max value in the collection
            seed_value = 0
            try:
                pipeline = [
                    {"$group": {"_id": None, "max_id": {"$max": f"${pk_column}"}}}
                ]
                agg = list(self._collection(table).aggregate(
                    pipeline, **self._session_kwargs()
                ))
                if agg and agg[0].get("max_id") is not None:
                    seed_value = int(agg[0]["max_id"])
            except Exception:
                pass

            try:
                sequences.insert_one(
                    {"seq_name": seq_name, "current_value": seed_value},
                    **self._session_kwargs()
                )
            except Exception:
                pass  # Race — another process inserted first; that's fine

        # Atomic increment
        result = sequences.find_one_and_update(
            {"seq_name": seq_name},
            {"$inc": {"current_value": 1}},
            return_document=True,  # pymongo.ReturnDocument.AFTER equivalent
            upsert=True,
            **self._session_kwargs()
        )
        return int(result["current_value"]) if result else 1

    def get_database_type(self) -> str:
        return "mongodb"

    def _supports_returning(self) -> bool:
        return False


# ── Utility ───────────────────────────────────────────────────────────────────

def _doc_to_dict(doc: dict) -> dict:
    """Convert a pymongo document to a plain dict, serialising ObjectId to str."""
    if doc is None:
        return {}
    out = {}
    for k, v in doc.items():
        # Serialise ObjectId (and any other non-JSON-safe types) to string
        type_name = type(v).__name__
        if type_name == "ObjectId":
            out[k] = str(v)
        elif type_name == "datetime":
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _doc_to_dict(v)
        elif isinstance(v, list):
            out[k] = [_doc_to_dict(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out
