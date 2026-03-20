# Tina4 Container — Lightweight dependency injection.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Lightweight dependency injection container.

    from tina4_python.container import Container

    container = Container()
    container.register("mailer", lambda: MailService())
    container.singleton("db", lambda: Database("sqlite3:app.db"))

    mailer = container.get("mailer")   # new instance each call
    db     = container.get("db")       # same instance every call

Thread-safe. Factories are plain callables (no arguments).
"""
import threading


class Container:
    """
    Lightweight DI container with transient and singleton registrations.

    - ``register(name, factory)``  — each ``get()`` calls the factory anew.
    - ``singleton(name, factory)`` — first ``get()`` calls the factory;
      subsequent calls return the memoised instance.
    - ``get(name)``                — resolve a dependency by name.
    - ``has(name)``                — check if a name is registered.
    - ``reset()``                  — clear all registrations.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._factories: dict[str, dict] = {}

    def register(self, name: str, factory: callable) -> None:
        """Register a transient factory (called on every ``get()``)."""
        if not callable(factory):
            raise TypeError(f"factory for '{name}' must be callable")
        with self._lock:
            self._factories[name] = {
                "factory": factory,
                "singleton": False,
                "instance": None,
            }

    def singleton(self, name: str, factory: callable) -> None:
        """Register a singleton factory (called once, then memoised)."""
        if not callable(factory):
            raise TypeError(f"factory for '{name}' must be callable")
        with self._lock:
            self._factories[name] = {
                "factory": factory,
                "singleton": True,
                "instance": None,
            }

    def get(self, name: str):
        """
        Resolve a dependency by name.

        Raises ``KeyError`` if the name has not been registered.
        """
        with self._lock:
            entry = self._factories.get(name)
            if entry is None:
                raise KeyError(f"service not registered: {name}")

            if entry["singleton"]:
                if entry["instance"] is None:
                    entry["instance"] = entry["factory"]()
                return entry["instance"]

            return entry["factory"]()

    def has(self, name: str) -> bool:
        """Return ``True`` if *name* has been registered."""
        with self._lock:
            return name in self._factories

    def reset(self) -> None:
        """Clear all registrations."""
        with self._lock:
            self._factories.clear()
