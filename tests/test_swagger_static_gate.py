"""Lock-in: the BUNDLED Swagger UI static assets must honour the swagger gate.

Regression this pins down
-------------------------
The framework ships the Swagger UI as static files under
``tina4_python/public/swagger/`` (``index.html`` + ``oauth2-redirect.html``).
Static files are resolved by ``_try_static`` INDEPENDENTLY of the gated
``/swagger`` routes, so before the fix a production server still served the
Swagger UI on:

    /swagger/                        -> 200 (index resolution)
    /swagger/index.html              -> 200 (direct file)
    /swagger/oauth2-redirect.html    -> 200 (direct file)

even with swagger disabled -- silently bypassing the documented
``TINA4_SWAGGER_ENABLED`` / ``TINA4_DEBUG`` switch. A bare ``/swagger`` already
404'd (index resolution only fires for ``''`` or a trailing slash), which is
exactly why the leak stayed hidden: testing only ``/swagger`` looked clean.

The tests are REAL: real files on disk, the real ``_try_static``, real env vars.
No doubles.
"""

import os
from pathlib import Path

import tina4_python
from tina4_python.core.server import _try_static

FRAMEWORK_PUBLIC = Path(tina4_python.__file__).resolve().parent / "public"

# The shipped assets that made up the leak surface.
SWAGGER_ASSETS = ("swagger/index.html", "swagger/oauth2-redirect.html")

# Request paths that MUST be gated. A bare "/swagger" is deliberately excluded:
# _try_static never index-resolves a path without a trailing slash, so it 404s
# on its own and is not part of this contract.
GATED_PATHS = (
    "/swagger/",
    "/swagger/index.html",
    "/swagger/oauth2-redirect.html",
)

# A bundled asset that is NOT swagger — proves the gate is surgical and does not
# break ordinary static serving.
CONTROL_PATH = "/favicon.ico"


def _set_env(**pairs):
    """Set env vars (None deletes) and return the previous values for restore."""
    previous = {}
    for key, value in pairs.items():
        previous[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return previous


def _restore_env(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_swagger_assets_really_ship():
    """GUARD: the leak surface must actually exist on disk.

    Without this, the negative test below could pass vacuously (nothing to
    serve means nothing to leak) and would keep passing even if the gate were
    deleted.
    """
    for asset in SWAGGER_ASSETS:
        assert (FRAMEWORK_PUBLIC / asset).is_file(), (
            f"{asset} is missing from {FRAMEWORK_PUBLIC} -- the negative test "
            "below would prove nothing"
        )
    assert (FRAMEWORK_PUBLIC / "favicon.ico").is_file(), "control asset missing"


def test_swagger_static_blocked_when_swagger_disabled():
    """NEGATIVE: swagger explicitly off -> no bundled asset path may serve."""
    previous = _set_env(TINA4_SWAGGER_ENABLED="false", TINA4_DEBUG="false")
    try:
        for path in GATED_PATHS:
            assert _try_static(path) is None, (
                f"{path} served the bundled Swagger UI with swagger disabled"
            )
    finally:
        _restore_env(previous)


def test_swagger_static_served_when_swagger_enabled():
    """POSITIVE: swagger on -> the assets must still serve.

    A gate that also breaks dev is worse than the leak.
    """
    previous = _set_env(TINA4_SWAGGER_ENABLED="true", TINA4_DEBUG="true")
    try:
        for path in GATED_PATHS:
            assert _try_static(path) is not None, (
                f"{path} did not serve with swagger enabled"
            )
    finally:
        _restore_env(previous)


def test_unset_flag_falls_back_to_debug():
    """TINA4_SWAGGER_ENABLED unset falls back to TINA4_DEBUG (documented)."""
    previous = _set_env(TINA4_SWAGGER_ENABLED=None, TINA4_DEBUG="false")
    try:
        assert _try_static("/swagger/index.html") is None, (
            "debug off with the flag unset must gate the assets"
        )
    finally:
        _restore_env(previous)

    previous = _set_env(TINA4_SWAGGER_ENABLED=None, TINA4_DEBUG="true")
    try:
        assert _try_static("/swagger/index.html") is not None, (
            "debug on with the flag unset must serve the assets"
        )
    finally:
        _restore_env(previous)


def test_explicit_flag_beats_debug():
    """Explicit TINA4_SWAGGER_ENABLED wins over TINA4_DEBUG, both directions."""
    previous = _set_env(TINA4_SWAGGER_ENABLED="false", TINA4_DEBUG="true")
    try:
        assert _try_static("/swagger/index.html") is None, (
            "explicit false must gate even in debug"
        )
    finally:
        _restore_env(previous)

    previous = _set_env(TINA4_SWAGGER_ENABLED="true", TINA4_DEBUG="false")
    try:
        assert _try_static("/swagger/index.html") is not None, (
            "explicit true must serve even with debug off"
        )
    finally:
        _restore_env(previous)


def test_non_swagger_static_unaffected_by_the_gate():
    """The gate must be surgical: ordinary bundled assets still serve."""
    previous = _set_env(TINA4_SWAGGER_ENABLED="false", TINA4_DEBUG="false")
    try:
        assert _try_static(CONTROL_PATH) is not None, (
            "the swagger gate must not block non-swagger static assets"
        )
    finally:
        _restore_env(previous)
