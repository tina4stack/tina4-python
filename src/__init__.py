import asyncio
from tina4_python.Migration import migrate
from tina4_python import get, post, put, delete, middleware, description, Database, secured, HTTP_OK, noauth, Debug, orm




dba = Database("sqlite3:data.db")

migrate(dba)
orm(dba)

# from .orm.User import User
# user = User({"id": 1, "username": "john", "email": "john@doe.com"})
# user.id = 1
# user.username = "moo"
# user.email = "test"
#
# if not dba.table_exists("user"):
#     Debug.info (user.create_table())
#     dba.execute(user.create_table())
#
# user.save()


@get("/users/landing")
async def get_users_landing(request, response):
    from .orm.User import User

    crud_users = User().select("*").to_crud(request, {"card_view": True})

    return response.render("{{crud_users}}", {"crud_users": crud_users})



@get("/system/employees")
async def get_employees(request, response):

    employees = dba.fetch("select * from employee order by last_name")

    return response.render(  "index.twig", {"employees": employees.to_crud(request, {"card_view": True})})

@post("/swagger/new-post-noauth")
@description("Noauth Post")
@noauth()
async def new_post_noauth(response):

    return response("NOAUTH Post")

@post("/swagger/new-post-secure")
@description("Secure Post")
@secured()
async def new_post_secure(response):

    return response("SECURED Post")

@get("/system/organizations")
async def get_organisations(request, response):
    d = d /0
    return response(request.params)


@get("/swagger/new-get-secure")
@description("Secure Get")
@secured()
async def new_post_get(response):

    return response("SECURED Get")


@get("/inline/{id}")
async def get_inline_id(id, request, response):
    return response({"id": id, "params": request.params["id"]})


@get("/users/{id}/posts/{post_id}")
async def user_post(id: str, post_id: str, response):  # Path params before request/response
    return response(f"User {id}'s post {post_id}")


@get("/uploads/{file}")
async def serve_upload(file: str, response):
    print("Ok")
    return response.file(file, "")


# 1–2. Basic routes
@get("/hello")
async def hello(response):
    return response("Hello, Tina4 Python!")


@post("/submit")
async def submit(request, response):
    data = request.body
    return response(data)


# 3. All methods
@get("/users")
async def list_users(request, response):
    return response({"users": ["Alice", "Bob"]})


@get("/api/users")
@description("Users")
async def list_users(request, response):
    return response({"users": ["Alice", "Bob"]})


@post("/users")
@description("Create a new user")
async def create_user(request, response):
    data = request.body
    return response({"created": data.get("name")})


@put("/users/{id}")
async def update_user(id: str, request, response):
    data = request.body
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
        if request.headers.get("authorization") != "Bearer 38168ba8aad6c91ba13d959c3f91c7a7":
            response.http_code = 401
            response.content = "Unauthorized"
            return request, response
        return request, response

    @staticmethod
    def after_route(request, response):
        response.add_header("X-Custom", "Processed")
        return request, response


@middleware(AuthMiddleware)
@get("/protected")
async def protected_route(request, response):
    print("Protected")
    return response("Secure data", HTTP_OK)


# 8. Error handling
@get("/divide/{num}")
async def divide(num: str, request, response):
    try:
        result = 100 / float(num)
        return response(str(result))
    except ValueError:

        return response("Invalid number", 400)
    except ZeroDivisionError:

        return response("Cannot divide by zero", 400)


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


@get("/new-page")
async def new_page(request, response):
    return response("New Page")


@get("/page/about")
async def about_page(request, response):
    return response.render("index.twig", {"title": "About Us", "name": "John Doe"})


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
            await ws.send("Echo: " + data)
    except Exception as e:
        pass
    return response("")

