from tina4_python import get, template, wsdl
from ..app.CIS import CIS

@get("/test")
async def test(request):
    pass

@get("/test")
async def test(request):
    pass


@get("/hello/world/{id}")
@template("index.twig")
async def get_twig_something (id, request, response):
    return {"id": id}

# assumes the get and post are the same
@wsdl("/cis")
async def wsdl_cis(request, response):

    return response.wsdl(CIS(request))