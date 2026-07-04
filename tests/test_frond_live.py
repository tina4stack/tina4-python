"""Frond {% live %} blocks — engine layer (parse, first paint, registry, re-render).

Pure-engine tests: no external dependency, no doubles. They exercise the real
Frond engine rendering real template source strings.
"""
import pytest

from tina4_python.frond import Frond, live_source


def test_live_poll_wrapper_first_paint_and_registry():
    Frond.clear_registry()
    engine = Frond()
    src = ('{% live "notifications" poll 5 %}'
           '<ul>{% for n in items %}<li>{{ n }}</li>{% endfor %}</ul>'
           '{% endlive %}')
    out = engine.render_string(src, {"items": ["a", "b"]})

    # Marker element carries the wiring the shared frond.js reads.
    assert 'data-frond-live="notifications"' in out
    assert 'id="live-notifications"' in out
    assert 'data-mode="poll"' in out
    assert 'data-interval="5"' in out
    assert 'data-src="/__frond/live/notifications"' in out
    # First paint is server-rendered inline (no flash, SEO-safe).
    assert "<li>a</li>" in out and "<li>b</li>" in out
    # Body source registered so the endpoint can re-render it.
    assert "notifications" in Frond._class_live_fragments


def test_render_live_re_renders_with_fresh_data():
    Frond.clear_registry()
    engine = Frond()
    engine.render_string('{% live "cart" poll 3 %}<span>{{ count }}</span>{% endlive %}',
                         {"count": 1})
    html = Frond.render_live("cart", {"count": 9})
    assert "<span>9</span>" in html


def test_render_live_unknown_name_returns_none():
    Frond.clear_registry()
    assert Frond.render_live("never-registered", {}) is None


def test_live_sse_mode():
    Frond.clear_registry()
    out = Frond().render_string('{% live "feed" sse %}x{% endlive %}', {})
    assert 'data-mode="sse"' in out
    assert 'data-src="/__frond/live/feed"' in out


def test_live_ws_mode_uses_data_ws():
    Frond.clear_registry()
    out = Frond().render_string('{% live "chat" ws "/ws/chat" %}hi{% endlive %}', {})
    assert 'data-mode="ws"' in out
    assert 'data-ws="/ws/chat"' in out


def test_live_explicit_src_route():
    Frond.clear_registry()
    out = Frond().render_string(
        '{% live "cart" poll 5 src "/fragments/cart" %}0{% endlive %}', {})
    assert 'data-src="/fragments/cart"' in out


def test_live_unknown_transport_raises():
    Frond.clear_registry()
    with pytest.raises(ValueError):
        Frond().render_string('{% live "x" bogus %}y{% endlive %}', {})


def test_live_poll_without_seconds_raises():
    Frond.clear_registry()
    with pytest.raises(ValueError):
        Frond().render_string('{% live "x" poll %}y{% endlive %}', {})


def test_live_cross_origin_src_rejected():
    Frond.clear_registry()
    with pytest.raises(ValueError):
        Frond().render_string(
            '{% live "x" poll 5 src "http://evil.example/x" %}y{% endlive %}', {})


def test_live_nested_raises():
    Frond.clear_registry()
    with pytest.raises(ValueError):
        Frond().render_string(
            '{% live "a" poll 5 %}{% live "b" poll 5 %}z{% endlive %}{% endlive %}', {})


def test_live_source_decorator_registers_provider():
    Frond.clear_registry()

    @live_source("orders")
    def _orders(request):
        return {"n": 3}

    assert "orders" in Frond._class_live_sources
    assert Frond._class_live_sources["orders"] is _orders
