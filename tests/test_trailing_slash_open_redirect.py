"""Medium security finding F3 — the trailing-slash redirect must not be an open
redirect.

With TINA4_TRAILING_SLASH_REDIRECT on, a request for ``//evil.com/`` used to
normalise to a ``Location: //evil.com`` header — which a browser treats as the
protocol-relative absolute URL of another host (open redirect). The canonical
target must always be a same-origin absolute path. Case names match the sibling
regression in tina4-php/tests/TrailingSlashOpenRedirectTest.php. (Node matches
against registered routes only, and Ruby's predicate emits no Location, so
neither is affected.)
"""
import pytest


class TestTrailingSlashOpenRedirect:
    @pytest.mark.asyncio
    async def test_protocol_relative_path_redirects_to_same_origin(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRAILING_SLASH_REDIRECT", "true")
        from tina4_python.core.request import Request
        from tina4_python.core.server import handle

        req = Request()
        req.method = "GET"
        req.path = "//evil.com/"
        req.headers = {}
        resp = await handle(req)

        assert resp.status_code == 301
        location = next((v for k, v in resp._headers if str(k).lower() == "location"), None)
        # Must be a same-origin absolute path, never protocol-relative "//host".
        assert location is not None
        assert not location.startswith("//"), f"open redirect: {location!r}"
        assert not location.startswith("/\\"), f"open redirect: {location!r}"
        assert location == "/evil.com"

    @pytest.mark.asyncio
    async def test_backslash_authority_redirects_to_same_origin(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRAILING_SLASH_REDIRECT", "true")
        from tina4_python.core.request import Request
        from tina4_python.core.server import handle

        req = Request()
        req.method = "GET"
        req.path = "/\\evil.com/"
        req.headers = {}
        resp = await handle(req)

        assert resp.status_code == 301
        location = next((v for k, v in resp._headers if str(k).lower() == "location"), None)
        assert location is not None
        assert not location.startswith("//") and not location.startswith("/\\"), (
            f"open redirect: {location!r}"
        )

    @pytest.mark.asyncio
    async def test_ordinary_path_still_redirects_to_canonical(self, monkeypatch):
        # Positive twin: a normal trailing-slash path still normalises correctly.
        monkeypatch.setenv("TINA4_TRAILING_SLASH_REDIRECT", "true")
        from tina4_python.core.request import Request
        from tina4_python.core.server import handle

        req = Request()
        req.method = "GET"
        req.path = "/foo/bar/"
        req.headers = {}
        resp = await handle(req)

        assert resp.status_code == 301
        location = next((v for k, v in resp._headers if str(k).lower() == "location"), None)
        assert location == "/foo/bar"
