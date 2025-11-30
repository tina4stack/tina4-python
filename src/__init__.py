
dba = Database("sqlite3:data.db")


@get("/inline/{id}")
async def get_inline_id (id, request, response):

    return response({"id": id, "params": request.params["id"]})