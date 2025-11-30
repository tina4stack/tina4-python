
@get("/hello/world/{id}")
@template("index.twig")
async def get_twig_something (id, request, response):
    return {"id": id}