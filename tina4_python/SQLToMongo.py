#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""SQL-to-MongoDB translation layer.

Translates a subset of SQL into MongoDB queries so that the tina4 Database
class can transparently use MongoDB as a backend while keeping the same
SQL-based API that all other engines use.

Supported SQL:
    SELECT columns FROM collection [WHERE ...] [ORDER BY ...] [LIMIT n] [OFFSET n]
    INSERT INTO collection (columns) VALUES (values)
    UPDATE collection SET col=val [WHERE ...]
    DELETE FROM collection [WHERE ...]
    CREATE TABLE / DROP TABLE (mapped to collection create/drop)

The parser is intentionally simple — it handles the SQL that tina4's Database,
ORM, and CRUD layers actually generate, not arbitrary SQL.
"""

__all__ = ["SQLToMongo"]

import re
from datetime import datetime


class SQLToMongo:
    """Translate SQL statements into MongoDB operations."""

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @staticmethod
    def translate(sql, params=None):
        """Parse a SQL statement and return a dict describing the MongoDB operation.

        Returns a dict with:
            type:       "find" | "insert" | "update" | "delete" | "count" |
                        "create_collection" | "drop_collection" | "aggregate"
            collection: str
            ... operation-specific keys (filter, projection, sort, doc, pipeline, etc.)
        """
        if params is None:
            params = []

        sql = sql.strip()
        # Replace ? placeholders with actual parameter values for parsing
        sql_resolved, params_remaining = SQLToMongo._resolve_placeholders(sql, params)

        upper = sql_resolved.upper().lstrip()

        if upper.startswith("SELECT"):
            return SQLToMongo._parse_select(sql_resolved, params_remaining)
        elif upper.startswith("INSERT"):
            return SQLToMongo._parse_insert(sql_resolved, params_remaining)
        elif upper.startswith("UPDATE"):
            return SQLToMongo._parse_update(sql_resolved, params_remaining)
        elif upper.startswith("DELETE"):
            return SQLToMongo._parse_delete(sql_resolved, params_remaining)
        elif upper.startswith("CREATE TABLE") or upper.startswith("CREATE COLLECTION"):
            return SQLToMongo._parse_create(sql_resolved)
        elif upper.startswith("DROP TABLE") or upper.startswith("DROP COLLECTION"):
            return SQLToMongo._parse_drop(sql_resolved)
        else:
            raise ValueError(f"Unsupported SQL statement: {sql_resolved[:80]}")

    # -----------------------------------------------------------------------
    # Placeholder resolution
    # -----------------------------------------------------------------------

    @staticmethod
    def _resolve_placeholders(sql, params):
        """Replace ? and %s placeholders with sentinel tokens.

        We replace placeholders with __PARAM_N__ tokens so we can parse
        the SQL structure, then resolve them to actual values when building
        the MongoDB query.
        """
        result = sql
        param_map = {}
        idx = 0
        for placeholder in ['?', '%s']:
            while placeholder in result and idx < len(params):
                token = f"__PARAM_{idx}__"
                param_map[token] = params[idx]
                result = result.replace(placeholder, token, 1)
                idx += 1
        return result, param_map

    @staticmethod
    def _resolve_value(val_str, param_map):
        """Resolve a value string to a Python value.

        Handles:
            - __PARAM_N__ tokens → actual parameter values
            - Quoted strings → str
            - Numbers → int or float
            - NULL → None
            - TRUE/FALSE → bool
        """
        val_str = val_str.strip()

        # Parameter token
        if val_str.startswith("__PARAM_") and val_str.endswith("__"):
            return param_map.get(val_str, val_str)

        # NULL
        if val_str.upper() == "NULL":
            return None

        # Boolean
        if val_str.upper() == "TRUE":
            return True
        if val_str.upper() == "FALSE":
            return False

        # Quoted string
        if (val_str.startswith("'") and val_str.endswith("'")) or \
           (val_str.startswith('"') and val_str.endswith('"')):
            return val_str[1:-1].replace("''", "'")

        # Number
        try:
            if '.' in val_str:
                return float(val_str)
            return int(val_str)
        except ValueError:
            pass

        # If it looks like a param token that wasn't resolved, return as-is
        return val_str

    # -----------------------------------------------------------------------
    # SELECT parser
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_select(sql, param_map):
        """Parse SELECT ... FROM ... [WHERE ...] [ORDER BY ...] [LIMIT ...] [OFFSET ...]"""

        # Check for COUNT(*) wrapper — used by pagination
        count_match = re.match(
            r'(?i)SELECT\s+COUNT\s*\(\s*\*\s*\)\s+AS\s+\w+\s+FROM\s*\(\s*(.+?)\s*\)\s+AS\s+\w+\s*$',
            sql, re.DOTALL
        )
        if count_match:
            inner = SQLToMongo._parse_select(count_match.group(1).strip(), param_map)
            return {
                "type": "count",
                "collection": inner["collection"],
                "filter": inner.get("filter", {}),
            }

        # Check for pagination wrapper: SELECT * FROM (inner) AS t LIMIT x OFFSET y
        wrap_match = re.match(
            r'(?i)SELECT\s+\*\s+FROM\s*\(\s*(.+?)\s*\)\s+AS\s+\w+\s+LIMIT\s+(\d+)\s+OFFSET\s+(\d+)\s*$',
            sql, re.DOTALL
        )
        if wrap_match:
            inner = SQLToMongo._parse_select(wrap_match.group(1).strip(), param_map)
            inner["limit"] = int(wrap_match.group(2))
            inner["skip"] = int(wrap_match.group(3))
            return inner

        # Standard SELECT
        # Extract ORDER BY (before LIMIT/OFFSET parsing)
        sort = {}
        order_match = re.search(r'(?i)\bORDER\s+BY\s+(.+?)(?:\s+LIMIT\b|\s+OFFSET\b|$)', sql, re.DOTALL)
        if order_match:
            sort = SQLToMongo._parse_order_by(order_match.group(1).strip(), param_map)
            # Remove ORDER BY from sql for further parsing
            sql = sql[:order_match.start()] + sql[order_match.end():]

        # Extract LIMIT
        limit = None
        limit_match = re.search(r'(?i)\bLIMIT\s+(\d+)', sql)
        if limit_match:
            limit = int(limit_match.group(1))
            sql = sql[:limit_match.start()] + sql[limit_match.end():]

        # Extract OFFSET
        skip = None
        offset_match = re.search(r'(?i)\bOFFSET\s+(\d+)', sql)
        if offset_match:
            skip = int(offset_match.group(1))
            sql = sql[:offset_match.start()] + sql[offset_match.end():]

        # Parse FROM and WHERE
        from_match = re.search(r'(?i)\bFROM\s+(\w+)', sql)
        if not from_match:
            raise ValueError(f"Cannot find FROM clause in: {sql[:80]}")
        collection = from_match.group(1)

        # Extract columns
        col_match = re.match(r'(?i)SELECT\s+(.*?)\s+FROM\b', sql, re.DOTALL)
        projection = None
        if col_match:
            cols_str = col_match.group(1).strip()
            if cols_str != '*':
                projection = SQLToMongo._parse_columns(cols_str)

        # Extract WHERE
        where_match = re.search(r'(?i)\bWHERE\s+(.+)$', sql.strip(), re.DOTALL)
        mongo_filter = {}
        if where_match:
            mongo_filter = SQLToMongo._parse_where(where_match.group(1).strip(), param_map)

        result = {
            "type": "find",
            "collection": collection,
            "filter": mongo_filter,
        }
        if projection:
            result["projection"] = projection
        if sort:
            result["sort"] = sort
        if limit is not None:
            result["limit"] = limit
        if skip is not None:
            result["skip"] = skip

        return result

    @staticmethod
    def _parse_columns(cols_str):
        """Parse column list into MongoDB projection dict."""
        projection = {}
        for col in SQLToMongo._split_commas(cols_str):
            col = col.strip()
            # Handle aliases: col AS alias, col alias
            alias_match = re.match(r'(?i)(.+?)\s+(?:AS\s+)?(\w+)$', col)
            if alias_match:
                col = alias_match.group(1).strip()
            # Strip table prefixes: t.col, u.col
            if '.' in col:
                col = col.split('.')[-1]
            # Strip quotes
            col = col.strip('`"[]')
            if col != '*':
                projection[col] = 1
        return projection if projection else None

    @staticmethod
    def _parse_order_by(order_str, param_map):
        """Parse ORDER BY clause into MongoDB sort dict."""
        sort = {}
        for part in SQLToMongo._split_commas(order_str):
            part = part.strip()
            # Remove (SELECT NULL) — MSSQL default
            if 'SELECT' in part.upper():
                continue
            desc = 1
            if part.upper().endswith(' DESC'):
                desc = -1
                part = part[:-5].strip()
            elif part.upper().endswith(' ASC'):
                part = part[:-4].strip()
            # Strip table prefix
            if '.' in part:
                part = part.split('.')[-1]
            part = part.strip('`"[]')
            if part:
                sort[part] = desc
        return sort

    # -----------------------------------------------------------------------
    # WHERE clause parser
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_where(where_str, param_map):
        """Parse a WHERE clause into a MongoDB filter dict.

        Handles:
            col = val           → {col: val}
            col != val          → {col: {$ne: val}}
            col <> val          → {col: {$ne: val}}
            col > val           → {col: {$gt: val}}
            col >= val          → {col: {$gte: val}}
            col < val           → {col: {$lt: val}}
            col <= val          → {col: {$lte: val}}
            col LIKE '%val%'    → {col: {$regex: val, $options: 'i'}}
            col IN (a, b, c)    → {col: {$in: [a, b, c]}}
            col IS NULL         → {col: None}
            col IS NOT NULL     → {col: {$ne: None}}
            col BETWEEN a AND b → {col: {$gte: a, $lte: b}}
            ... AND ...         → {$and: [...]}
            ... OR ...          → {$or: [...]}
            (...) grouping      → recursive parse
        """
        where_str = where_str.strip()

        # Handle OR (lowest precedence)
        or_parts = SQLToMongo._split_logical(where_str, 'OR')
        if len(or_parts) > 1:
            return {"$or": [SQLToMongo._parse_where(p, param_map) for p in or_parts]}

        # Handle AND — but protect BETWEEN ... AND ... from being split
        # Replace BETWEEN...AND with a placeholder before splitting
        protected = re.sub(
            r'(?i)\bBETWEEN\b\s+(\S+)\s+AND\s+(\S+)',
            r'BETWEEN \1 __BETWEEN_AND__ \2',
            where_str
        )
        and_parts = SQLToMongo._split_logical(protected, 'AND')
        # Restore BETWEEN...AND
        and_parts = [p.replace('__BETWEEN_AND__', 'AND') for p in and_parts]
        if len(and_parts) > 1:
            filters = [SQLToMongo._parse_where(p, param_map) for p in and_parts]
            # Merge simple filters if no key conflicts
            merged = {}
            needs_and = False
            for f in filters:
                for k in f:
                    if k in merged or k.startswith('$'):
                        needs_and = True
                        break
                if needs_and:
                    break
            if needs_and:
                return {"$and": filters}
            for f in filters:
                merged.update(f)
            return merged

        # Handle parenthesised group
        if where_str.startswith('(') and where_str.endswith(')'):
            return SQLToMongo._parse_where(where_str[1:-1].strip(), param_map)

        # Single condition
        return SQLToMongo._parse_condition(where_str, param_map)

    @staticmethod
    def _parse_condition(cond, param_map):
        """Parse a single WHERE condition into a MongoDB filter."""
        cond = cond.strip()

        # IS NOT NULL
        m = re.match(r'(?i)(\w+(?:\.\w+)?)\s+IS\s+NOT\s+NULL', cond)
        if m:
            col = SQLToMongo._clean_col(m.group(1))
            return {col: {"$ne": None}}

        # IS NULL
        m = re.match(r'(?i)(\w+(?:\.\w+)?)\s+IS\s+NULL', cond)
        if m:
            col = SQLToMongo._clean_col(m.group(1))
            return {col: None}

        # BETWEEN
        m = re.match(r'(?i)(\w+(?:\.\w+)?)\s+BETWEEN\s+(.+?)\s+AND\s+(.+)', cond)
        if m:
            col = SQLToMongo._clean_col(m.group(1))
            low = SQLToMongo._resolve_value(m.group(2), param_map)
            high = SQLToMongo._resolve_value(m.group(3), param_map)
            return {col: {"$gte": low, "$lte": high}}

        # IN (...)
        m = re.match(r'(?i)(\w+(?:\.\w+)?)\s+IN\s*\((.+)\)', cond)
        if m:
            col = SQLToMongo._clean_col(m.group(1))
            vals = [SQLToMongo._resolve_value(v.strip(), param_map)
                    for v in SQLToMongo._split_commas(m.group(2))]
            return {col: {"$in": vals}}

        # NOT IN (...)
        m = re.match(r'(?i)(\w+(?:\.\w+)?)\s+NOT\s+IN\s*\((.+)\)', cond)
        if m:
            col = SQLToMongo._clean_col(m.group(1))
            vals = [SQLToMongo._resolve_value(v.strip(), param_map)
                    for v in SQLToMongo._split_commas(m.group(2))]
            return {col: {"$nin": vals}}

        # LIKE / ILIKE
        m = re.match(r'(?i)(?:cast\s*\(.+?\s+as\s+\w+(?:\(\d+\))?\s*\)|(\w+(?:\.\w+)?))\s+(I?LIKE)\s+(.+)', cond)
        if m:
            col_raw = m.group(1)
            # If cast() was used, extract the column name from inside
            if col_raw is None:
                cast_match = re.match(r'(?i)cast\s*\((\w+(?:\.\w+)?)', cond)
                col_raw = cast_match.group(1) if cast_match else "unknown"
            col = SQLToMongo._clean_col(col_raw)
            pattern = SQLToMongo._resolve_value(m.group(3), param_map)
            if isinstance(pattern, str):
                # Convert SQL LIKE to regex
                regex = SQLToMongo._like_to_regex(pattern)
                return {col: {"$regex": regex, "$options": "i"}}
            return {col: pattern}

        # Comparison operators: >=, <=, <>, !=, >, <, =
        m = re.match(r'(\w+(?:\.\w+)?)\s*(>=|<=|<>|!=|>|<|=)\s*(.+)', cond)
        if m:
            col = SQLToMongo._clean_col(m.group(1))
            op = m.group(2)
            val = SQLToMongo._resolve_value(m.group(3), param_map)
            op_map = {
                '=': None,  # direct match
                '!=': '$ne',
                '<>': '$ne',
                '>': '$gt',
                '>=': '$gte',
                '<': '$lt',
                '<=': '$lte',
            }
            mongo_op = op_map.get(op)
            if mongo_op is None:
                return {col: val}
            return {col: {mongo_op: val}}

        # Fallback — return empty filter
        return {}

    @staticmethod
    def _like_to_regex(pattern):
        """Convert SQL LIKE pattern to MongoDB regex."""
        # Replace SQL wildcards with placeholders before escaping
        pattern = pattern.replace('%', '\x00').replace('_', '\x01')
        # Escape regex special chars
        regex = re.escape(pattern)
        # Restore SQL wildcards as regex equivalents
        regex = regex.replace('\x00', '.*').replace('\x01', '.')
        return f"^{regex}$"

    # -----------------------------------------------------------------------
    # INSERT parser
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_insert(sql, param_map):
        """Parse INSERT INTO collection (cols) VALUES (vals) [RETURNING ...]"""
        # Strip RETURNING clause
        returning = None
        ret_match = re.search(r'(?i)\bRETURNING\b\s+(.+)$', sql)
        if ret_match:
            returning = ret_match.group(1).strip().rstrip(';')
            sql = sql[:ret_match.start()].strip()

        m = re.match(
            r'(?i)INSERT\s+INTO\s+(\w+)\s*\((.+?)\)\s*VALUES\s*\((.+)\)',
            sql, re.DOTALL
        )
        if not m:
            raise ValueError(f"Cannot parse INSERT: {sql[:80]}")

        collection = m.group(1)
        columns = [c.strip().strip('`"[]') for c in SQLToMongo._split_commas(m.group(2))]
        values = [SQLToMongo._resolve_value(v.strip(), param_map)
                  for v in SQLToMongo._split_commas(m.group(3))]

        doc = dict(zip(columns, values))

        result = {
            "type": "insert",
            "collection": collection,
            "document": doc,
        }
        if returning:
            result["returning"] = returning
        return result

    # -----------------------------------------------------------------------
    # UPDATE parser
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_update(sql, param_map):
        """Parse UPDATE collection SET col=val, ... [WHERE ...]"""
        # Strip RETURNING clause
        returning = None
        ret_match = re.search(r'(?i)\bRETURNING\b\s+(.+)$', sql)
        if ret_match:
            returning = ret_match.group(1).strip().rstrip(';')
            sql = sql[:ret_match.start()].strip()

        m = re.match(r'(?i)UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$', sql, re.DOTALL)
        if not m:
            raise ValueError(f"Cannot parse UPDATE: {sql[:80]}")

        collection = m.group(1)
        set_str = m.group(2).strip()
        where_str = m.group(3)

        # Parse SET clause
        update_doc = {}
        for assignment in SQLToMongo._split_commas(set_str):
            eq_match = re.match(r'(\w+)\s*=\s*(.+)', assignment.strip())
            if eq_match:
                col = eq_match.group(1).strip().strip('`"[]')
                val = SQLToMongo._resolve_value(eq_match.group(2), param_map)
                update_doc[col] = val

        mongo_filter = {}
        if where_str:
            mongo_filter = SQLToMongo._parse_where(where_str.strip(), param_map)

        result = {
            "type": "update",
            "collection": collection,
            "filter": mongo_filter,
            "update": {"$set": update_doc},
        }
        if returning:
            result["returning"] = returning
        return result

    # -----------------------------------------------------------------------
    # DELETE parser
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_delete(sql, param_map):
        """Parse DELETE FROM collection [WHERE ...]"""
        # Strip RETURNING clause
        returning = None
        ret_match = re.search(r'(?i)\bRETURNING\b\s+(.+)$', sql)
        if ret_match:
            returning = ret_match.group(1).strip().rstrip(';')
            sql = sql[:ret_match.start()].strip()

        m = re.match(r'(?i)DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?$', sql, re.DOTALL)
        if not m:
            raise ValueError(f"Cannot parse DELETE: {sql[:80]}")

        collection = m.group(1)
        where_str = m.group(2)

        mongo_filter = {}
        if where_str:
            mongo_filter = SQLToMongo._parse_where(where_str.strip(), param_map)

        result = {
            "type": "delete",
            "collection": collection,
            "filter": mongo_filter,
        }
        if returning:
            result["returning"] = returning
        return result

    # -----------------------------------------------------------------------
    # CREATE / DROP
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_create(sql):
        """Parse CREATE TABLE/COLLECTION — just extract collection name."""
        m = re.match(r'(?i)CREATE\s+(?:TABLE|COLLECTION)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', sql)
        if not m:
            raise ValueError(f"Cannot parse CREATE: {sql[:80]}")
        return {"type": "create_collection", "collection": m.group(1)}

    @staticmethod
    def _parse_drop(sql):
        """Parse DROP TABLE/COLLECTION — just extract collection name."""
        m = re.match(r'(?i)DROP\s+(?:TABLE|COLLECTION)\s+(?:IF\s+EXISTS\s+)?(\w+)', sql)
        if not m:
            raise ValueError(f"Cannot parse DROP: {sql[:80]}")
        return {"type": "drop_collection", "collection": m.group(1)}

    # -----------------------------------------------------------------------
    # Utility helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_col(col):
        """Strip table prefix and quotes from a column name."""
        if '.' in col:
            col = col.split('.')[-1]
        return col.strip('`"[]')

    @staticmethod
    def _split_commas(s):
        """Split on commas, respecting parentheses and quotes."""
        parts = []
        depth = 0
        current = []
        in_quote = None
        for ch in s:
            if in_quote:
                current.append(ch)
                if ch == in_quote:
                    in_quote = None
                continue
            if ch in ("'", '"'):
                in_quote = ch
                current.append(ch)
                continue
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            if ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    @staticmethod
    def _split_logical(where_str, keyword):
        """Split WHERE string on AND/OR keyword, respecting parentheses."""
        parts = []
        depth = 0
        current = []
        tokens = re.split(r'(\s+)', where_str)
        i = 0
        kw_upper = keyword.upper()
        while i < len(tokens):
            token = tokens[i]
            if token.strip() == '':
                current.append(token)
                i += 1
                continue
            # Track parentheses
            for ch in token:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
            if depth == 0 and token.upper() == kw_upper:
                parts.append(''.join(current).strip())
                current = []
            else:
                current.append(token)
            i += 1
        remainder = ''.join(current).strip()
        if remainder:
            parts.append(remainder)
        return parts
