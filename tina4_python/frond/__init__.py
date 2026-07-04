# Tina4 Frond — Zero-dependency template engine.
"""
Twig-like template engine built from scratch.

    from tina4_python.frond import Frond

    engine = Frond(template_dir="src/templates")
    output = engine.render("page.html", {"name": "World"})
"""
import inspect

from tina4_python.frond.engine import Frond


async def live_endpoint(name, request, response):
    """GET /__frond/live/{name} - re-render a registered {% live %} fragment.

    Resolves the @live_source provider for <name>, runs it with the LIVE request
    so auth and session scoping re-apply on every refresh (a live "my cart"
    cannot leak another user's data), renders the registered fragment, and
    returns the HTML. 404 when the name is unknown or its fragment has not been
    registered yet (the page carrying the block has not rendered).
    """
    provider = Frond._class_live_sources.get(name)
    if name not in Frond._class_live_fragments and provider is None:
        return response("live block not found: " + str(name), 404)
    context = {}
    if provider is not None:
        result = provider(request)
        if inspect.isawaitable(result):
            result = await result
        context = result or {}
    html = Frond.render_live(name, context)
    if html is None:
        return response("live fragment not registered yet: " + str(name), 404)
    return response(html)


async def push_live(name, data=None):
    """Re-render the '<name>' live fragment and push it to connected clients.

    Renders via Frond.render_live(name, data) and broadcasts a {type, name, html}
    envelope over WebSocket: to the ws path the block declared (data-ws), or to a
    room named <name> if the block declared none. Apps call this after a state
    change (a new chat message, an order update). Returns the rendered HTML, or
    None when the fragment is not registered (its page has not rendered).
    """
    html = Frond.render_live(name, data or {})
    if html is None:
        return None
    import json
    envelope = json.dumps({"type": "live", "name": name, "html": html})
    try:
        from tina4_python.core.server import _ws_manager
        ws_path = Frond._class_live_ws_paths.get(name)
        if ws_path:
            await _ws_manager.broadcast(envelope, path=ws_path)
        else:
            await _ws_manager.broadcast_to_room(name, envelope)
    except Exception as exc:
        try:
            from tina4_python.debug import Log
            Log.error("push_live(" + str(name) + ") broadcast failed: " + str(exc))
        except Exception:
            pass
    return html


def live_source(name: str):
    """Register a data provider for a {% live %} block.

    The decorated function receives the request and returns the context dict
    used to re-render the fragment on refresh:

        @live_source("notifications")
        async def notifications(request):
            return {"items": Notification.where("user_id = ?", [request.session["uid"]])}
    """
    def _wrap(fn):
        Frond._class_live_sources[name] = fn
        return fn
    return _wrap


__all__ = ["Frond", "live_source", "live_endpoint", "push_live"]
