"""Gallery: Auth — JWT login and protected endpoint."""
from tina4_python.Router import get, post, noauth, secured
from tina4_python.Auth import get_token, valid_token, get_payload


@noauth()
@post("/api/gallery/auth/login")
async def gallery_login(request, response):
    body = request.body or {}
    username = body.get("username", "")
    password = body.get("password", "")

    # Demo: accept any non-empty credentials
    if username and password:
        token = get_token({"username": username, "role": "user"})
        return response({"token": token, "message": f"Welcome {username}!"})
    return response({"error": "Username and password required"}, 401)


@secured()
@get("/api/gallery/auth/profile")
async def gallery_profile(request, response):
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "")
    payload = get_payload(token)
    return response({"profile": payload})


@noauth()
@get("/api/gallery/auth/verify")
async def gallery_verify(request, response):
    token = request.params.get("token", "")
    is_valid = valid_token(token)
    return response({"valid": is_valid})
