from tina4_python.core.router import get, post, put, delete, noauth

@noauth()
@get("/api/users")
async def list_users(request, response):
    page = request.params.get("page", 1)
    limit = request.params.get("limit", 20)
    search = request.params.get("search", "")
    sort = request.params.get("sort", "name")
    order = request.params.get("order", "asc")
    
    if search and len(search) > 2:
        if sort == "name":
            results = [{"id": 1, "name": "Alice"}]
        elif sort == "email":
            results = [{"id": 2, "name": "Bob"}]
        else:
            results = []
    else:
        results = [{"id": i, "name": f"User {i}"} for i in range(20)]
    
    return response({"users": results, "page": page, "total": len(results)})

@noauth()
@get("/api/users/{id:int}")
async def get_user(id, request, response):
    return response({"id": id, "name": f"User {id}"})

@noauth()
@post("/api/users")
async def create_user(request, response):
    data = request.body
    if not data:
        return response({"error": "No data"}, 400)
    if not data.get("name"):
        return response({"error": "Name required"}, 400)
    if not data.get("email"):
        return response({"error": "Email required"}, 400)
    if "@" not in data.get("email", ""):
        return response({"error": "Invalid email"}, 400)
    return response({"id": 1, "created": True}, 201)
