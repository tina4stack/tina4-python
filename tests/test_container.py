# Tests for tina4_python.container — Lightweight DI container
import threading
import pytest
from tina4_python.container import Container


# ── interface contract (cross-framework rename guard) ────────────


class TestContainerContract:
    """One consolidated contract test: the public DI surface must stay stable.

    Cheap guard against a silent rename drifting Container out of parity with
    the PHP / Ruby / Node containers. Behaviour of each method is asserted by
    the dedicated tests below; this only locks the method *set*.
    """

    def test_public_method_set(self):
        c = Container()
        for name in ("register", "singleton", "get", "has", "reset", "reset_all"):
            assert callable(getattr(c, name)), f"Container.{name} missing or not callable"


# ── register() and get() — transient ─────────────────────────────


class TestTransientRegistration:
    """Test register() creates a new instance on every get()."""

    def test_get_returns_factory_result(self):
        c = Container()
        c.register("greeting", lambda: "hello")
        assert c.get("greeting") == "hello"

    def test_get_returns_new_instance_each_call(self):
        c = Container()
        c.register("obj", lambda: object())
        a = c.get("obj")
        b = c.get("obj")
        assert a is not b

    def test_register_with_class_factory(self):
        c = Container()

        class Service:
            def __init__(self):
                self.value = "ready"

        c.register("svc", Service)
        first = c.get("svc")
        second = c.get("svc")
        # The factory really ran: a constructed Service with its init state.
        assert isinstance(first, Service)
        assert first.value == "ready"
        # Transient: a class factory yields a brand-new instance each get().
        assert first is not second


# ── singleton() — lazy, same instance ────────────────────────────


class TestSingletonRegistration:
    """Test singleton() returns the same instance every call."""

    def test_singleton_returns_same_instance(self):
        c = Container()
        c.singleton("db", lambda: {"conn": "sqlite"})
        a = c.get("db")
        b = c.get("db")
        assert a is b

    def test_singleton_is_lazy(self):
        """Factory should not be called until first get()."""
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return "created"

        c = Container()
        c.singleton("lazy", factory)
        assert call_count == 0
        c.get("lazy")
        assert call_count == 1
        c.get("lazy")
        assert call_count == 1  # not called again


# ── has() ─────────────────────────────────────────────────────────


class TestHas:
    """Test has() returns True/False correctly."""

    def test_has_returns_true_for_registered(self):
        c = Container()
        c.register("a", lambda: 1)
        assert c.has("a") is True

    def test_has_returns_false_for_unregistered(self):
        c = Container()
        assert c.has("nope") is False

    def test_has_true_for_singleton(self):
        c = Container()
        c.singleton("s", lambda: "x")
        assert c.has("s") is True


# ── get() raises KeyError ─────────────────────────────────────────


class TestGetKeyError:
    """Test get() raises KeyError for unregistered names."""

    def test_raises_key_error(self):
        c = Container()
        with pytest.raises(KeyError, match="service not registered"):
            c.get("missing")

    def test_raises_after_reset_all(self):
        """reset_all() wipes everything — get() raises KeyError after."""
        c = Container()
        c.register("temp", lambda: 1)
        c.reset_all()
        with pytest.raises(KeyError):
            c.get("temp")


# ── reset() ───────────────────────────────────────────────────────


class TestReset:
    """Test reset() — clears cached singleton instances; keeps factories.

    The 3.13.0 contract changed: reset() used to wipe everything (factories
    AND cached singletons). Now reset() only clears the cache so factories
    re-run on next get(); reset_all() wipes everything.
    """

    def test_reset_keeps_factories_clears_cache(self):
        c = Container()
        c.register("a", lambda: object())
        c.singleton("b", lambda: object())
        # Prime the singleton cache so reset() has something to clear.
        cached = c.get("b")
        assert c.get("b") is cached  # memoised before reset

        c.reset()

        # Factories are still wired after reset().
        assert c.has("a") is True
        assert c.has("b") is True
        # The cache really cleared: the singleton factory re-runs and yields a
        # brand-new instance, so the post-reset value is NOT the old cached one.
        after = c.get("b")
        assert after is not cached
        # ...and it re-memoises again going forward.
        assert c.get("b") is after

    def test_reset_all_clears_everything(self):
        c = Container()
        c.register("a", lambda: 1)
        c.singleton("b", lambda: 2)
        c.reset_all()
        assert c.has("a") is False
        assert c.has("b") is False

    def test_reset_allows_re_registration(self):
        c = Container()
        c.register("x", lambda: "old")
        c.reset_all()
        c.register("x", lambda: "new")
        assert c.get("x") == "new"


# ── Overwriting a Registration ────────────────────────────────────


class TestOverwrite:
    """Test that re-registering a name overwrites the previous factory."""

    def test_overwrite_transient(self):
        c = Container()
        c.register("svc", lambda: "v1")
        assert c.get("svc") == "v1"
        c.register("svc", lambda: "v2")
        assert c.get("svc") == "v2"

    def test_overwrite_singleton_with_transient(self):
        c = Container()
        c.singleton("svc", lambda: object())
        singleton_val = c.get("svc")
        assert c.get("svc") is singleton_val  # same instance while singleton

        c.register("svc", lambda: object())
        a = c.get("svc")
        b = c.get("svc")
        assert a is not b  # now transient — new instance each call

    def test_overwrite_transient_with_singleton(self):
        c = Container()
        c.register("svc", lambda: object())
        a = c.get("svc")
        b = c.get("svc")
        assert a is not b

        c.singleton("svc", lambda: object())
        x = c.get("svc")
        y = c.get("svc")
        assert x is y  # now singleton


# ── Factory Receives No Arguments ─────────────────────────────────


class TestFactoryNoArgs:
    """Test that factories are called with no arguments."""

    def test_factory_called_with_zero_args(self):
        received_args = []

        def factory(*args, **kwargs):
            received_args.append((args, kwargs))
            return "ok"

        c = Container()
        c.register("check", factory)
        c.get("check")
        assert received_args == [((), {})]

    def test_non_callable_raises_type_error(self):
        c = Container()
        with pytest.raises(TypeError, match="must be callable"):
            c.register("bad", "not a callable")

    def test_singleton_non_callable_raises_type_error(self):
        c = Container()
        with pytest.raises(TypeError, match="must be callable"):
            c.singleton("bad", 42)


# ── Thread Safety ─────────────────────────────────────────────────


class TestThreadSafety:
    """Test concurrent access to singleton resolution."""

    def test_concurrent_singleton_get_returns_same_instance(self):
        c = Container()
        c.singleton("shared", lambda: object())

        results = []
        errors = []

        def getter():
            try:
                results.append(c.get("shared"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=getter) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert len(results) == 20
        # All results should be the same instance
        assert all(r is results[0] for r in results)

    def test_concurrent_register_and_get(self):
        c = Container()
        errors = []
        resolved = {}

        def register_and_get(idx):
            try:
                name = f"svc-{idx}"
                # Bind idx now so each closure captures its own value.
                c.register(name, lambda value=idx: value)
                resolved[name] = c.get(name)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_and_get, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        # Every concurrent registration is intact and resolves to its own value
        # (no cross-talk between threads sharing the one container/lock).
        assert len(resolved) == 20
        for i in range(20):
            assert c.has(f"svc-{i}") is True
            assert resolved[f"svc-{i}"] == i
            assert c.get(f"svc-{i}") == i


# ── Multiple Independent Containers ───────────────────────────────


class TestMultipleContainers:
    """Test that separate Container instances are independent."""

    def test_independent_registrations(self):
        c1 = Container()
        c2 = Container()

        c1.register("name", lambda: "alice")
        c2.register("name", lambda: "bob")

        assert c1.get("name") == "alice"
        assert c2.get("name") == "bob"

    def test_reset_all_one_does_not_affect_other(self):
        c1 = Container()
        c2 = Container()

        c1.register("x", lambda: 1)
        c2.register("x", lambda: 2)

        c1.reset_all()
        assert c1.has("x") is False
        assert c2.has("x") is True
        assert c2.get("x") == 2

    def test_singleton_instances_are_independent(self):
        c1 = Container()
        c2 = Container()

        c1.singleton("obj", lambda: object())
        c2.singleton("obj", lambda: object())

        assert c1.get("obj") is not c2.get("obj")
