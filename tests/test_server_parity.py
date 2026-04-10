"""Tests for Server cross-framework parity: handle(), start(), stop()."""

from tina4_python.core.server import handle, start, stop


def test_handle_is_callable():
    """handle() exists and is callable."""
    assert callable(handle)


def test_start_is_callable():
    """start() exists and is callable."""
    assert callable(start)


def test_stop_is_callable():
    """stop() exists and is callable."""
    assert callable(stop)
