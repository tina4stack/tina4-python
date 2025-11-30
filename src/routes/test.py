@get("/hello/{id}")
async def get_hello_id (id, request, response):

    return response({"id": id, "params": request.params["id"]})