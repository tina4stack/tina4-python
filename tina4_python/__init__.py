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
    # Floor literal, reached only when BOTH lookups above miss. That is not
    # theoretical: the Docker build used to prune dist-info from the installed
    # package, so path 2 raised PackageNotFoundError and the published
    # tina4-python:3.13.94 image served this literal on /health -- then reading
    # "3.13.56", 36 releases stale, because nothing kept it current.
    #
    # test_version_constant.py now asserts this literal equals the pyproject
    # version, so the release bump cannot leave it behind again.
    return "3.13.103"


__version__ = _resolve_version()

# ══════════════════════════════════════════════════════════════════════════
# LAZY FEATURE LOADING (PEP 562 module __getattr__)
# ══════════════════════════════════════════════════════════════════════════
# A batteries-included framework should not pay to import all ~98 features on
# every boot. Only the CORE surface below is imported eagerly; every optional
# subsystem is registered in _LAZY and imported on FIRST reference via
# ``__getattr__``. An app that never touches GraphQL/WSDL/MQTT/Messenger never
# loads those modules — so a production runtime's footprint matches the app.
# ``from tina4_python import GraphQL`` still works: the miss routes through
# ``__getattr__``, which imports the module, caches the name in globals(), and
# returns it (so later access skips the hook). See plan/v3/feature-preload-manifest.md.

# ── CORE (always eager) — every app needs these to boot + serve ──
from tina4_python.core.router import (  # noqa: E402, F401
    get, post, put, patch, delete, any_method,
    noauth, secured, cached, middleware, template,
    Router, RouteGroup,
)
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
from tina4_python.core.server import (  # noqa: E402, F401
    run, background, background_task_count, stop_all_background_tasks,
    asgi,
)
from tina4_python.core.events import on, emit, once, off  # noqa: E402, F401
from tina4_python.env import Env  # noqa: E402, F401

# ── OPTIONAL (lazy) — public name -> (submodule, attribute) ──
_LAZY: dict[str, tuple[str, str]] = {
    # Database + ORM
    "Database": ("tina4_python.database", "Database"),
    "ORM": ("tina4_python.orm", "ORM"),
    "bind_database": ("tina4_python.orm", "bind_database"),
    "Field": ("tina4_python.orm", "Field"),
    "IntegerField": ("tina4_python.orm", "IntegerField"),
    "StringField": ("tina4_python.orm", "StringField"),
    "BooleanField": ("tina4_python.orm", "BooleanField"),
    "FloatField": ("tina4_python.orm", "FloatField"),
    "DateTimeField": ("tina4_python.orm", "DateTimeField"),
    "TextField": ("tina4_python.orm", "TextField"),
    "BlobField": ("tina4_python.orm", "BlobField"),
    "NumericField": ("tina4_python.orm", "NumericField"),
    "DecimalField": ("tina4_python.orm", "DecimalField"),
    "JSONField": ("tina4_python.orm", "JSONField"),
    "PointField": ("tina4_python.orm", "PointField"),
    "Point": ("tina4_python.orm", "Point"),
    "feature_collection": ("tina4_python.orm", "feature_collection"),
    "ForeignKeyField": ("tina4_python.orm", "ForeignKeyField"),
    "IntField": ("tina4_python.orm", "IntField"),
    "StrField": ("tina4_python.orm", "StrField"),
    "BoolField": ("tina4_python.orm", "BoolField"),
    "has_many": ("tina4_python.orm", "has_many"),
    "has_one": ("tina4_python.orm", "has_one"),
    "belongs_to": ("tina4_python.orm", "belongs_to"),
    # Auth
    "Auth": ("tina4_python.auth", "Auth"),
    # Queue
    "Queue": ("tina4_python.queue", "Queue"),
    # MQTT
    "Mqtt": ("tina4_python.mqtt", "Mqtt"),
    "MqttMessage": ("tina4_python.mqtt", "MqttMessage"),
    "MqttError": ("tina4_python.mqtt", "MqttError"),
    # Template engine
    "Frond": ("tina4_python.frond", "Frond"),
    # Response cache
    "ResponseCache": ("tina4_python.cache", "ResponseCache"),
    "cache_stats": ("tina4_python.cache", "cache_stats"),
    "clear_cache": ("tina4_python.cache", "clear_cache"),
    # DI container
    "Container": ("tina4_python.container", "Container"),
    # HTTP client
    "Api": ("tina4_python.api", "Api"),
    # App-facing AI client (ADR-0053)
    "Ai": ("tina4_python.ai", "Ai"),
    "ChatResponse": ("tina4_python.ai", "ChatResponse"),
    "AiError": ("tina4_python.ai", "AiError"),
    "AiConfigError": ("tina4_python.ai", "AiConfigError"),
    "AiHTTPError": ("tina4_python.ai", "AiHTTPError"),
    "AiTimeoutError": ("tina4_python.ai", "AiTimeoutError"),
    "AiParseError": ("tina4_python.ai", "AiParseError"),
    # Provider-neutral OpenID Connect SSO (ADR-0056)
    "Sso": ("tina4_python.sso", "Sso"),
    "SSO": ("tina4_python.sso", "SSO"),
    "SsoError": ("tina4_python.sso", "SsoError"),
    # SOAP / WSDL
    "WSDL": ("tina4_python.wsdl", "WSDL"),
    "wsdl_operation": ("tina4_python.wsdl", "wsdl_operation"),
    # GraphQL
    "GraphQL": ("tina4_python.graphql", "GraphQL"),
    # Auto-CRUD
    "AutoCrud": ("tina4_python.crud", "AutoCrud"),
    # Email
    "Messenger": ("tina4_python.messenger", "Messenger"),
    # Realtime / WebRTC
    "realtime": ("tina4_python.realtime", "realtime"),
    "RtcMediaBackend": ("tina4_python.realtime", "RtcMediaBackend"),
    "MeshBackend": ("tina4_python.realtime", "MeshBackend"),
    "StorageBackend": ("tina4_python.realtime.storage", "StorageBackend"),
    "LocalStorage": ("tina4_python.realtime.storage", "LocalStorage"),
    "S3Storage": ("tina4_python.realtime.storage", "S3Storage"),
    # Inline testing (decorator/descriptor surface — expect_* builders)
    "tests": ("tina4_python.Testing", "tests"),
    "expect_equal": ("tina4_python.Testing", "expect_equal"),
    "expect_raises": ("tina4_python.Testing", "expect_raises"),
    "expect_true": ("tina4_python.Testing", "expect_true"),
    "expect_false": ("tina4_python.Testing", "expect_false"),
}


def __getattr__(name: str):  # noqa: N807  (PEP 562 module-level hook)
    """Import an optional subsystem on first reference, then cache it."""
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module 'tina4_python' has no attribute {name!r}")
    import importlib
    module_path, attr = spec
    value = getattr(importlib.import_module(module_path), attr)
    globals()[name] = value  # cache — subsequent access skips this hook
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))


def _preload_from_manifest() -> None:
    """Eager-warm the subsystems an app actually uses, from a generated
    ``.tina4/preload.json`` (see plan/v3/feature-preload-manifest.md). No manifest,
    or dev mode, means everything stays lazy — this is pure pre-warm, never a gate.
    The lazy ``__getattr__`` above is what guarantees unused features never load.
    """
    import os
    if os.environ.get("TINA4_DEBUG", "").lower() in ("true", "1", "yes", "on"):
        return  # dev: leave everything lazy on-demand
    try:
        import json
        import pathlib
        manifest = pathlib.Path.cwd() / ".tina4" / "preload.json"
        if not manifest.exists():
            return
        data = json.loads(manifest.read_text())
        import importlib
        for feature in data.get("features", []):
            try:
                importlib.import_module(f"tina4_python.{feature}")
            except Exception:  # noqa: BLE001 — a bad manifest entry must not break boot
                pass
    except Exception:  # noqa: BLE001
        pass


_preload_from_manifest()
