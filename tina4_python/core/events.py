# Tina4 Events — Simple observer pattern for decoupled communication.
"""
Zero-dependency event system. Fire events, register listeners.

    from tina4_python.core.events import on, emit

    @on("user.created")
    def send_welcome_email(user):
        print(f"Welcome {user['name']}!")

    @on("user.created")
    def log_signup(user):
        print(f"New signup: {user['email']}")

    emit("user.created", {"name": "Alice", "email": "alice@example.com"})

Async listeners are supported:

    @on("order.placed")
    async def process_order(order):
        await send_notification(order)

    await emit_async("order.placed", order_data)
"""
import asyncio
from collections import defaultdict

# Global listener registry
_listeners: dict[str, list[callable]] = defaultdict(list)


def on(event: str, listener: callable = None, *, priority: int = 0):
    """Register a listener for an event.

    Can be used as a decorator or called directly:

        @on("user.created")
        def handle(data): ...

        on("user.created", my_handler)
        on("user.created", my_handler, priority=10)  # higher = runs first
    """
    def decorator(fn):
        _listeners[event].append((priority, fn))
        # Keep sorted by priority (highest first)
        _listeners[event].sort(key=lambda x: -x[0])
        return fn

    if listener is not None:
        # Direct call: on("event", handler)
        return decorator(listener)

    # Decorator usage: @on("event")
    return decorator


def off(event: str, listener: callable = None):
    """Remove a listener, or all listeners for an event.

        off("user.created", my_handler)  # remove specific
        off("user.created")              # remove all for event
    """
    if listener is None:
        _listeners.pop(event, None)
    else:
        _listeners[event] = [
            (p, fn) for p, fn in _listeners[event] if fn is not listener
        ]


def _log_listener_error(event: str, error: Exception) -> None:
    """Log a listener failure without ever raising. Visible, never silent."""
    try:
        from tina4_python.debug import Log
        Log.warning(
            f"Event listener for '{event}' raised "
            f"{type(error).__name__}: {error}"
        )
    except Exception:
        # The logger itself must never break the event bus. Fall back to
        # stderr so the failure is still surfaced, never swallowed.
        import sys
        print(
            f"[tina4.events] listener for '{event}' raised "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )


def emit(event: str, *args, strict: bool = False, **kwargs) -> list:
    """Fire an event synchronously. Returns list of listener results.

        results = emit("user.created", user_data)

    Each listener is isolated: if one raises, the error is LOGGED
    (``Log.warning`` with the event name + error) and the remaining
    listeners still run. A failed listener contributes a ``None`` slot to
    the results list, so N listeners always yield N results in priority
    order. Pass ``strict=True`` to RE-RAISE on the first listener error
    instead of isolating it. Errors are never silently swallowed.
    """
    results = []
    for _, listener in _listeners.get(event, []):
        try:
            results.append(listener(*args, **kwargs))
        except Exception as error:
            if strict:
                raise
            _log_listener_error(event, error)
            results.append(None)
    return results


async def emit_async(event: str, *args, strict: bool = False, **kwargs) -> list:
    """Fire an event, awaiting async listeners. Returns list of results.

        results = await emit_async("order.placed", order)

    Mirrors :func:`emit` — each awaited listener is isolated: one
    rejection does not abort the others. On a listener error the failure
    is LOGGED and a ``None`` slot is appended; ``strict=True`` re-raises
    on the first error.
    """
    results = []
    for _, listener in _listeners.get(event, []):
        try:
            if asyncio.iscoroutinefunction(listener):
                results.append(await listener(*args, **kwargs))
            else:
                results.append(listener(*args, **kwargs))
        except Exception as error:
            if strict:
                raise
            _log_listener_error(event, error)
            results.append(None)
    return results


def once(event: str, listener: callable = None, *, priority: int = 0):
    """Register a listener that fires only once then auto-removes.

        @once("app.ready")
        def on_ready():
            print("App started!")
    """
    def decorator(fn):
        def wrapper(*args, **kwargs):
            off(event, wrapper)
            return fn(*args, **kwargs)
        wrapper.__wrapped__ = fn
        on(event, wrapper, priority=priority)
        return fn

    if listener is not None:
        return decorator(listener)
    return decorator


def listeners(event: str) -> list[callable]:
    """Get all listeners for an event (in priority order)."""
    return [fn for _, fn in _listeners.get(event, [])]


def events() -> list[str]:
    """List all registered event names."""
    return list(_listeners.keys())


def clear():
    """Remove all listeners for all events."""
    _listeners.clear()
