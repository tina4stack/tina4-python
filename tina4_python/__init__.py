# Tina4 Python v3.0 — The Intelligent Native Application 4ramework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Tina4 Python v3.0 — Zero-dependency, lightweight web framework.

    from tina4_python import get, post, ORM, Database, Frond, Auth, Queue

One import, everything works.
"""
__version__ = "3.13.57"

# ── Route decorators ──
from tina4_python.core.router import (  # noqa: E402, F401
    get, post, put, patch, delete, any_method,
    noauth, secured, cached, middleware, template,
    Router, RouteGroup,
)

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

# ── Database ──
from tina4_python.database import Database  # noqa: E402, F401

# ── ORM ──
from tina4_python.orm import (  # noqa: E402, F401
    ORM, bind_database, Field,
    IntegerField, StringField, BooleanField, FloatField,
    DateTimeField, TextField, BlobField, NumericField, JSONField,
    ForeignKeyField,
    IntField, StrField, BoolField,  # short aliases
    has_many, has_one, belongs_to,  # relationship descriptors
)

# ── Env (typed env-var helpers) ──
from tina4_python.env import Env  # noqa: E402, F401

# ── Auth ──
from tina4_python.auth import Auth  # noqa: E402, F401

# ── Queue ──
from tina4_python.queue import Queue  # noqa: E402, F401

# ── Template engine ──
from tina4_python.frond import Frond  # noqa: E402, F401

# ── Response Cache ──
from tina4_python.cache import (  # noqa: E402, F401
    ResponseCache, cache_stats, clear_cache,
)

# ── DI Container ──
from tina4_python.container import Container  # noqa: E402, F401

# ── Server ──
from tina4_python.core.server import run, background  # noqa: E402, F401

# ── HTTP Client ──
from tina4_python.api import Api  # noqa: E402, F401

# ── SOAP / WSDL ──
from tina4_python.wsdl import WSDL, wsdl_operation  # noqa: E402, F401

# ── GraphQL ──
from tina4_python.graphql import GraphQL  # noqa: E402, F401

# ── Auto-CRUD scaffolder ──
from tina4_python.crud import AutoCrud  # noqa: E402, F401

# ── Events (decoupled communication) ──
from tina4_python.core.events import on, emit, once, off  # noqa: E402, F401

# ── Email (Messenger) ──
from tina4_python.messenger import Messenger  # noqa: E402, F401

# ── Real-time collaboration (WebRTC signalling + chat + files control plane) ──
from tina4_python.realtime import realtime, RtcMediaBackend, MeshBackend  # noqa: E402, F401
from tina4_python.realtime.storage import (  # noqa: E402, F401
    StorageBackend, LocalStorage, S3Storage,
)

# ── Inline testing (@tests + assertions for inline test cases) ──
# Class-based xUnit testing lives in tina4_python.test (a separate module).
# Keep both surfaces re-exported so users can write either style.
from tina4_python.Testing import tests, assert_equal as assert_equal_inline  # noqa: E402, F401
