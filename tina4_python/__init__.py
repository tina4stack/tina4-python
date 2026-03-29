# Tina4 Python v3.0 — This is not a 4ramework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Tina4 Python v3.0 — Zero-dependency, lightweight web framework.

    from tina4_python import get, post, ORM, Database, Frond, Auth, Queue

One import, everything works.
"""
__version__ = "3.10.24"

# ── HTTP Constants ──
from tina4_python.core.constants import (  # noqa: E402, F401
    HTTP_OK, HTTP_CREATED, HTTP_ACCEPTED, HTTP_NO_CONTENT,
    HTTP_MOVED, HTTP_REDIRECT, HTTP_NOT_MODIFIED,
    HTTP_BAD_REQUEST, HTTP_UNAUTHORIZED, HTTP_FORBIDDEN,
    HTTP_NOT_FOUND, HTTP_METHOD_NOT_ALLOWED, HTTP_CONFLICT,
    HTTP_GONE, HTTP_UNPROCESSABLE, HTTP_TOO_MANY,
    HTTP_SERVER_ERROR, HTTP_BAD_GATEWAY, HTTP_UNAVAILABLE,
    APPLICATION_JSON, APPLICATION_XML, APPLICATION_FORM,
    APPLICATION_OCTET, TEXT_HTML, TEXT_PLAIN, TEXT_CSV, TEXT_XML,
)

# ── ORM ──
from tina4_python.orm import (  # noqa: E402, F401
    ORM, orm_bind, Field,
    IntegerField, StringField, BooleanField, FloatField,
    DateTimeField, TextField, BlobField, NumericField,
    IntField, StrField, BoolField,  # short aliases
    has_many, has_one, belongs_to,  # relationship descriptors
)

# ── Response Cache ──
from tina4_python.cache import (  # noqa: E402, F401
    ResponseCache, cache_stats, clear_cache,
)

# ── DI Container ──
from tina4_python.container import Container  # noqa: E402, F401
