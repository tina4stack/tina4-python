#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Middleware system for intercepting and transforming HTTP requests and responses.

Provides a hook-based middleware pattern with three lifecycle phases:

- **before** hooks: Methods whose names start with ``before`` run before the
  route handler, allowing request validation, authentication, or modification.
- **after** hooks: Methods whose names start with ``after`` run after the route
  handler, enabling response transformation, logging, or cleanup.
- **any** hooks: All other public methods run as general-purpose middleware that
  executes regardless of phase.

Middleware classes are plain Python classes whose public methods accept
``(request, response)`` and return the (possibly modified) ``(request, response)``
tuple.  Both synchronous and ``async`` methods are supported.

Typical usage::

    from tina4_python.Router import get, middleware

    class AuthMiddleware:
        @staticmethod
        def before_auth(request, response):
            # validate token, modify request, etc.
            return request, response

    @middleware(AuthMiddleware)
    @get("/protected")
    async def protected(request, response):
        return response("OK")
"""

__all__ = ["MiddleWare"]

import asyncio


class MiddleWare:
    """Wraps a user-defined middleware class and dispatches its hook methods.

    On instantiation the middleware class is introspected: every public method
    (i.e. not starting with ``__``) is categorised as a *before*, *after*, or
    *any* hook based on its name prefix.  The ``call_*`` helpers then invoke
    the appropriate group of hooks in order, threading the ``(request, response)``
    pair through each one.
    """

    def __init__(self, middleware_class):
        """Introspect *middleware_class* and classify its public methods.

        Args:
            middleware_class: A class (not an instance) whose public methods
                implement middleware hooks.  Method names starting with
                ``before`` are registered as before-hooks, names starting with
                ``after`` as after-hooks, and everything else as any-hooks.
        """
        self.before_methods = []
        self.after_methods = []
        self.any_methods = []
        self.middleware_class = middleware_class

        self.methods_list = [method for method in vars(middleware_class) if callable(
            getattr(middleware_class, method)) and not method.startswith("__")]

        for method in self.methods_list:
            if method.startswith("before") and "after" not in method:
                self.before_methods.append(method)
            elif method.startswith("after") and "before" not in method:
                self.after_methods.append(method)
            else:
                self.any_methods.append(method)

    async def call_before_methods(self, request, response):
        """Invoke all *before* hooks sequentially, threading request/response through each.

        Each before-hook method is called with the current ``(request, response)``
        pair.  Both synchronous and async methods are supported; coroutines are
        awaited automatically.

        Args:
            request: The current HTTP request object.
            response: The current HTTP response object.

        Returns:
            tuple: The ``(request, response)`` pair after all before-hooks
                have been applied.
        """
        for method in self.before_methods:
            method = getattr(self.middleware_class, method)
            result = method(request, response)
            if asyncio.iscoroutine(result):
                request, response = await result
            else:
                request, response = result

        return request, response

    async def call_after_methods(self, request, response):
        """Invoke all *after* hooks sequentially, threading request/response through each.

        Each after-hook method is called with the current ``(request, response)``
        pair.  Both synchronous and async methods are supported; coroutines are
        awaited automatically.

        Args:
            request: The current HTTP request object.
            response: The current HTTP response object.

        Returns:
            tuple: The ``(request, response)`` pair after all after-hooks
                have been applied.
        """
        for method in self.after_methods:
            method = getattr(self.middleware_class, method)
            result = method(request, response)
            if asyncio.iscoroutine(result):
                request, response = await result
            else:
                request, response = result
        return request, response

    async def call_any_methods(self, request, response):
        """Invoke all *any* (general-purpose) hooks sequentially.

        Any-hooks are public methods that do not start with ``before`` or
        ``after``.  They run in declaration order.  Both synchronous and async
        methods are supported; coroutines are awaited automatically.

        Args:
            request: The current HTTP request object.
            response: The current HTTP response object.

        Returns:
            tuple: The ``(request, response)`` pair after all any-hooks
                have been applied.
        """
        for method in self.any_methods:
            method = getattr(self.middleware_class, method)
            result = method(request, response)
            if asyncio.iscoroutine(result):
                request, response = await result
            else:
                request, response = result
        return request, response

    def call_direct_method(self, request, response, method_name):
        """Invoke a single middleware method by name (synchronous only).

        Unlike the ``call_*_methods`` helpers this targets one specific method
        without iterating over a category.  The method is looked up on the
        middleware class via ``getattr`` and called directly.

        Args:
            request: The current HTTP request object.
            response: The current HTTP response object.
            method_name (str): The exact name of the method to call on the
                middleware class.

        Returns:
            tuple: The ``(request, response)`` pair returned by the method.
        """
        method = getattr(self.middleware_class, method_name)
        request, response = method(request, response)
        return request, response
