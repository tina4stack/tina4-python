#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import importlib
import os
from tina4_python.Debug import Debug

class Websocket:
    """
    Websocket class which wraps simple_websocket library
    """
    def __init__(self, request):
        try:
            self.server = importlib.import_module("simple_websocket")
            self.request = request
            self.connection = None
        except Exception as e:
            Debug.error("Error creating Websocket, perhaps you need to install simple_websocket ?", e)

    async def connection(self):
        """
        Returns a websocket connection
        :return:
        """
        if self.request.asgi_response:
            self.connection = await self.server.AioServer.accept(asgi=self.request.transport)
        else:
            if os.name == "nt":
                self.connection = await self.server.AioServer.accept(sock=self.request.transport.transport._sock, headers=self.request.headers)
            else:
                self.connection = await self.server.AioServer.accept(aiohttp=self.request)

        return self.connection
