#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""WebSocket support for the Tina4 Python web framework.

This module provides a thin wrapper around the ``simple_websocket`` library,
allowing Tina4 route handlers to upgrade HTTP connections to full-duplex
WebSocket connections.  It supports both ASGI-native transports and raw
socket transports (with a platform-specific path for Windows).

Typical usage inside a Tina4 route handler::

    from tina4_python.Websocket import Websocket

    @get("/ws")
    async def websocket_handler(request, response):
        ws = Websocket(request)
        conn = await ws.connection()
        if conn is None:
            return response("WebSocket upgrade failed", 400)
        while True:
            data = conn.receive()
            conn.send(f"echo: {data}")
"""

__all__ = ["Websocket"]

import importlib
import os
from asyncio.trsock import TransportSocket

from tina4_python.Debug import Debug


class Websocket:
    """Wrapper around ``simple_websocket`` for Tina4 WebSocket connections.

    This class lazily imports the ``simple_websocket`` package at
    instantiation time so the dependency remains optional.  Call
    :meth:`connection` to perform the WebSocket handshake and obtain an
    active connection object that supports ``send()`` and ``receive()``.
    """

    def __init__(self, request):
        """Initialise the WebSocket wrapper.

        Args:
            request: A Tina4 ``Request`` object (or the raw request dict)
                that carries the incoming HTTP connection details.  Must
                expose ``asgi_response``, ``asgi_scope``, ``asgi_reader``,
                ``asgi_writer``, and ``headers`` attributes so the
                WebSocket handshake can be performed.

        Raises:
            Logs an error via ``Debug.error`` if the ``simple_websocket``
            package is not installed.
        """
        try:
            self.server = importlib.import_module("simple_websocket")
            self.request = request
        except Exception as e:
            from tina4_python import Messages
            Debug.error(Messages.MSG_WS_CREATE_ERROR, e)

    async def connection(self):
        """Perform the WebSocket handshake and return an active connection.

        The method inspects the request to decide which accept strategy to
        use:

        * **ASGI mode** -- delegates to ``simple_websocket.AioServer.accept``
          with the ASGI scope, reader and writer.
        * **Raw-socket mode (Unix)** -- duplicates the underlying socket via
          ``get_extra_info('socket').dup()``.
        * **Raw-socket mode (Windows)** -- wraps the transport socket with
          ``asyncio.trsock.TransportSocket``.

        Returns:
            A ``simple_websocket.AioServer`` connection instance on success,
            or ``None`` if the handshake failed.
        """
        try:
            if self.request.asgi_response:
                connection = await self.server.AioServer.accept(asgi=(self.request.asgi_scope, self.request.asgi_reader, self.request.asgi_writer))
            else:
                if os.name == "nt":
                    connection = await self.server.AioServer.accept(
                        sock=TransportSocket(self.request.asgi_writer.transport._sock), # not working properly
                        headers=self.request.headers
                    )
                else:
                    connection = await self.server.AioServer.accept(
                        sock=self.request.asgi_writer.get_extra_info('socket').dup(),
                        headers=self.request.headers
                    )
            return connection

        except Exception as e:
            from tina4_python import Messages
            Debug.error(Messages.MSG_WS_CONNECTION_ERROR.format(error=str(e)))
            return None
