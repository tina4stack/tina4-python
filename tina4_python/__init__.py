# Tina4 Python v3.0 — The Intelligent Native Application 4ramework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Tina4 Python v3.0 — Zero-dependency, lightweight web framework.

    from tina4_python import get, post, ORM, Database, Frond, Auth, Queue

One import, everything works.
"""
def _resolve_version() -> str:
    """Resolve the package version from a single source of truth.

    Derive it rather than hardcode it, so a release only has to bump
    ``pyproject.toml`` and can never leave this constant stale (which used to
    make the dev toolbar and ``docs._detect_version`` under-report). Mirrors how
    Node reads package.json and PHP resolves ``App::$VERSION`` at runtime.

    Order:
      1. The repo's own ``pyproject.toml`` (a source checkout is authoritative
         and current; installed metadata can lag an un-synced checkout). Guarded
         by the project name so a copy vendored under another app's pyproject
         can't hijack the version.
      2. Installed distribution metadata (the shipped wheel has no pyproject).
      3. A floor literal (last resort only).
    """
    try:
        import pathlib
        import tomllib
        pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
        if pyproject.exists():
            with pyproject.open("rb") as fh:
                project = tomllib.load(fh).get("project", {})
            if project.get("name") == "tina4-python" and project.get("version"):
                return project["version"]
    except Exception:
        pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("tina4-python")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    return "3.13.56"


__version__ = _resolve_version()

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
from tina4_python.core.server import (  # noqa: E402, F401
    run,
    background,
    background_task_count,
    stop_all_background_tasks,
)

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
