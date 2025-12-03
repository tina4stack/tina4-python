
dba = Database("sqlite3:data.db")


@get("/inline/{id}")
async def get_inline_id (id, request, response):

    return response({"id": id, "params": request.params["id"]})


@get("/users/{id}/posts/{post_id}")
async def user_post(id: str, post_id: str, request, response):  # Path params before request/response
    return response(f"User {id}'s post {post_id}")

@get("/search")
async def search(request, response):
    query = request.params.get("q", "default")
    page = int(request.params.get("page", 1))
    return response(request.raw_content)

@get("/uploads/{file}")
async def serve_upload(file: str, request, response):
    print("Ok")
    return response.file(file, "")