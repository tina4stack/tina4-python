from tina4_python import get, post, noauth
from tina4_python.Response import Response


@get("/session-form")
async def get_session_form(request, response):
    return response.render("session_form.twig")


@noauth()
@post("/session-form")
async def post_session_form(request, response):
    # Save posted form data into the session
    body = request.body or {}

    request.session.set("name", body.get("name", ""))
    request.session.set("email", body.get("email", ""))
    request.session.set("message", body.get("message", ""))

    # Redirect to the session display page
    return Response.redirect("/session-info")


@get("/session-info")
async def get_session_info(request, response):
    name = request.session.get("name")
    email = request.session.get("email")
    message = request.session.get("message")

    return response.render("session_info.twig", {
        "name": name,
        "email": email,
        "message": message,
    })
