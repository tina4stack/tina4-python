"""Test event system — demonstrates: @on decorator, emit firing handlers, @once
single-fire, off removal, and priority ordering.

Uses unique event names per test to avoid cross-test pollution, and cleans up
listeners after each test.
"""
import pytest
from tina4_python.core.events import on, emit, once, off, listeners


class TestOnDecorator:
    def test_on_registers_listener(self):
        results = []

        @on("test.on_register")
        def handler(data):
            results.append(data)

        try:
            emit("test.on_register", "hello")
            assert results == ["hello"]
        finally:
            off("test.on_register")

    def test_on_direct_call(self):
        results = []

        def handler(data):
            results.append(data)

        on("test.on_direct", handler)
        try:
            emit("test.on_direct", "world")
            assert results == ["world"]
        finally:
            off("test.on_direct")


class TestEmit:
    def test_emit_fires_multiple_handlers(self):
        results = []

        @on("test.multi")
        def handler_a(data):
            results.append("a")

        @on("test.multi")
        def handler_b(data):
            results.append("b")

        try:
            emit("test.multi", {})
            assert "a" in results
            assert "b" in results
        finally:
            off("test.multi")

    def test_emit_returns_results(self):
        @on("test.returns")
        def handler(x):
            return x * 2

        try:
            results = emit("test.returns", 5)
            assert 10 in results
        finally:
            off("test.returns")

    def test_emit_no_listeners(self):
        results = emit("test.no_listeners", "anything")
        assert results == []


class TestOnce:
    def test_once_fires_only_once(self):
        call_count = []

        @once("test.once_fire")
        def handler(data):
            call_count.append(1)

        try:
            emit("test.once_fire", {})
            emit("test.once_fire", {})
            emit("test.once_fire", {})
            assert len(call_count) == 1
        finally:
            off("test.once_fire")

    def test_once_returns_value(self):
        @once("test.once_return")
        def handler():
            return "done"

        try:
            results = emit("test.once_return")
            assert "done" in results
        finally:
            off("test.once_return")


class TestOff:
    def test_off_removes_specific_listener(self):
        results = []

        @on("test.off_specific")
        def handler_a(data):
            results.append("a")

        @on("test.off_specific")
        def handler_b(data):
            results.append("b")

        off("test.off_specific", handler_a)
        try:
            emit("test.off_specific", {})
            assert "a" not in results
            assert "b" in results
        finally:
            off("test.off_specific")

    def test_off_removes_all_listeners(self):
        @on("test.off_all")
        def handler(data):
            pass

        off("test.off_all")
        remaining = listeners("test.off_all")
        assert len(remaining) == 0


class TestPriority:
    def test_higher_priority_runs_first(self):
        order = []

        @on("test.priority", priority=1)
        def low(data):
            order.append("low")

        @on("test.priority", priority=10)
        def high(data):
            order.append("high")

        @on("test.priority", priority=5)
        def mid(data):
            order.append("mid")

        try:
            emit("test.priority", {})
            assert order == ["high", "mid", "low"]
        finally:
            off("test.priority")

    def test_same_priority_preserves_registration_order(self):
        order = []

        @on("test.same_priority", priority=0)
        def first(data):
            order.append("first")

        @on("test.same_priority", priority=0)
        def second(data):
            order.append("second")

        try:
            emit("test.same_priority", {})
            assert order[0] == "first"
            assert order[1] == "second"
        finally:
            off("test.same_priority")
