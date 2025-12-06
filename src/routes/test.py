from tina4_python import get, template, wsdl
from ..app.Calculator import Calculator

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



@wsdl("/calculator")
async def wsdl_cis(request, response):

    return response.wsdl(Calculator(request))