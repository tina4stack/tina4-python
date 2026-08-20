# Tests for tina4_python.cache — ResponseCache middleware + multi-backend direct API
import os
import time
import shutil
import threading
import pytest
from unittest.mock import patch
from tina4_python.cache import (
    ResponseCache, _get_default, cache_stats, clear_cache,
    cache_get, cache_set, cache_delete, cache_clear,
    _MemoryBackend, _FileBackend, _RedisBackend, _create_backend,
)
import tina4_python.cache as cache_module


from tina4_python.core.request import Request
from tina4_python.core.response import Response


# These tests drive the REAL framework Request and Response.
#
# They used to drive a `MockRequest` stub with a plain `__dict__`. The real
# Request has `__slots__`, so `request._cache_key = ...` — which the middleware
# did on every call — raised AttributeError against a live request while the
# stub happily accepted it. The suite was green for the middleware's whole life
# while `@middleware(ResponseCache)` 500'd every real request. A double standing
# in for a real collaborator is what the no-mock rule forbids, and this is why.


def make_request(method="GET", url="/test", params=None, headers=None, cache_max_age=None):
    """A real framework Request, populated like the dispatcher populates one.

    ``cache_max_age`` attaches a handler carrying the flag ``@cached(max_age=N)``
    stamps, exactly as the dispatcher does via ``request._handler``.
    """
    request = Request()
    request.method = method
    request.url = url
    request.path = url
    request.params = params or {}
    request.headers = headers or {}
    if cache_max_age is not None:
        def handler(req, resp):
            return resp
        handler._cached = True
        handler._cache_max_age = cache_max_age
        request._handler = handler
    return request


def make_response(body=None, status_code=200):
    """A real framework Response, optionally pre-filled with a body."""
    response = Response()
    if body is not None:
        response(body, status_code)
    return response


def body_of(response):
    """The response body as text, whatever shape it is carried in."""
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content).decode("utf-8", errors="replace")
    return "" if content is None else str(content)


def header_of(response, name):
    """A single response header value, or None."""
    target = name.lower()
    for key, value in getattr(response, "_headers", []):
        if str(key).lower() == target:
            return str(value)
    return None


def serve(cache, request, response):
    """Run before_cache and return the response the caller would receive.

    A HIT short-circuits by returning the Response OBJECT; a MISS returns the
    ``(request, response)`` pair. Both shapes are part of the middleware
    contract (``Middleware.apply_hook_result``), so tests read through here.
    """
    result = cache.before_cache(request, response)
    return result[1] if isinstance(result, tuple) else result


@pytest.fixture(autouse=True)
def _isolate_response_cache():
    """Every test starts with an empty, freshly-built shared backend."""
    cache_module._reset_response_backend()
    cache_module._default_backend = None
    cache_module._default_cache = None
    cache_module._default_ttl = None
    yield
    cache_module._reset_response_backend()
    cache_module._default_backend = None
    cache_module._default_cache = None
    cache_module._default_ttl = None


# ── Construction & Defaults ──────────────────────────────────────


class TestResponseCacheInit:
    """Test cache creation with default and custom parameters."""

    def test_default_ttl(self):
        cache = ResponseCache()
        assert cache.ttl == 60

    def test_default_max_entries(self):
        cache = ResponseCache()
        assert cache.max_entries == 1000

    def test_default_status_codes(self):
        cache = ResponseCache()
        assert cache.status_codes == {200}

    def test_custom_ttl(self):
        cache = ResponseCache(ttl=120)
        assert cache.ttl == 120

    def test_custom_max_entries(self):
        cache = ResponseCache(max_entries=50)
        assert cache.max_entries == 50

    def test_custom_status_codes(self):
        cache = ResponseCache(status_codes=[200, 201, 304])
        assert cache.status_codes == {200, 201, 304}

    def test_env_ttl(self):
        os.environ["TINA4_CACHE_TTL"] = "300"
        try:
            cache = ResponseCache()
            assert cache.ttl == 300
        finally:
            del os.environ["TINA4_CACHE_TTL"]

    def test_env_max_entries(self):
        os.environ["TINA4_CACHE_MAX_ENTRIES"] = "500"
        try:
            cache = ResponseCache()
            assert cache.max_entries == 500
        finally:
            del os.environ["TINA4_CACHE_MAX_ENTRIES"]

    def test_explicit_ttl_overrides_env(self):
        os.environ["TINA4_CACHE_TTL"] = "300"
        try:
            cache = ResponseCache(ttl=10)
            assert cache.ttl == 10
        finally:
            del os.environ["TINA4_CACHE_TTL"]

    def test_explicit_max_entries_overrides_env(self):
        os.environ["TINA4_CACHE_MAX_ENTRIES"] = "500"
        try:
            cache = ResponseCache(max_entries=5)
            assert cache.max_entries == 5
        finally:
            del os.environ["TINA4_CACHE_MAX_ENTRIES"]


# ── Backend Selection ────────────────────────────────────────────


class TestBackendSelection:
    """Test that TINA4_CACHE_BACKEND selects the correct backend."""

    def test_default_backend_is_memory(self):
        backend = _create_backend()
        assert backend.name() == "memory"

    def test_env_selects_memory(self):
        os.environ["TINA4_CACHE_BACKEND"] = "memory"
        try:
            backend = _create_backend()
            assert backend.name() == "memory"
        finally:
            del os.environ["TINA4_CACHE_BACKEND"]

    def test_env_selects_file(self):
        os.environ["TINA4_CACHE_BACKEND"] = "file"
        try:
            backend = _create_backend()
            assert backend.name() == "file"
        finally:
            del os.environ["TINA4_CACHE_BACKEND"]
            # Cleanup
            shutil.rmtree("data/cache", ignore_errors=True)

    def test_explicit_param_overrides_env(self):
        os.environ["TINA4_CACHE_BACKEND"] = "file"
        try:
            backend = _create_backend(backend="memory")
            assert backend.name() == "memory"
        finally:
            del os.environ["TINA4_CACHE_BACKEND"]

    def test_response_cache_accepts_backend_param(self):
        cache = ResponseCache(backend="memory")
        stats = cache.cache_stats()
        assert stats["backend"] == "memory"


# ── Memory Backend ───────────────────────────────────────────────


class TestMemoryBackend:
    """Test the in-memory LRU backend directly."""

    def test_set_and_get(self):
        backend = _MemoryBackend()
        backend.set("key1", {"data": "value"}, ttl=60)
        result = backend.get("key1")
        assert result == {"data": "value"}

    def test_get_missing_key(self):
        backend = _MemoryBackend()
        assert backend.get("nonexistent") is None

    def test_ttl_expiry(self):
        backend = _MemoryBackend()
        backend.set("expire", "data", ttl=1)
        assert backend.get("expire") == "data"
        time.sleep(1.1)
        assert backend.get("expire") is None

    def test_delete(self):
        backend = _MemoryBackend()
        backend.set("del", "val", ttl=60)
        assert backend.delete("del") is True
        assert backend.get("del") is None
        assert backend.delete("del") is False

    def test_clear(self):
        backend = _MemoryBackend()
        backend.set("a", 1, ttl=60)
        backend.set("b", 2, ttl=60)
        backend.clear()
        stats = backend.stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_lru_eviction(self):
        backend = _MemoryBackend(max_entries=2)
        backend.set("a", 1, ttl=60)
        backend.set("b", 2, ttl=60)
        backend.set("c", 3, ttl=60)
        assert backend.get("a") is None  # evicted
        assert backend.get("b") == 2
        assert backend.get("c") == 3

    def test_stats_tracks_hits_misses(self):
        backend = _MemoryBackend()
        backend.set("x", "val", ttl=60)
        backend.get("x")  # hit
        backend.get("y")  # miss
        stats = backend.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["backend"] == "memory"


# ── File Backend ─────────────────────────────────────────────────


class TestFileBackend:
    """Test the file-based cache backend."""

    CACHE_DIR = "/tmp/tina4_test_cache"

    def setup_method(self):
        shutil.rmtree(self.CACHE_DIR, ignore_errors=True)

    def teardown_method(self):
        shutil.rmtree(self.CACHE_DIR, ignore_errors=True)

    def test_set_and_get(self):
        backend = _FileBackend(cache_dir=self.CACHE_DIR)
        backend.set("key1", {"data": "value"}, ttl=60)
        result = backend.get("key1")
        assert result == {"data": "value"}

    def test_get_missing_key(self):
        backend = _FileBackend(cache_dir=self.CACHE_DIR)
        assert backend.get("nonexistent") is None

    def test_ttl_expiry(self):
        backend = _FileBackend(cache_dir=self.CACHE_DIR)
        backend.set("expire", "data", ttl=1)
        assert backend.get("expire") == "data"
        time.sleep(1.1)
        assert backend.get("expire") is None

    def test_delete(self):
        backend = _FileBackend(cache_dir=self.CACHE_DIR)
        backend.set("del", "val", ttl=60)
        assert backend.delete("del") is True
        assert backend.get("del") is None
        assert backend.delete("del") is False

    def test_clear(self):
        backend = _FileBackend(cache_dir=self.CACHE_DIR)
        backend.set("a", 1, ttl=60)
        backend.set("b", 2, ttl=60)
        backend.clear()
        stats = backend.stats()
        assert stats["size"] == 0

    def test_stats_backend_name(self):
        backend = _FileBackend(cache_dir=self.CACHE_DIR)
        stats = backend.stats()
        assert stats["backend"] == "file"


# ── Cache Key Generation ─────────────────────────────────────────


class TestCacheKeyGeneration:
    """Test that cache keys are built correctly from method + URL + params."""

    def test_get_without_params(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/items")

        assert cache.cache_key(req) == "GET:/api/items"

    def test_get_with_params_sorted(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/items", params={"z": "1", "a": "2"})

        assert cache.cache_key(req) == "GET:/api/items?a=2&z=1"

    def test_non_get_no_cache_key(self):
        """A non-GET is never stored, so a later GET on the same URL misses."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()
        post = make_request(method="POST", url="/api/items")
        cache.before_cache(post, make_response())
        cache.after_cache(post, make_response(body='{"posted": true}'))

        get = make_request(method="GET", url="/api/items")
        out = serve(cache, get, make_response())
        assert body_of(out) == ""


# ── Cache Hit (before_cache) ─────────────────────────────────────


class TestCacheHit:
    """Test that cached responses are returned on cache hit."""

    def test_cache_hit_returns_cached_body(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/data")
        resp = make_response()

        # First request — miss
        cache.before_cache(req, resp)
        # Simulate handler producing a response
        resp_out = make_response(body='{"result": 1}', status_code=200)
        cache.after_cache(req, resp_out)

        # Second request — hit
        req2 = make_request(method="GET", url="/api/data")
        resp2 = make_response()
        hit_resp = serve(cache, req2, resp2)

        assert body_of(hit_resp) == '{"result": 1}'
        assert hit_resp.status_code == 200

    def test_cache_miss_lets_request_through(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/new")
        resp = make_response()

        returned_resp = serve(cache, req, resp)
        # On miss, the original response is returned unchanged
        assert returned_resp is resp


# ── X-Cache headers ───────────────────────────────────────────────


class TestXCacheHeaders:
    """ResponseCache advertises X-Cache: MISS/HIT and X-Cache-TTL."""

    def test_miss_then_hit_headers(self):
        cache = ResponseCache(ttl=60)

        # First request — handler runs → MISS.
        req = make_request(method="GET", url="/api/x")
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body='{"v": 1}', status_code=200)
        _, after = cache.after_cache(req, resp_out)
        assert header_of(after, "X-Cache") == "MISS"
        assert header_of(after, "X-Cache-TTL") == "60"

        # Second request — served from cache → HIT.
        req2 = make_request(method="GET", url="/api/x")
        resp2 = make_response()
        hit = serve(cache, req2, resp2)
        assert body_of(hit) == '{"v": 1}'
        assert header_of(hit, "X-Cache") == "HIT"
        # Remaining TTL present and within (0, 60].
        assert header_of(hit, "X-Cache-TTL") is not None
        assert 0 < int(header_of(hit, "X-Cache-TTL")) <= 60

    def test_no_cache_control_header_emitted(self):
        """We must NOT set Cache-Control — that's the app's call."""
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/nocc")
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body="x", status_code=200)
        _, after = cache.after_cache(req, resp_out)
        assert header_of(after, "Cache-Control") is None

    def test_route_ttl_reflected_in_header(self):
        cache = ResponseCache(ttl=300)
        req = make_request(method="GET", url="/api/rt", cache_max_age=42)
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body="x", status_code=200)
        _, after = cache.after_cache(req, resp_out)
        assert header_of(after, "X-Cache") == "MISS"
        assert header_of(after, "X-Cache-TTL") == "42"

    def test_uncached_status_gets_no_headers(self):
        """A 404 isn't stored, so no X-Cache header is added in after_cache."""
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/404")
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body="missing", status_code=404)
        _, after = cache.after_cache(req, resp_out)
        assert header_of(after, "X-Cache") is None

    def test_headers_on_real_framework_response(self):
        """End-to-end against the real Response: headers land in build_headers()."""
        from tina4_python.core.response import Response

        cache = ResponseCache(ttl=60)

        # MISS — handler produced a real Response.
        req = make_request(method="GET", url="/api/real")
        cache.before_cache(req, Response())
        handler_resp = Response()(  # call to populate body/content
            {"hello": "world"}, 200
        )
        _, after = cache.after_cache(req, handler_resp)
        miss_headers = dict(after.build_headers())
        assert miss_headers[b"X-Cache"] == b"MISS"
        assert miss_headers[b"X-Cache-TTL"] == b"60"

        # HIT — before_cache returns a fresh Response carrying the headers.
        req2 = make_request(method="GET", url="/api/real")
        hit = serve(cache, req2, Response())
        hit_headers = dict(hit.build_headers())
        assert hit_headers[b"X-Cache"] == b"HIT"
        assert b"X-Cache-TTL" in hit_headers


# ── after_cache stores response ──────────────────────────────────


class TestAfterCache:
    """Test that after_cache stores responses correctly."""

    def test_stores_200_response(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/store")
        resp = make_response()

        cache.before_cache(req, resp)
        resp_out = make_response(body="stored", status_code=200)
        cache.after_cache(req, resp_out)

        stats = cache.cache_stats()
        assert stats["size"] == 1

    def test_does_not_store_without_cache_key(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="POST", url="/api/store")
        resp = make_response(body="nope", status_code=200)

        cache.after_cache(req, resp)
        assert cache.cache_stats()["size"] == 0


# ── TTL Expiry ────────────────────────────────────────────────────


class TestTTLExpiry:
    """Test that entries expire after their TTL."""

    def test_entry_expires_after_ttl(self):
        cache = ResponseCache(ttl=1, cleanup_interval=9999)
        req = make_request(method="GET", url="/api/expire")
        resp = make_response()

        cache.before_cache(req, resp)
        resp_out = make_response(body="temp", status_code=200)
        cache.after_cache(req, resp_out)

        # Entry is present
        assert cache.cache_stats()["size"] == 1

        time.sleep(1.1)

        # New request should miss (entry expired)
        req2 = make_request(method="GET", url="/api/expire")
        resp2 = make_response()
        ret = serve(cache, req2, resp2)
        # The response should be the original (not cached)
        assert ret is resp2

    def test_ttl_zero_disables_caching(self):
        cache = ResponseCache(ttl=0)
        req = make_request(method="GET", url="/api/disabled")
        resp = make_response()

        returned_resp = serve(cache, req, resp)
        assert returned_resp is resp
        assert not hasattr(req, "_cache_key")


# ── LRU Eviction ─────────────────────────────────────────────────


class TestLRUEviction:
    """Test LRU eviction when max_entries is exceeded."""

    def test_evicts_oldest_when_full(self):
        cache = ResponseCache(ttl=60, max_entries=2)

        for i in range(3):
            req = make_request(method="GET", url=f"/api/item/{i}")
            resp = make_response()
            cache.before_cache(req, resp)
            resp_out = make_response(body=f"item-{i}", status_code=200)
            cache.after_cache(req, resp_out)

        assert cache.cache_stats()["size"] == 2

        # First item should have been evicted
        req_check = make_request(method="GET", url="/api/item/0")
        resp_check = make_response()
        ret = serve(cache, req_check, resp_check)
        assert ret is resp_check  # miss — evicted

        # Third item should still be cached
        req_check2 = make_request(method="GET", url="/api/item/2")
        resp_check2 = make_response()
        ret2 = serve(cache, req_check2, resp_check2)
        assert body_of(ret2) == "item-2"  # hit


# ── Status Codes ──────────────────────────────────────────────────


class TestStatusCodes:
    """Test that only cacheable status codes are stored."""

    def test_200_is_cached_by_default(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/ok")
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body="ok", status_code=200)
        cache.after_cache(req, resp_out)
        assert cache.cache_stats()["size"] == 1

    def test_404_is_not_cached_by_default(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/missing")
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body="not found", status_code=404)
        cache.after_cache(req, resp_out)
        assert cache.cache_stats()["size"] == 0

    def test_custom_status_codes(self):
        cache = ResponseCache(ttl=60, status_codes=[200, 404])
        req = make_request(method="GET", url="/api/custom")
        resp = make_response()
        cache.before_cache(req, resp)
        resp_out = make_response(body="not found", status_code=404)
        cache.after_cache(req, resp_out)
        assert cache.cache_stats()["size"] == 1


# ── Non-GET Methods ───────────────────────────────────────────────


class TestNonGetMethods:
    """Test that POST, PUT, etc. are never cached."""

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_non_get_method_not_cached(self, method):
        cache = ResponseCache(ttl=60)
        req = make_request(method=method, url="/api/write")
        resp = make_response()

        cache.before_cache(req, resp)
        assert not hasattr(req, "_cache_key")


# ── Stats ─────────────────────────────────────────────────────────


class TestCacheStats:
    """Test cache_stats() returns correct hits/misses/size."""

    def test_initial_stats(self):
        cache = ResponseCache(ttl=60)
        stats = cache.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0
        assert "backend" in stats

    def test_stats_after_miss_and_hit(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/stats")
        resp = make_response()

        cache.before_cache(req, resp)  # miss
        resp_out = make_response(body="data", status_code=200)
        cache.after_cache(req, resp_out)

        req2 = make_request(method="GET", url="/api/stats")
        resp2 = make_response()
        cache.before_cache(req2, resp2)  # hit

        stats = cache.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1


# ── Clear Cache ───────────────────────────────────────────────────


class TestClearCache:
    """Test clear_cache() resets everything."""

    def test_clear_resets_store_and_stats(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/clear")
        resp = make_response()

        cache.before_cache(req, resp)
        resp_out = make_response(body="data", status_code=200)
        cache.after_cache(req, resp_out)

        cache.clear_cache()
        stats = cache.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0


# ── Per-Route TTL Override ────────────────────────────────────────


class TestPerRouteTTL:
    """Test per-route TTL override via _route_meta."""

    def test_route_meta_overrides_default_ttl(self):
        """The per-route max_age is what the MISS advertises, not the default."""
        cache = ResponseCache(ttl=60)
        req = make_request(
            method="GET",
            url="/api/custom-ttl",
            cache_max_age=1,
        )
        resp = make_response(body='{"a": 1}')

        cache.before_cache(req, resp)
        cache.after_cache(req, resp)
        assert header_of(resp, "X-Cache-TTL") == "1"

    def test_no_route_meta_uses_default_ttl(self):
        cache = ResponseCache(ttl=60)
        req = make_request(method="GET", url="/api/default-ttl")
        resp = make_response(body='{"a": 1}')

        cache.before_cache(req, resp)
        cache.after_cache(req, resp)
        assert header_of(resp, "X-Cache-TTL") == "60"

    def test_route_meta_ttl_expiry(self):
        cache = ResponseCache(ttl=300, cleanup_interval=9999)
        req = make_request(
            method="GET",
            url="/api/short-lived",
            cache_max_age=1,
        )
        resp = make_response()

        cache.before_cache(req, resp)
        resp_out = make_response(body="short", status_code=200)
        cache.after_cache(req, resp_out)

        time.sleep(1.1)

        req2 = make_request(method="GET", url="/api/short-lived")
        resp2 = make_response()
        ret = serve(cache, req2, resp2)
        # Should be a miss (expired after 1s despite 300s default)
        assert ret is resp2


# ── Thread Safety ─────────────────────────────────────────────────


class TestThreadSafety:
    """Test concurrent access to the cache."""

    def test_concurrent_reads_and_writes(self):
        cache = ResponseCache(ttl=60, max_entries=100)
        errors = []

        def writer(idx):
            try:
                req = make_request(method="GET", url=f"/api/thread/{idx}")
                resp = make_response()
                cache.before_cache(req, resp)
                resp_out = make_response(body=f"val-{idx}", status_code=200)
                cache.after_cache(req, resp_out)
            except Exception as e:
                errors.append(e)

        def reader(idx):
            try:
                req = make_request(method="GET", url=f"/api/thread/{idx}")
                resp = make_response()
                cache.before_cache(req, resp)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        stats = cache.cache_stats()
        assert stats["size"] <= 100


# ── Direct Cache API ──────────────────────────────────────────────


class TestDirectCacheAPI:
    """Test the module-level cache_get/cache_set/cache_delete/cache_clear/cache_stats."""

    def setup_method(self):
        # Reset the module-level singletons before each test
        cache_module._default_cache = None
        cache_module._default_backend = None
        cache_module._default_ttl = None

    def test_cache_set_and_get(self):
        cache_set("test_key", {"hello": "world"}, ttl=60)
        result = cache_get("test_key")
        assert result == {"hello": "world"}

    def test_cache_get_missing(self):
        result = cache_get("nonexistent_key_12345")
        assert result is None

    def test_cache_delete(self):
        cache_set("del_key", "value", ttl=60)
        assert cache_delete("del_key") is True
        assert cache_get("del_key") is None
        assert cache_delete("del_key") is False

    def test_cache_clear(self):
        cache_set("a", 1, ttl=60)
        cache_set("b", 2, ttl=60)
        cache_clear()
        stats = cache_stats()
        assert stats["size"] == 0

    def test_cache_stats_has_backend(self):
        stats = cache_stats()
        assert "backend" in stats
        assert stats["backend"] == "memory"  # default

    def test_cache_stats_tracks_hits_misses(self):
        cache_clear()
        cache_set("x", "val", ttl=60)
        cache_get("x")       # hit
        cache_get("missing")  # miss
        stats = cache_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1


# ── Module-Level Convenience Functions (legacy) ──────────────────


class TestModuleLevelFunctions:
    """Test the module-level cache_stats and clear_cache functions."""

    def setup_method(self):
        # Reset the module-level singleton before each test
        cache_module._default_cache = None
        cache_module._default_backend = None
        cache_module._default_ttl = None

    def test_clear_cache_resets_default(self):
        # Populate the default cache
        default = _get_default()
        req = make_request(method="GET", url="/api/module")
        resp = make_response()
        default.before_cache(req, resp)
        resp_out = make_response(body="mod", status_code=200)
        default.after_cache(req, resp_out)
        assert default.cache_stats()["size"] == 1

        clear_cache()
        assert default.cache_stats()["size"] == 0

    def test_get_default_creates_singleton(self):
        d1 = _get_default()
        d2 = _get_default()
        assert d1 is d2


# ── File Backend with env var ─────────────────────────────────────


class TestFileBackendEnv:
    """Test file backend creation via env vars."""

    CACHE_DIR = "/tmp/tina4_env_cache_test"

    def setup_method(self):
        import shutil
        shutil.rmtree(self.CACHE_DIR, ignore_errors=True)
        cache_module._default_backend = None
        cache_module._default_ttl = None

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.CACHE_DIR, ignore_errors=True)
        for key in ["TINA4_CACHE_BACKEND", "TINA4_CACHE_DIR"]:
            os.environ.pop(key, None)
        cache_module._default_backend = None

    def test_file_backend_via_env(self):
        os.environ["TINA4_CACHE_BACKEND"] = "file"
        os.environ["TINA4_CACHE_DIR"] = self.CACHE_DIR
        backend = _create_backend()
        assert backend.name() == "file"

        backend.set("env_key", {"test": True}, ttl=60)
        result = backend.get("env_key")
        assert result == {"test": True}


# ── RFC 9111 conformance (shared-cache rules) ─────────────────────


class TestSharedCacheAuthorization:
    """RFC 9111 s3: a shared cache MUST NOT store a response to a request
    carrying Authorization unless a response directive allows shared caching.

    Without this the key is method + URL only, so one authenticated caller's
    body is replayed to every later caller of the same URL — including, where
    the cache sits ahead of the auth gate, an unauthenticated one.
    """

    def test_response_cache_does_not_store_a_response_to_an_authorized_request(self):
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        alice = make_request(url="/api/me", headers={"Authorization": "Bearer alice-token"})
        alice_resp = make_response(body='{"user": "alice", "balance": 42}')
        cache.before_cache(alice, alice_resp)
        cache.after_cache(alice, alice_resp)

        # A later caller of the same URL must NOT see alice's body.
        bob = make_request(url="/api/me", headers={"Authorization": "Bearer bob-token"})
        bob_out = serve(cache, bob, make_response())
        assert "alice" not in body_of(bob_out)

        anon = make_request(url="/api/me")
        anon_out = serve(cache, anon, make_response())
        assert "alice" not in body_of(anon_out)

    def test_response_cache_stores_an_authorized_response_when_cache_control_public(self):
        """s3.5's escape hatch: public / s-maxage / must-revalidate opt back in."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        req = make_request(url="/api/rates", headers={"Authorization": "Bearer any-token"})
        resp = make_response(body='{"usd": 1.0}')
        resp.header("Cache-Control", "public, max-age=60")
        cache.before_cache(req, resp)
        cache.after_cache(req, resp)

        later = make_request(url="/api/rates", headers={"Authorization": "Bearer other"})
        out = serve(cache, later, make_response())
        assert body_of(out) == '{"usd": 1.0}'

    def test_response_cache_serves_an_unauthenticated_get(self):
        """Positive control: the cache still works for ordinary public GETs."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        req = make_request(url="/api/public")
        resp = make_response(body='{"public": true}')
        cache.before_cache(req, resp)
        cache.after_cache(req, resp)

        out = serve(cache, make_request(url="/api/public"), make_response())
        assert body_of(out) == '{"public": true}'
        assert header_of(out, "X-Cache") == "HIT"


class TestNoStoreAndPrivate:
    """RFC 9111 s3: "no-store" forbids storage in ANY cache and "private"
    forbids it in a shared one.

    Neither was honoured before 3.13.108, so a handler had no way at all to keep
    a response out of this cache — setting the correct standard header did
    nothing and the body was still replayed to the next caller of that URL.
    """

    @pytest.mark.parametrize("directive", ["no-store", "private", "no-cache"])
    def test_a_response_refusing_storage_is_not_stored(self, directive):
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        first = make_request(url=f"/api/secret/{directive}")
        resp = make_response(body='{"token": "ALICE-SECRET"}')
        resp.header("Cache-Control", directive)
        cache.before_cache(first, resp)
        cache.after_cache(first, resp)

        later = make_request(url=f"/api/secret/{directive}")
        out = serve(cache, later, make_response())
        assert "ALICE-SECRET" not in body_of(out)

    def test_the_directive_is_read_as_a_token_not_a_substring(self):
        """``no-cache="Set-Cookie"`` is still no-cache; a value must not hide it."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        first = make_request(url="/api/qualified")
        resp = make_response(body='{"token": "ALICE-SECRET"}')
        resp.header("Cache-Control", 'no-cache="Set-Cookie"')
        cache.before_cache(first, resp)
        cache.after_cache(first, resp)

        out = serve(cache, make_request(url="/api/qualified"), make_response())
        assert "ALICE-SECRET" not in body_of(out)


class TestSessionCookieIsolation:
    """RFC 9111 s3, applied to the caller identified by a session rather than by
    an Authorization header.

    The key is method + URL, so storing a response built for a signed-in caller
    replays it to whoever requests that URL next. Tina4's own session mechanism
    is a cookie, so guarding Authorization alone left every session-authenticated
    page replayable — reachable on a stock install through the documented
    ``middleware=["ResponseCache:300"]`` form.
    """

    def test_one_sessions_response_is_not_replayed_to_another(self):
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        alice = make_request(url="/api/me", headers={"Cookie": "session=ALICE"})
        alice_resp = make_response(body='{"user": "ALICE", "cart_total": "R 1499.00"}')
        cache.before_cache(alice, alice_resp)
        cache.after_cache(alice, alice_resp)

        bob = make_request(url="/api/me", headers={"Cookie": "session=BOB"})
        assert "ALICE" not in body_of(serve(cache, bob, make_response()))

        anon = make_request(url="/api/me")
        assert "ALICE" not in body_of(serve(cache, anon, make_response()))

    def test_a_response_installing_a_session_is_not_stored(self):
        """Set-Cookie on the way out marks the body as built for one caller."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        first = make_request(url="/api/login-landing")
        resp = make_response(body='{"welcome": "ALICE"}')
        resp.header("Set-Cookie", "session=ALICE; Path=/; HttpOnly")
        cache.before_cache(first, resp)
        cache.after_cache(first, resp)

        out = serve(cache, make_request(url="/api/login-landing"), make_response())
        assert "ALICE" not in body_of(out)

    def test_a_cookie_bearing_request_still_caches_when_marked_public(self):
        """The same s3.5 escape hatch the Authorization path already honours."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        req = make_request(url="/api/products", headers={"Cookie": "session=ALICE"})
        resp = make_response(body='{"products": []}')
        resp.header("Cache-Control", "public, max-age=60")
        cache.before_cache(req, resp)
        cache.after_cache(req, resp)

        later = make_request(url="/api/products", headers={"Cookie": "session=BOB"})
        assert body_of(serve(cache, later, make_response())) == '{"products": []}'

    def test_traffic_without_cookies_is_unaffected(self):
        """Positive control: the ordinary public GET path keeps its hit rate."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        req = make_request(url="/api/anon")
        resp = make_response(body='{"public": true}')
        cache.before_cache(req, resp)
        cache.after_cache(req, resp)

        out = serve(cache, make_request(url="/api/anon"), make_response())
        assert body_of(out) == '{"public": true}'
        assert header_of(out, "X-Cache") == "HIT"


class TestVary:
    """RFC 9111 s4.1: a stored response with Vary is only reusable when every
    nominated request header matches the request that caused it to be stored."""

    def test_response_cache_honours_vary_on_a_nominated_request_header(self):
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        en = make_request(url="/api/greeting", headers={"Accept-Language": "en"})
        en_resp = make_response(body='"hello"')
        en_resp.header("Vary", "Accept-Language")
        cache.before_cache(en, en_resp)
        cache.after_cache(en, en_resp)

        # Same header value → HIT.
        same = serve(cache, 
            make_request(url="/api/greeting", headers={"Accept-Language": "en"}), make_response())
        assert body_of(same) == '"hello"'

        # Different value → MISS, the handler must run again.
        other = serve(cache, 
            make_request(url="/api/greeting", headers={"Accept-Language": "fr"}), make_response())
        assert body_of(other) != '"hello"'

        # Absent only matches absent.
        absent = serve(cache, make_request(url="/api/greeting"), make_response())
        assert body_of(absent) != '"hello"'

    def test_response_cache_never_stores_vary_asterisk(self):
        """s4.1: 'A stored response with a Vary header field value containing a
        member "*" always fails to match', so storing one is pointless."""
        cache = ResponseCache(ttl=60)
        cache.clear_cache()

        req = make_request(url="/api/anything")
        resp = make_response(body='"never-reusable"')
        resp.header("Vary", "*")
        cache.before_cache(req, resp)
        cache.after_cache(req, resp)

        out = serve(cache, make_request(url="/api/anything"), make_response())
        assert body_of(out) != '"never-reusable"'
