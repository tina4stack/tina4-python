# Tests for tina4_python.cache — ResponseCache middleware
import os
import time
import threading
import pytest
from unittest.mock import patch
from tina4_python.cache import ResponseCache, _get_default, cache_stats, clear_cache
import tina4_python.cache as cache_module


class MockRequest:
    """Minimal request stub for cache tests."""

    def __init__(self, method="GET", url="/test", params=None, route_meta=None):
        self.method = method
        self.url = url
        self.params = params
        if route_meta is not None:
            self._route_meta = route_meta


class MockResponse:
    """Callable response stub that records what was returned."""

    def __init__(self, body="", status_code=200, content_type="application/json"):
        self.body = body
        self.status_code = status_code
        self.content_type = content_type
        self._called_with = None

    def __call__(self, body=None, status_code=None):
        """Simulate response(body, status_code) call."""
        r = MockResponse(
            body=body if body is not None else self.body,
            status_code=status_code if status_code is not None else self.status_code,
            content_type=self.content_type,
        )
        r._called_with = (body, status_code)
        return r


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


# ── Cache Key Generation ─────────────────────────────────────────


class TestCacheKeyGeneration:
    """Test that cache keys are built correctly from method + URL + params."""

    def test_get_without_params(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/items")
        resp = MockResponse()

        cache.before_cache(req, resp)
        assert req._cache_key == "GET:/api/items"

    def test_get_with_params_sorted(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/items", params={"z": "1", "a": "2"})
        resp = MockResponse()

        cache.before_cache(req, resp)
        assert req._cache_key == "GET:/api/items?a=2&z=1"

    def test_non_get_no_cache_key(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="POST", url="/api/items")
        resp = MockResponse()

        cache.before_cache(req, resp)
        assert not hasattr(req, "_cache_key")


# ── Cache Hit (before_cache) ─────────────────────────────────────


class TestCacheHit:
    """Test that cached responses are returned on cache hit."""

    def test_cache_hit_returns_cached_body(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/data")
        resp = MockResponse()

        # First request — miss
        cache.before_cache(req, resp)
        # Simulate handler producing a response
        resp_out = MockResponse(body='{"result": 1}', status_code=200)
        cache.after_cache(req, resp_out)

        # Second request — hit
        req2 = MockRequest(method="GET", url="/api/data")
        resp2 = MockResponse()
        _, hit_resp = cache.before_cache(req2, resp2)

        assert hit_resp.body == '{"result": 1}'
        assert hit_resp.status_code == 200

    def test_cache_miss_lets_request_through(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/new")
        resp = MockResponse()

        returned_req, returned_resp = cache.before_cache(req, resp)
        # On miss, the original response is returned unchanged
        assert returned_resp is resp
        assert hasattr(req, "_cache_key")


# ── after_cache stores response ──────────────────────────────────


class TestAfterCache:
    """Test that after_cache stores responses correctly."""

    def test_stores_200_response(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/store")
        resp = MockResponse()

        cache.before_cache(req, resp)
        resp_out = MockResponse(body="stored", status_code=200)
        cache.after_cache(req, resp_out)

        stats = cache.cache_stats()
        assert stats["size"] == 1

    def test_does_not_store_without_cache_key(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="POST", url="/api/store")
        resp = MockResponse(body="nope", status_code=200)

        cache.after_cache(req, resp)
        assert cache.cache_stats()["size"] == 0


# ── TTL Expiry ────────────────────────────────────────────────────


class TestTTLExpiry:
    """Test that entries expire after their TTL."""

    def test_entry_expires_after_ttl(self):
        cache = ResponseCache(ttl=1, cleanup_interval=9999)
        req = MockRequest(method="GET", url="/api/expire")
        resp = MockResponse()

        cache.before_cache(req, resp)
        resp_out = MockResponse(body="temp", status_code=200)
        cache.after_cache(req, resp_out)

        # Entry is present
        assert cache.cache_stats()["size"] == 1

        time.sleep(1.1)

        # New request should miss (entry expired)
        req2 = MockRequest(method="GET", url="/api/expire")
        resp2 = MockResponse()
        _, ret = cache.before_cache(req2, resp2)
        # The response should be the original (not cached)
        assert ret is resp2

    def test_ttl_zero_disables_caching(self):
        cache = ResponseCache(ttl=0)
        req = MockRequest(method="GET", url="/api/disabled")
        resp = MockResponse()

        returned_req, returned_resp = cache.before_cache(req, resp)
        assert returned_resp is resp
        assert not hasattr(req, "_cache_key")


# ── LRU Eviction ─────────────────────────────────────────────────


class TestLRUEviction:
    """Test LRU eviction when max_entries is exceeded."""

    def test_evicts_oldest_when_full(self):
        cache = ResponseCache(ttl=60, max_entries=2)

        for i in range(3):
            req = MockRequest(method="GET", url=f"/api/item/{i}")
            resp = MockResponse()
            cache.before_cache(req, resp)
            resp_out = MockResponse(body=f"item-{i}", status_code=200)
            cache.after_cache(req, resp_out)

        assert cache.cache_stats()["size"] == 2

        # First item should have been evicted
        req_check = MockRequest(method="GET", url="/api/item/0")
        resp_check = MockResponse()
        _, ret = cache.before_cache(req_check, resp_check)
        assert ret is resp_check  # miss — evicted

        # Third item should still be cached
        req_check2 = MockRequest(method="GET", url="/api/item/2")
        resp_check2 = MockResponse()
        _, ret2 = cache.before_cache(req_check2, resp_check2)
        assert ret2.body == "item-2"  # hit


# ── Status Codes ──────────────────────────────────────────────────


class TestStatusCodes:
    """Test that only cacheable status codes are stored."""

    def test_200_is_cached_by_default(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/ok")
        resp = MockResponse()
        cache.before_cache(req, resp)
        resp_out = MockResponse(body="ok", status_code=200)
        cache.after_cache(req, resp_out)
        assert cache.cache_stats()["size"] == 1

    def test_404_is_not_cached_by_default(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/missing")
        resp = MockResponse()
        cache.before_cache(req, resp)
        resp_out = MockResponse(body="not found", status_code=404)
        cache.after_cache(req, resp_out)
        assert cache.cache_stats()["size"] == 0

    def test_custom_status_codes(self):
        cache = ResponseCache(ttl=60, status_codes=[200, 404])
        req = MockRequest(method="GET", url="/api/custom")
        resp = MockResponse()
        cache.before_cache(req, resp)
        resp_out = MockResponse(body="not found", status_code=404)
        cache.after_cache(req, resp_out)
        assert cache.cache_stats()["size"] == 1


# ── Non-GET Methods ───────────────────────────────────────────────


class TestNonGetMethods:
    """Test that POST, PUT, etc. are never cached."""

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_non_get_method_not_cached(self, method):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method=method, url="/api/write")
        resp = MockResponse()

        cache.before_cache(req, resp)
        assert not hasattr(req, "_cache_key")


# ── Stats ─────────────────────────────────────────────────────────


class TestCacheStats:
    """Test cache_stats() returns correct hits/misses/size."""

    def test_initial_stats(self):
        cache = ResponseCache(ttl=60)
        stats = cache.cache_stats()
        assert stats == {"hits": 0, "misses": 0, "size": 0}

    def test_stats_after_miss_and_hit(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/stats")
        resp = MockResponse()

        cache.before_cache(req, resp)  # miss
        resp_out = MockResponse(body="data", status_code=200)
        cache.after_cache(req, resp_out)

        req2 = MockRequest(method="GET", url="/api/stats")
        resp2 = MockResponse()
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
        req = MockRequest(method="GET", url="/api/clear")
        resp = MockResponse()

        cache.before_cache(req, resp)
        resp_out = MockResponse(body="data", status_code=200)
        cache.after_cache(req, resp_out)

        cache.clear_cache()
        stats = cache.cache_stats()
        assert stats == {"hits": 0, "misses": 0, "size": 0}


# ── Per-Route TTL Override ────────────────────────────────────────


class TestPerRouteTTL:
    """Test per-route TTL override via _route_meta."""

    def test_route_meta_overrides_default_ttl(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(
            method="GET",
            url="/api/custom-ttl",
            route_meta={"cache_max_age": 1},
        )
        resp = MockResponse()

        cache.before_cache(req, resp)
        assert req._cache_ttl == 1

    def test_no_route_meta_uses_default_ttl(self):
        cache = ResponseCache(ttl=60)
        req = MockRequest(method="GET", url="/api/default-ttl")
        resp = MockResponse()

        cache.before_cache(req, resp)
        assert req._cache_ttl == 60

    def test_route_meta_ttl_expiry(self):
        cache = ResponseCache(ttl=300, cleanup_interval=9999)
        req = MockRequest(
            method="GET",
            url="/api/short-lived",
            route_meta={"cache_max_age": 1},
        )
        resp = MockResponse()

        cache.before_cache(req, resp)
        resp_out = MockResponse(body="short", status_code=200)
        cache.after_cache(req, resp_out)

        time.sleep(1.1)

        req2 = MockRequest(method="GET", url="/api/short-lived")
        resp2 = MockResponse()
        _, ret = cache.before_cache(req2, resp2)
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
                req = MockRequest(method="GET", url=f"/api/thread/{idx}")
                resp = MockResponse()
                cache.before_cache(req, resp)
                resp_out = MockResponse(body=f"val-{idx}", status_code=200)
                cache.after_cache(req, resp_out)
            except Exception as e:
                errors.append(e)

        def reader(idx):
            try:
                req = MockRequest(method="GET", url=f"/api/thread/{idx}")
                resp = MockResponse()
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


# ── Module-Level Convenience Functions ────────────────────────────


class TestModuleLevelFunctions:
    """Test the module-level cache_stats and clear_cache functions."""

    def setup_method(self):
        # Reset the module-level singleton before each test
        cache_module._default_cache = None

    def test_cache_stats_returns_dict(self):
        stats = cache_stats()
        assert isinstance(stats, dict)
        assert "hits" in stats
        assert "misses" in stats
        assert "size" in stats

    def test_clear_cache_resets_default(self):
        # Populate the default cache
        default = _get_default()
        req = MockRequest(method="GET", url="/api/module")
        resp = MockResponse()
        default.before_cache(req, resp)
        resp_out = MockResponse(body="mod", status_code=200)
        default.after_cache(req, resp_out)
        assert cache_stats()["size"] == 1

        clear_cache()
        assert cache_stats()["size"] == 0

    def test_get_default_creates_singleton(self):
        d1 = _get_default()
        d2 = _get_default()
        assert d1 is d2
