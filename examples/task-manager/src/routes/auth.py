import tina4_python
from tina4_python.Router import get, post, noauth
from src.orm.User import User


@get("/login")
async def login_page(request, response):
    return response.render("pages/login.twig", {"error": None})


@get("/register")
async def register_page(request, response):
    return response.render("pages/register.twig", {"error": None})


@noauth()
@post("/login")
async def do_login(request, response):
    username = request.body.get("username", "")
    password = request.body.get("password", "")

    user = User()
    if not user.load("username = ?", [username]):
        return response.render("pages/login.twig", {"error": "Invalid username or password"})

    if not tina4_python.tina4_auth.check_password(password, user.password_hash):
        return response.render("pages/login.twig", {"error": "Invalid username or password"})

    request.session.set("user_id", user.id)
    request.session.set("username", user.username)
    request.session.save()
    return response.redirect("/tasks")


@noauth()
@post("/register")
async def do_register(request, response):
    username = request.body.get("username", "")
    email = request.body.get("email", "")
    password = request.body.get("password", "")

    if not username or not email or not password:
        return response.render("pages/register.twig", {"error": "All fields are required"})

    # Check if username exists
    existing = User()
    if existing.load("username = ?", [username]):
        return response.render("pages/register.twig", {"error": "Username already taken"})

    user = User({
        "username": username,
        "email": email,
        "password_hash": tina4_python.tina4_auth.hash_password(password),
    })
    user.save()
    return response.redirect("/login")


@get("/logout")
async def logout(request, response):
    request.session.close()
    return response.redirect("/login")
