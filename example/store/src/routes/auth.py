from tina4_python.core.router import get, post, noauth
from tina4_python.auth import Auth, get_token
from tina4_python.core.events import emit
from src.orm.customer import Customer
from src.app.template import render


@get("/login")
async def login_page(request, response):
    return response(render("storefront/login.twig", {
        "error": request.session.get_flash("error"),
    }, request))


@noauth()
@post("/login")
async def login(request, response):
    email = request.body.get("email", "")
    password = request.body.get("password", "")

    customers = Customer.where("email = ?", params=[email])
    customer = customers[0] if customers else None

    if customer and not Auth.check_password(password, customer.password_hash):
        customer = None

    if not customer:
        request.session.flash("error", "Invalid email or password")
        return response.redirect("/login")

    role = customer.role or "customer"
    token = get_token({"customer_id": customer.id, "role": role})
    request.session.set("token", token)
    request.session.set("customer_id", customer.id)
    request.session.set("customer_name", customer.name)
    request.session.set("role", role)

    if role == "admin":
        return response.redirect("/admin")
    return response.redirect("/account")


@get("/register")
async def register_page(request, response):
    return response(render("storefront/register.twig", {
        "error": request.session.get_flash("error"),
    }, request))


@noauth()
@post("/register")
async def register(request, response):
    name = request.body.get("name", "")
    email = request.body.get("email", "")
    password = request.body.get("password", "")

    existing = Customer.where("email = ?", params=[email])
    if existing:
        request.session.flash("error", "Email already registered")
        return response.redirect("/login")

    customer = Customer.create(
        name=name,
        email=email,
        password_hash=Auth.hash_password(password),
        role="customer",
    )

    emit("customer.registered", {"customer_id": customer.id, "name": name, "email": email})

    token = get_token({"customer_id": customer.id, "role": "customer"})
    request.session.set("token", token)
    request.session.set("customer_id", customer.id)
    request.session.set("customer_name", name)
    request.session.set("role", "customer")
    return response.redirect("/account")


@get("/logout")
async def logout(request, response):
    request.session.set("token", None)
    request.session.set("customer_id", None)
    request.session.set("customer_name", None)
    request.session.set("role", None)
    return response.redirect("/")
