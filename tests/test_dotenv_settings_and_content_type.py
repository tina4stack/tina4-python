"""Regression lock-in for tina4-python#143 and #144 (ADR-0072).

#144: ``response.header("Content-Type", ...)`` sent a SECOND Content-Type
instead of replacing the one ``response()`` detects. A route that served PNG
bytes that way went out with ``application/octet-stream`` AND ``image/png``;
with ``X-Content-Type-Options: nosniff`` a browser may refuse to render it.

#143: ``TINA4_MAX_UPLOAD_SIZE`` set in ``.env`` was ignored. ``core/request.py``
read it into a module constant at import time and ``run()`` loads ``.env``
later, so the constant kept the 10MB default. ``TINA4_HEALTH_PATH`` had the same
gap: ``core/server.py`` registered the health route at import time.

No mocks: one REAL child server, booted by ``run()`` from a project whose
``.env`` carries the settings (the outer environment is scrubbed of them), and
every case is a real HTTP request over a real loopback socket. The headers are
read raw, so a duplicated Content-Type is visible.
"""
import http.client

import pytest

from conftest import boot_child_server

UPLOAD_LIMIT = 1000
DOTENV_HEALTH_PATH = "/healthz-from-dotenv"

ROUTES = '''
from tina4_python.core.router import get, noauth, post

PNG = bytes.fromhex("89504e470d0a1a0a")


@noauth()
@post("/upload")
async def upload(request, response):
    return response("OK", 200)


@get("/content-type/header-with-bytes")
async def header_with_bytes(request, response):
    response.header("Content-Type", "image/png")
    return response(PNG)


@get("/content-type/lowercase-header")
async def lowercase_header(request, response):
    response.header("content-type", "image/png")
    return response(PNG)


@get("/content-type/header-with-string")
async def header_with_string(request, response):
    response.header("Content-Type", "text/csv")
    return response("a,b")


@get("/content-type/argument-after-header")
async def argument_after_header(request, response):
    response.header("Content-Type", "image/png")
    return response(PNG, 200, "image/gif")


@get("/content-type/detected")
async def detected(request, response):
    return response("plain words")
'''


def _write_app(project, port):
    (project / ".env").write_text(
        f"TINA4_MAX_UPLOAD_SIZE={UPLOAD_LIMIT}\n"
        f"TINA4_HEALTH_PATH={DOTENV_HEALTH_PATH}\n"
        "TINA4_DEBUG=false\n"
    )
    (project / "src" / "routes" / "content_type.py").write_text(ROUTES)
    (project / "app.py").write_text(
        "from tina4_python.core import run\n"
        "if __name__ == '__main__':\n"
        f"    run(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
    )


@pytest.fixture(scope="module")
def dotenv_server(tmp_path_factory):
    proc, port = boot_child_server(
        tmp_path_factory.mktemp("dotenv_settings"), _write_app,
        extra_env={"TINA4_DEBUG": "false"},
        unset_env=("TINA4_MAX_UPLOAD_SIZE", "TINA4_HEALTH_PATH", "TINA4_ENV_FILE"),
        log_dir=tmp_path_factory.mktemp("dotenv_settings_logs"),
    )
    try:
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def _request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        answer = connection.getresponse()
        answer.read()
        return answer.status, answer.msg.get_all("Content-Type") or []
    finally:
        connection.close()


class TestHeaderContentTypeIsTheOneContentType:
    """#144: a Content-Type set with header() is THE Content-Type."""

    def test_header_content_type_replaces_the_detected_type(self, dotenv_server):
        status, content_types = _request(dotenv_server, "GET", "/content-type/header-with-bytes")
        assert status == 200
        assert content_types == ["image/png"]

    def test_a_lowercase_content_type_header_is_the_same_header(self, dotenv_server):
        status, content_types = _request(dotenv_server, "GET", "/content-type/lowercase-header")
        assert status == 200
        assert content_types == ["image/png"]

    def test_header_content_type_survives_a_string_body(self, dotenv_server):
        status, content_types = _request(dotenv_server, "GET", "/content-type/header-with-string")
        assert status == 200
        assert content_types == ["text/csv"]

    def test_an_explicit_content_type_argument_wins_over_the_header(self, dotenv_server):
        status, content_types = _request(dotenv_server, "GET", "/content-type/argument-after-header")
        assert status == 200
        assert content_types == ["image/gif"]

    def test_without_a_header_the_detected_type_is_used(self, dotenv_server):
        status, content_types = _request(dotenv_server, "GET", "/content-type/detected")
        assert status == 200
        assert len(content_types) == 1
        assert content_types[0].lower().startswith("text/plain")


class TestDotenvSettingsAreReadWhenUsed:
    """#143: a setting in .env applies, because it is read after run() loads .env."""

    def test_max_upload_size_from_dotenv_is_enforced(self, dotenv_server):
        status, _ = _request(dotenv_server, "POST", "/upload", body=b"x" * (UPLOAD_LIMIT * 5),
                             headers={"Content-Type": "application/octet-stream"})
        assert status == 413

    def test_a_body_under_the_dotenv_limit_is_accepted(self, dotenv_server):
        status, _ = _request(dotenv_server, "POST", "/upload", body=b"x" * (UPLOAD_LIMIT // 2),
                             headers={"Content-Type": "application/octet-stream"})
        assert status == 200

    def test_health_path_from_dotenv_is_served(self, dotenv_server):
        status, _ = _request(dotenv_server, "GET", DOTENV_HEALTH_PATH)
        assert status == 200


class TestUploadLimitValue:
    """The limit is resolved from the environment on every call."""

    def test_max_upload_size_follows_the_environment(self, monkeypatch):
        from tina4_python.core.request import max_upload_size
        monkeypatch.setenv("TINA4_MAX_UPLOAD_SIZE", "2048")
        assert max_upload_size() == 2048
        monkeypatch.setenv("TINA4_MAX_UPLOAD_SIZE", "4096")
        assert max_upload_size() == 4096

    def test_a_bad_max_upload_size_falls_back_to_the_default(self, monkeypatch):
        from tina4_python.core.request import DEFAULT_MAX_UPLOAD_SIZE, max_upload_size
        for bad in ("ten megabytes", "-5", "0"):
            monkeypatch.setenv("TINA4_MAX_UPLOAD_SIZE", bad)
            assert max_upload_size() == DEFAULT_MAX_UPLOAD_SIZE
