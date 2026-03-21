"""Gallery: Auth — JWT login and protected endpoint."""
from tina4_python.core.router import get, post, noauth, secured
from tina4_python.auth import Auth


@noauth()
@post("/api/gallery/auth/login")
async def gallery_login(request, response):
    body = request.body or {}
    username = body.get("username", "")
    password = body.get("password", "")

    if username and password:
        auth = Auth()
        token = auth.create_token({"username": username, "role": "user"})
        return response({"token": token, "message": f"Welcome {username}!"})
    return response({"error": "Username and password required"}, 401)


@secured()
@get("/api/gallery/auth/profile")
async def gallery_profile(request, response):
    return response({"profile": "Requires Authorization: Bearer <token>"})


@noauth()
@get("/api/gallery/auth/demo")
async def gallery_auth_demo(request, response):
    return response({
        "instructions": "POST /api/gallery/auth/login with {username, password} to get a token",
        "example": {"username": "admin", "password": "secret"},
    })
