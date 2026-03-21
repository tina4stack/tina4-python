# Tests for tina4_python.core.events (v3)
import pytest
from tina4_python.core.events import on, off, emit, emit_async, once, listeners, events, clear


@pytest.fixture(autouse=True)
def clean_events():
    clear()
    yield
    clear()


class TestOn:

    def test_register_listener(self):
        @on("test.event")
        def handler(data):
            pass
        assert handler in listeners("test.event")

    def test_register_multiple_listeners(self):
        @on("test.event")
        def handler_a(data):
            pass

        @on("test.event")
        def handler_b(data):
            pass
        assert len(listeners("test.event")) == 2

    def test_direct_call_registration(self):
        def handler(data):
            pass
        on("test.event", handler)
        assert handler in listeners("test.event")

    def test_returns_original_function(self):
        def handler():
            pass
        result = on("test.event", handler)
        assert result is handler

    def test_decorator_returns_original_function(self):
        @on("test.event")
        def handler():
            pass
        assert callable(handler)


class TestOff:

    def test_remove_specific_listener(self):
        @on("test.event")
        def handler():
            pass
        off("test.event", handler)
        assert handler not in listeners("test.event")

    def test_remove_all_listeners_for_event(self):
        @on("test.event")
        def handler_a():
            pass

        @on("test.event")
        def handler_b():
            pass
        off("test.event")
        assert listeners("test.event") == []

    def test_remove_nonexistent_event_no_error(self):
        off("nonexistent.event")

    def test_remove_nonexistent_listener_no_error(self):
        @on("test.event")
        def handler():
            pass
        def other():
            pass
        off("test.event", other)
        assert handler in listeners("test.event")


class TestEmit:

    def test_emit_calls_listener(self):
        results = []

        @on("test.event")
        def handler(value):
            results.append(value)

        emit("test.event", "hello")
        assert results == ["hello"]

    def test_emit_returns_results(self):
        @on("test.event")
        def handler(x):
            return x * 2

        results = emit("test.event", 5)
        assert results == [10]

    def test_emit_calls_multiple_listeners(self):
        call_order = []

        @on("test.event")
        def handler_a():
            call_order.append("a")

        @on("test.event")
        def handler_b():
            call_order.append("b")

        emit("test.event")
        assert len(call_order) == 2

    def test_emit_nonexistent_event_returns_empty(self):
        results = emit("nonexistent.event")
        assert results == []

    def test_emit_with_kwargs(self):
        captured = {}

        @on("test.event")
        def handler(**kwargs):
            captured.update(kwargs)

        emit("test.event", name="Alice")
        assert captured == {"name": "Alice"}


class TestPriority:

    def test_higher_priority_runs_first(self):
        call_order = []

        @on("test.event", priority=1)
        def low():
            call_order.append("low")

        @on("test.event", priority=10)
        def high():
            call_order.append("high")

        emit("test.event")
        assert call_order == ["high", "low"]

    def test_same_priority_preserves_registration_order(self):
        call_order = []

        @on("test.event", priority=0)
        def first():
            call_order.append("first")

        @on("test.event", priority=0)
        def second():
            call_order.append("second")

        emit("test.event")
        assert call_order[0] == "first"


class TestOnce:

    def test_once_fires_only_once(self):
        call_count = [0]

        @once("test.event")
        def handler():
            call_count[0] += 1

        emit("test.event")
        emit("test.event")
        assert call_count[0] == 1

    def test_once_returns_original_function(self):
        @once("test.event")
        def handler():
            pass
        assert callable(handler)

    def test_once_with_priority(self):
        call_order = []

        @on("test.event", priority=0)
        def always():
            call_order.append("always")

        @once("test.event", priority=10)
        def one_time():
            call_order.append("once")

        emit("test.event")
        assert call_order == ["once", "always"]

        call_order.clear()
        emit("test.event")
        assert call_order == ["always"]

    def test_once_direct_call(self):
        call_count = [0]
        def handler():
            call_count[0] += 1
        once("test.event", handler)
        emit("test.event")
        emit("test.event")
        assert call_count[0] == 1


class TestEmitAsync:

    @pytest.mark.asyncio
    async def test_emit_async_calls_sync_listener(self):
        results = []

        @on("test.event")
        def handler(val):
            results.append(val)

        await emit_async("test.event", "sync")
        assert results == ["sync"]

    @pytest.mark.asyncio
    async def test_emit_async_calls_async_listener(self):
        results = []

        @on("test.event")
        async def handler(val):
            results.append(val)

        await emit_async("test.event", "async")
        assert results == ["async"]

    @pytest.mark.asyncio
    async def test_emit_async_returns_results(self):
        @on("test.event")
        async def handler(x):
            return x + 1

        results = await emit_async("test.event", 10)
        assert results == [11]

    @pytest.mark.asyncio
    async def test_emit_async_mixed_listeners(self):
        results = []

        @on("test.event")
        def sync_handler():
            results.append("sync")

        @on("test.event")
        async def async_handler():
            results.append("async")

        await emit_async("test.event")
        assert "sync" in results
        assert "async" in results


class TestIntrospection:

    def test_listeners_returns_functions(self):
        @on("test.event")
        def handler():
            pass
        fns = listeners("test.event")
        assert handler in fns

    def test_listeners_empty_for_unknown_event(self):
        assert listeners("unknown") == []

    def test_events_lists_registered_events(self):
        @on("event.a")
        def ha():
            pass

        @on("event.b")
        def hb():
            pass

        names = events()
        assert "event.a" in names
        assert "event.b" in names

    def test_clear_removes_all(self):
        @on("event.a")
        def handler():
            pass
        clear()
        assert events() == []
        assert listeners("event.a") == []
