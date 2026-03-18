import tina4_python
from tina4_python.Router import post, noauth
from tina4_python.Swagger import description, tags, example


@noauth()
@description("Get a JWT bearer token (demo: admin/admin)")
@tags(["auth"])
@example({"username": "admin", "password": "admin"})
@post("/api/auth/token")
async def get_token(request, response):
    username = request.body.get("username", "")
    password = request.body.get("password", "")

    # Demo credentials — in production, check against the database
    if username == "admin" and password == "admin":
        token = tina4_python.tina4_auth.get_token(
            {"user": username, "role": "admin"},
            expiry_minutes=60,
        )
        return response({"token": token})

    return response({"error": "Invalid credentials"}, 401)
