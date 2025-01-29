from tina4_python import get
from tina4_python.Template import Template
from ..orm.User import User
from simple_websocket import AioServer, ConnectionClosed

@get("/some/other/page")
async def get_some_page(request, response):
    user = User()
    user.load('id = 1')
    html = Template.render_twig_template("index.twig", data={"user": user.to_dict()})
    return response(html)


@get("/websocket")
async def get_websocket(request, response):
    ws = await AioServer.accept(aiohttp=request)
    try:
        while True:
            data = await ws.receive()
            data = "Hello World! "+data
            await ws.send(data)
    except ConnectionClosed:
        pass
    return response("")

@get("/websocket2")
async def get_websocket2(request, response):
    ws = await AioServer.accept(asgi=request.transport)
    try:
        while True:
            data = await ws.receive()
            await ws.send(data)
    except ConnectionClosed:
        pass