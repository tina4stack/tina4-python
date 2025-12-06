
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


# 1–2. Basic routes
@get("/hello")
async def hello(request, response):
    return response("Hello, Tina4 Python!")

@post("/submit")
async def submit(request, response):
    data = await request.body()
    return response(f"Received: {data}")

# 3. All methods
@get("/users")
async def list_users(request, response):
    return response({"users": ["Alice", "Bob"]})

@post("/users")
async def create_user(request, response):
    data = await request.body()
    return response({"created": data.get("name")})

@put("/users/{id}")
async def update_user(id: str, request, response):
    data = await request.body()
    return response(f"Updated user {id} with {data}")

@delete("/users/{id}")
async def delete_user(id: str, request, response):
    return response(f"Deleted user {id}")

# 4–5. Path & Query params
@get("/users/{id}/posts/{post_id}")
async def user_post(id: str, post_id: str, request, response):
    return response(f"User {id}'s post {post_id}")

@get("/search")
async def search(request, response):
    q = request.params.get("q", "default")
    page = request.params.get("page", "1")
    return response(f"Searching '{q}' on page {page}")

# 6. Admin prefix
@get("/admin/dashboard")
async def admin_dashboard(request, response):
    return response("Admin Dashboard")

# 7. Middleware
class AuthMiddleware:
    @staticmethod
    def before_route(request, response):
        if request.headers.get("Authorization") != "Bearer valid-jwt-token":
            response.status_code = 401
            return request, "Unauthorized"
        return request, response

    @staticmethod
    def after_route(request, response):
        response.headers["X-Custom"] = "Processed"
        return request, response

@middleware(AuthMiddleware)
@get("/protected")
async def protected_route(request, response):
    return response("Secure data")

# 8. Error handling
@get("/divide/{num}")
async def divide(request, response, num: str):
    try:
        result = 100 / float(num)
        return response(str(result))
    except ValueError:
        response.status_code = 400
        return response("Invalid number")
    except ZeroDivisionError:
        response.status_code = 400
        return response("Cannot divide by zero")

# 9. Async
@get("/async-db")
async def async_db(request, response):
    # Simulate DB call
    await asyncio.sleep(0.01)
    return response([{"id": 1, "name": "John"}])

# 10. Responses
@get("/api/health")
async def health(request, response):
    return response({"status": "ok", "timestamp": "now"})

@get("/old-page")
async def old_page(request, response):
    return response.redirect("/new-page")

@get("/page/about")
async def about_page(request, response):
    return response.render("about.html", {"title": "About Us", "name": "John Doe"})

# 12. Secured
@get("/profile")
@secured()
async def profile(request, response):
    return response({"user": "authenticated"})

# 14. WebSocket
from tina4_python.Websocket import Websocket

@get("/chat")
async def get_websocket(request, response):
    ws = await Websocket(request).connection()
    try:
        while True:
            data = await ws.receive()
            await ws.send(data)
    except Exception as e:
        pass
    return response("")