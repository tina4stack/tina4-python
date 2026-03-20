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


def emit(event: str, *args, **kwargs) -> list:
    """Fire an event synchronously. Returns list of listener results.

        results = emit("user.created", user_data)
    """
    results = []
    for _, listener in _listeners.get(event, []):
        result = listener(*args, **kwargs)
        results.append(result)
    return results


async def emit_async(event: str, *args, **kwargs) -> list:
    """Fire an event, awaiting async listeners. Returns list of results.

        results = await emit_async("order.placed", order)
    """
    results = []
    for _, listener in _listeners.get(event, []):
        if asyncio.iscoroutinefunction(listener):
            result = await listener(*args, **kwargs)
        else:
            result = listener(*args, **kwargs)
        results.append(result)
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
