# Tina4 DocStore — pymongo-style document storage with a zero-config SQLite fallback.
"""
A document store with the everyday pymongo collection API, backed by SQLite's
JSON1 extension when no MongoDB server is configured.

    from tina4_python.docstore import get_collection, ObjectId

    orders = get_collection("orders")          # SqliteCollection when no Mongo configured
    oid = orders.insert_one({"customer_id": 1, "total": 9.99}).inserted_id
    for o in orders.find({"customer_id": {"$in": [1, 2]}}).sort("created_at", -1).limit(10):
        ...
    orders.update_one({"_id": oid}, {"$set": {"status": "shipped"}})

`get_collection(name)` returns a real pymongo `Collection` when a Mongo URI is
configured (TINA4_MONGO_URI, else TINA4_SESSION_MONGO_URI; TINA4_SESSION_MONGO_URL
is accepted as a legacy alias), and otherwise a
`SqliteCollection` backed by a local SQLite file. This mirrors the file-based
fallbacks the queue, cache, and session subsystems already provide: an app that
talks to Mongo in production runs serverless in local dev with no code change -
only the backend differs.

Design (the SQLite backend):
    - Each collection is a table `(_id TEXT PRIMARY KEY, doc TEXT)`; `doc` is JSON.
    - Query filters are pushed down to SQL over `json_extract(doc, '$.field')`
      (indexed + lazy, not a full in-memory scan), supporting equality, $in/$nin,
      $gt/$gte/$lt/$lte, $ne, $exists, $regex, and implicit-AND / $or / $and.
    - Updates: $set, $unset, $inc, and full-document replace.
    - Cursors: sort / limit / skip / projection.
    - IDs are a built-in 12-byte ObjectId (zero-dependency; interchangeable with
      bson.ObjectId as a 24-hex string).

Type round-trip is by value, not by wrapper object, so json_extract stays
queryable and sortable: a datetime is stored as an ISO-8601 UTC string and an
ObjectId as its 24-hex string, and reads rehydrate a strict-ISO string back to
datetime and a 24-hex string back to ObjectId. That keeps range queries and
sorts working on date and id fields - the trade-off (a plain 24-hex / ISO string
becomes an ObjectId / datetime on read) is acceptable for the local dev store.

Deliberate non-goals: aggregation pipeline, $elemMatch, geo. This is the
everyday CRUD + filter subset, not full Mongo parity.
"""
import os
import re
import json
import time
import struct
import secrets
import sqlite3
import threading
from datetime import datetime, timezone


class InvalidId(ValueError):
    """Raised when a value cannot be parsed as an ObjectId (mirrors bson.errors.InvalidId)."""


class _NativeObjectId:
    """A 12-byte MongoDB-style ObjectId, with no external dependency.

    Layout: 4-byte big-endian seconds since epoch, 5-byte per-process random,
    3-byte big-endian counter. Renders as a 24-char hex string, so it is
    interchangeable with bson.ObjectId wherever the string form is used.
    """

    _counter = secrets.randbits(24)
    _process = secrets.token_bytes(5)
    _lock = threading.Lock()

    __slots__ = ("_bytes",)

    def __init__(self, oid=None):
        if oid is None:
            self._bytes = self._generate()
        elif isinstance(oid, _NativeObjectId):
            self._bytes = oid._bytes
        elif isinstance(oid, (bytes, bytearray)):
            if len(oid) != 12:
                raise InvalidId("ObjectId bytes must be exactly 12 bytes")
            self._bytes = bytes(oid)
        elif isinstance(oid, str):
            if not _OID_RE.match(oid):
                raise InvalidId(f"{oid!r} is not a valid 24-character hex ObjectId")
            self._bytes = bytes.fromhex(oid)
        else:
            raise InvalidId(f"cannot make an ObjectId from {type(oid).__name__}")

    @classmethod
    def _generate(cls) -> bytes:
        ts = struct.pack(">I", int(time.time()))
        with cls._lock:
            cls._counter = (cls._counter + 1) & 0xFFFFFF
            counter = cls._counter
        return ts + cls._process + struct.pack(">I", counter)[1:]

    @classmethod
    def is_valid(cls, value) -> bool:
        try:
            _NativeObjectId(value)
            return True
        except (InvalidId, TypeError):
            return False

    @property
    def binary(self) -> bytes:
        return self._bytes

    @property
    def generation_time(self) -> datetime:
        ts = struct.unpack(">I", self._bytes[:4])[0]
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def __str__(self) -> str:
        return self._bytes.hex()

    def __repr__(self) -> str:
        return f"ObjectId('{self._bytes.hex()}')"

    def __eq__(self, other) -> bool:
        return isinstance(other, _NativeObjectId) and other._bytes == self._bytes

    def __hash__(self) -> int:
        return hash(self._bytes)



# The PUBLIC ObjectId is the DRIVER'S type whenever the driver is installed.
#
# MEASURED 2026-08-03 against a real MongoDB: the framework exported its own
# ObjectId class, pymongo received it, and refused -
#
#     InvalidDocument: cannot encode object: ObjectId('6a70a6d8...')
#
# even though bson.ObjectId(str(oid)) encodes fine. The VALUE was always right;
# the TYPE was wrong. So the documented way to construct an id worked on the
# local SQLite fallback and failed the moment TINA4_MONGO_URI was set - the
# swap breaking at the exact call site it advertises (ADR-0024).
#
# The native implementation stays, because it is what makes the zero-dependency
# install work at all. It is simply not the public name when a real bson is
# present. Note the internal references above were re-pointed at
# _NativeObjectId first: leaving them on the public name would have made this
# rebind silently break its own isinstance and __eq__.
try:  # pragma: no cover - depends on whether the driver is installed
    from bson import ObjectId  # type: ignore[assignment]
    from bson.errors import InvalidId  # type: ignore[assignment]
except ImportError:  # zero-dependency install: our own is the real one
    ObjectId = _NativeObjectId

# ── Value encoding: keep scalars queryable, rehydrate types on read ──────────

_OID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def encode_value(value):
    """Python value -> JSON-serialisable, sortable scalar form (for storage/queries)."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {k: encode_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_value(v) for v in value]
    return value


def decode_value(value):
    """Stored JSON value -> Python, rehydrating ObjectId (24-hex) and datetime (ISO)."""
    if isinstance(value, str):
        if _OID_RE.match(value):
            return ObjectId(value)
        if _ISO_RE.match(value):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
        return value
    if isinstance(value, dict):
        return {k: decode_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    return value


def _id_key(value) -> str:
    """Canonical string key for the _id column."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    return str(value)


# ── Query translation: Mongo filter dict -> SQL WHERE over json_extract ──────

_COMPARATORS = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}


def _path(field: str) -> str:
    """Field name -> a JSON path. Dotted names address nested keys."""
    # json_extract path; quote each segment to allow keys with odd characters
    segments = field.split(".")
    return "$." + ".".join(f'"{s}"' if not s.isidentifier() else s for s in segments)


def _extract(field: str) -> str:
    return f"json_extract(doc, '{_path(field)}')"


def _type(field: str) -> str:
    return f"json_type(doc, '{_path(field)}')"


def compile_filter(query: dict):
    """Compile a Mongo-style filter dict into (sql_fragment, params).

    Returns ('1=1', []) for an empty filter. Supports implicit AND across keys,
    $or / $and, and the per-field operator set.
    """
    if not query:
        return "1=1", []

    clauses = []
    params = []
    for key, value in query.items():
        if key == "$or" or key == "$and":
            joiner = " OR " if key == "$or" else " AND "
            subs = []
            for sub in value:
                frag, p = compile_filter(sub)
                subs.append(f"({frag})")
                params.extend(p)
            if subs:
                clauses.append("(" + joiner.join(subs) + ")")
            continue

        if isinstance(value, dict) and value and all(k.startswith("$") for k in value):
            for op, operand in value.items():
                frag, p = _compile_op(key, op, operand)
                clauses.append(frag)
                params.extend(p)
        else:
            # equality
            if value is None:
                clauses.append(f"{_extract(key)} IS NULL")
            else:
                clauses.append(f"{_extract(key)} = ?")
                params.append(_bind(value))

    return (" AND ".join(clauses) if clauses else "1=1"), params


def _compile_op(field: str, op: str, operand):
    ex = _extract(field)
    if op in _COMPARATORS:
        return f"{ex} {_COMPARATORS[op]} ?", [_bind(operand)]
    if op == "$eq":
        if operand is None:
            return f"{ex} IS NULL", []
        return f"{ex} = ?", [_bind(operand)]
    if op == "$ne":
        if operand is None:
            return f"{ex} IS NOT NULL", []
        return f"({ex} <> ? OR {ex} IS NULL)", [_bind(operand)]
    if op == "$in":
        items = list(operand) or []
        if not items:
            return "0", []
        placeholders = ",".join("?" for _ in items)
        return f"{ex} IN ({placeholders})", [_bind(v) for v in items]
    if op == "$nin":
        items = list(operand) or []
        if not items:
            return "1", []
        placeholders = ",".join("?" for _ in items)
        return f"({ex} NOT IN ({placeholders}) OR {ex} IS NULL)", [_bind(v) for v in items]
    if op == "$exists":
        # json_type is NULL when the path is absent; present-but-null still has a type
        return (f"{_type(field)} IS NOT NULL" if operand else f"{_type(field)} IS NULL"), []
    if op == "$regex":
        pattern = operand
        if isinstance(operand, dict):  # not expected, but be safe
            pattern = operand.get("$regex", "")
        return f"{ex} REGEXP ?", [str(pattern)]
    raise ValueError(f"DocStore: unsupported query operator {op!r}")


def _bind(value):
    """Bind a Python value for comparison against json_extract output."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (ObjectId, datetime)):
        return encode_value(value)
    if isinstance(value, (int, float, str)) or value is None:
        return value
    return json.dumps(encode_value(value))


def _regexp(pattern, value):
    if value is None:
        return 0
    try:
        return 1 if re.search(pattern, str(value)) else 0
    except re.error:
        return 0


# ── Cursor ───────────────────────────────────────────────────────────────────

class Cursor:
    """Lazy result cursor. Builds and runs SQL only when iterated."""

    def __init__(self, collection, where, params, projection=None):
        self._c = collection
        self._where = where
        self._params = params
        self._projection = projection
        self._sort = []
        self._limit = None
        self._skip = 0

    def sort(self, key_or_list, direction=1):
        if isinstance(key_or_list, str):
            self._sort.append((key_or_list, direction))
        else:
            for k, d in key_or_list:
                self._sort.append((k, d))
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    def skip(self, n):
        self._skip = int(n)
        return self

    def _build_sql(self):
        sql = f"SELECT doc FROM {self._c._q} WHERE {self._where}"
        if self._sort:
            order = ", ".join(
                f"{_extract(k)} {'DESC' if d < 0 else 'ASC'}" for k, d in self._sort
            )
            sql += f" ORDER BY {order}"
        if self._limit is not None:
            sql += f" LIMIT {int(self._limit)}"
            if self._skip:
                sql += f" OFFSET {int(self._skip)}"
        elif self._skip:
            sql += f" LIMIT -1 OFFSET {int(self._skip)}"
        return sql

    def __iter__(self):
        cur = self._c._conn.execute(self._build_sql(), self._params)
        for (doc_text,) in cur:
            yield self._c._load(doc_text, self._projection)

    def to_list(self, length=None):
        out = list(self)
        return out if length is None else out[:length]


class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class InsertManyResult:
    def __init__(self, inserted_ids):
        self.inserted_ids = inserted_ids


class UpdateResult:
    def __init__(self, matched_count, modified_count, upserted_id=None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


# ── Collection ─────────────────────────────────────────────────────────────

class SqliteCollection:
    """A SQLite-backed collection exposing the everyday pymongo API."""

    def __init__(self, conn, name):
        self._conn = conn
        self._name = name
        # quoted, validated table identifier
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise ValueError(f"DocStore: invalid collection name {name!r}")
        self._q = f'"{name}"'
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._q} (_id TEXT PRIMARY KEY, doc TEXT NOT NULL)"
        )

    # -- helpers --
    def _dump(self, document: dict) -> str:
        return json.dumps(encode_value(document), separators=(",", ":"))

    def _load(self, doc_text: str, projection=None) -> dict:
        doc = decode_value(json.loads(doc_text))
        return _project(doc, projection) if projection else doc

    # -- writes --
    def insert_one(self, document: dict) -> InsertOneResult:
        doc = dict(document)
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self._conn.execute(
            f"INSERT INTO {self._q} (_id, doc) VALUES (?, ?)",
            [_id_key(doc["_id"]), self._dump(doc)],
        )
        self._conn.commit()
        return InsertOneResult(doc["_id"])

    def insert_many(self, documents) -> InsertManyResult:
        ids = []
        rows = []
        for document in documents:
            doc = dict(document)
            if "_id" not in doc:
                doc["_id"] = ObjectId()
            ids.append(doc["_id"])
            rows.append((_id_key(doc["_id"]), self._dump(doc)))
        self._conn.executemany(f"INSERT INTO {self._q} (_id, doc) VALUES (?, ?)", rows)
        self._conn.commit()
        return InsertManyResult(ids)

    # -- reads --
    def find(self, filter=None, projection=None) -> Cursor:
        where, params = compile_filter(filter or {})
        return Cursor(self, where, params, projection)

    def find_one(self, filter=None, projection=None):
        results = self.find(filter, projection).limit(1).to_list()
        return results[0] if results else None

    def count_documents(self, filter=None) -> int:
        where, params = compile_filter(filter or {})
        row = self._conn.execute(
            f"SELECT count(*) FROM {self._q} WHERE {where}", params
        ).fetchone()
        return int(row[0])

    def estimated_document_count(self) -> int:
        return int(self._conn.execute(f"SELECT count(*) FROM {self._q}").fetchone()[0])

    def distinct(self, key, filter=None):
        seen = []
        for doc in self.find(filter):
            v = doc.get(key)
            if v not in seen:
                seen.append(v)
        return seen

    # -- updates (filter pushed to SQL; mutation applied per matched doc) --
    def _matching_rows(self, filter):
        where, params = compile_filter(filter or {})
        return self._conn.execute(
            f"SELECT _id, doc FROM {self._q} WHERE {where}", params
        ).fetchall()

    def update_one(self, filter, update, upsert=False) -> UpdateResult:
        rows = self._conn.execute(*self._first_match_sql(filter)).fetchall()
        if not rows:
            if upsert:
                return self._do_upsert(filter, update)
            return UpdateResult(0, 0)
        old_id, doc_text = rows[0]
        doc = decode_value(json.loads(doc_text))
        new_doc = _apply_update(doc, update)
        modified = self._write_back(old_id, new_doc)
        return UpdateResult(1, 1 if modified else 0)

    def update_many(self, filter, update, upsert=False) -> UpdateResult:
        rows = self._matching_rows(filter)
        if not rows and upsert:
            return self._do_upsert(filter, update)
        matched = 0
        modified = 0
        for old_id, doc_text in rows:
            matched += 1
            doc = decode_value(json.loads(doc_text))
            new_doc = _apply_update(doc, update)
            if self._write_back(old_id, new_doc):
                modified += 1
        return UpdateResult(matched, modified)

    def replace_one(self, filter, replacement, upsert=False) -> UpdateResult:
        rows = self._conn.execute(*self._first_match_sql(filter)).fetchall()
        if not rows:
            if upsert:
                doc = dict(replacement)
                if "_id" not in doc:
                    doc["_id"] = ObjectId()
                self.insert_one(doc)
                return UpdateResult(0, 0, upserted_id=doc["_id"])
            return UpdateResult(0, 0)
        old_id, doc_text = rows[0]
        doc = dict(replacement)
        doc.setdefault("_id", decode_value(json.loads(doc_text)).get("_id"))
        self._write_back(old_id, doc)
        return UpdateResult(1, 1)

    def _first_match_sql(self, filter):
        where, params = compile_filter(filter or {})
        return (f"SELECT _id, doc FROM {self._q} WHERE {where} LIMIT 1", params)

    def _write_back(self, old_id, new_doc) -> bool:
        new_key = _id_key(new_doc["_id"])
        self._conn.execute(
            f"UPDATE {self._q} SET _id = ?, doc = ? WHERE _id = ?",
            [new_key, self._dump(new_doc), old_id],
        )
        self._conn.commit()
        return True

    def _do_upsert(self, filter, update) -> UpdateResult:
        # Seed a document from the filter's equality terms, then apply the update.
        seed = {k: v for k, v in (filter or {}).items() if not k.startswith("$") and not isinstance(v, dict)}
        doc = _apply_update(seed, update)
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self.insert_one(doc)
        return UpdateResult(0, 0, upserted_id=doc["_id"])

    # -- deletes --
    def delete_one(self, filter) -> DeleteResult:
        row = self._conn.execute(*self._first_match_sql(filter)).fetchone()
        if not row:
            return DeleteResult(0)
        self._conn.execute(f"DELETE FROM {self._q} WHERE _id = ?", [row[0]])
        self._conn.commit()
        return DeleteResult(1)

    def delete_many(self, filter) -> DeleteResult:
        where, params = compile_filter(filter or {})
        cur = self._conn.execute(f"DELETE FROM {self._q} WHERE {where}", params)
        self._conn.commit()
        return DeleteResult(cur.rowcount)

    def drop(self):
        self._conn.execute(f"DROP TABLE IF EXISTS {self._q}")
        self._conn.commit()


def _project(doc: dict, projection: dict) -> dict:
    if not projection:
        return doc
    include = {k for k, v in projection.items() if v and k != "_id"}
    exclude = {k for k, v in projection.items() if not v}
    if include:
        out = {k: doc[k] for k in include if k in doc}
        if projection.get("_id", 1) and "_id" in doc:
            out["_id"] = doc["_id"]
        return out
    # exclusion projection
    return {k: v for k, v in doc.items() if k not in exclude}


def _apply_update(doc: dict, update: dict) -> dict:
    if not any(k.startswith("$") for k in update):
        # full-document replace (keep the existing _id)
        new = dict(update)
        new.setdefault("_id", doc.get("_id"))
        return new
    new = dict(doc)
    for op, fields in update.items():
        if op == "$set":
            for k, v in fields.items():
                _set_path(new, k, v)
        elif op == "$unset":
            for k in fields:
                _unset_path(new, k)
        elif op == "$inc":
            for k, v in fields.items():
                _set_path(new, k, (_get_path(new, k) or 0) + v)
        else:
            raise ValueError(f"DocStore: unsupported update operator {op!r}")
    return new


def _set_path(doc, dotted, value):
    parts = dotted.split(".")
    node = doc
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _unset_path(doc, dotted):
    parts = dotted.split(".")
    node = doc
    for p in parts[:-1]:
        node = node.get(p) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
    node.pop(parts[-1], None)


def _get_path(doc, dotted):
    parts = dotted.split(".")
    node = doc
    for p in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node


# ── Database + selection ─────────────────────────────────────────────────────

class SqliteDatabase:
    """A SQLite-backed document database (a file of collection tables)."""

    def __init__(self, path: str = None):
        self.path = path or os.environ.get("TINA4_DOC_STORE_PATH", "data/tina4_docstore.db")
        if self.path != ":memory:":
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.create_function("regexp", 2, _regexp)
        self._collections = {}

    def get_collection(self, name) -> SqliteCollection:
        if name not in self._collections:
            self._collections[name] = SqliteCollection(self._conn, name)
        return self._collections[name]

    # dict-style + attribute-style access, like pymongo's Database
    def __getitem__(self, name):
        return self.get_collection(name)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get_collection(name)

    def list_collection_names(self):
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self):
        self._conn.close()


def _mongo_uri() -> str:
    """The configured Mongo URI, reusing the app-wide queue/session env vars.

    TINA4_MONGO_URI is the canonical app-wide name; TINA4_SESSION_MONGO_URI is
    the session-layer name; TINA4_SESSION_MONGO_URL is a back-compat alias.
    """
    return (
        os.environ.get("TINA4_MONGO_URI")
        or os.environ.get("TINA4_SESSION_MONGO_URI")
        or os.environ.get("TINA4_SESSION_MONGO_URL")
        or ""
    ).strip()


def is_serverless() -> bool:
    """True when no Mongo is configured, so the SQLite fallback is in effect."""
    if not _mongo_uri():
        return True
    try:
        import pymongo  # noqa: F401
        return False
    except ImportError:
        # A URI is set but the driver is absent: degrade to the local store
        # rather than crash, and say so once.
        return True


_default_db = None
_default_lock = threading.Lock()


def _get_db() -> SqliteDatabase:
    global _default_db
    if _default_db is None:
        with _default_lock:
            if _default_db is None:
                _default_db = SqliteDatabase()
    return _default_db


def get_collection(name: str):
    """Return a collection for `name`.

    Real pymongo `Collection` when a Mongo URI is configured (and pymongo is
    installed); otherwise a `SqliteCollection` backed by the local SQLite file.
    Same call sites either way - only the backend differs.
    """
    if is_serverless():
        return _get_db().get_collection(name)
    import pymongo
    uri = _mongo_uri()
    db_name = (
        os.environ.get("TINA4_MONGO_DB")
        or os.environ.get("TINA4_SESSION_MONGO_DB")
        or "tina4"
    )
    client = pymongo.MongoClient(uri)
    return client[db_name][name]


def reset_default_store():
    """Drop the cached default SQLite store (test helper)."""
    global _default_db
    with _default_lock:
        if _default_db is not None:
            _default_db.close()
        _default_db = None


__all__ = [
    "get_collection", "ObjectId", "InvalidId",
    "SqliteDatabase", "SqliteCollection", "Cursor",
    "is_serverless", "reset_default_store",
    "encode_value", "decode_value", "compile_filter",
]
