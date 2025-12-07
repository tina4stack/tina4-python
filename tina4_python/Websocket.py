#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import importlib
import os
from asyncio.trsock import TransportSocket

from tina4_python.Debug import Debug

class Websocket:
    """
    Websocket class which wraps simple_websocket library
    """
    def __init__(self, request):
        try:
            self.server = importlib.import_module("simple_websocket")
            self.request = request
        except Exception as e:
            Debug.error("Error creating Websocket, perhaps you need to install simple_websocket ?", e)

    async def connection(self):
        """
        Returns a websocket connection
        :return:
        """
        try:
            if self.request.asgi_response:
                connection = await self.server.AioServer.accept(asgi=(self.request.asgi_scope, self.request.asgi_reader, self.request.asgi_writer))
            else:
                if os.name == "nt":
                    connection = await self.server.AioServer.accept(
                        sock=TransportSocket(self.request.transport.transport._sock), # not working properly
                        headers=self.request.headers
                    )
                else:
                    connection = await self.server.AioServer.accept(
                        sock=self.request.transport.get_extra_info('socket').dup(),
                        headers=self.request.headers
                    )
            return connection

        except Exception as e:
            Debug.error("Could not establish a socket connection:", str(e))
            return None
