from tina4_python import get
from tina4_python.Template import Template
from tina4_python.Websocket import Websocket
from ..orm.User import User

@get("/some/other/page")
async def get_some_page(request, response):
    user = User()
    user.load('id = 1')
    html = Template.render_twig_template("index.twig", data={"user": user.to_dict()})
    return response(html)

@get("/websocket")
async def get_websocket(request, response):
    ws = await Websocket(request).connection()
    try:
        while True:
            data = await ws.receive()+ " Reply"
            await ws.send(data)
    except Exception as e:
        pass
    return response("")

