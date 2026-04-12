"""Contact page — demonstrates HtmlElement programmatic HTML builder."""
from tina4_python.core.router import get, post, noauth
from tina4_python.HtmlElement import HTMLElement, add_html_helpers
from src.app.template import render

# Inject helpers: _div, _form, _input, _label, _textarea, _button, _h2, _p, etc.
add_html_helpers(globals())


def _build_contact_form(success=False, error=None):
    """Build the contact form entirely with HtmlElement — no template needed."""
    children = []

    children.append(_h2({"class": "mb-3"}, "Contact Us"))
    children.append(_p({"class": "text-muted mb-4"}, "Have a question? Send us a message."))

    if success:
        children.append(_div({"class": "alert alert-success"}, "Thank you! Your message has been sent."))

    if error:
        children.append(_div({"class": "alert alert-danger"}, error))

    form = _form({"method": "POST", "action": "/contact", "class": "contact-form"},
        _div({"class": "form-group mb-3"},
            _label({"for": "name"}, "Name"),
            _input({"type": "text", "id": "name", "name": "name", "class": "form-control", "required": "required", "placeholder": "John Smith"}),
        ),
        _div({"class": "form-group mb-3"},
            _label({"for": "email"}, "Email"),
            _input({"type": "email", "id": "email", "name": "email", "class": "form-control", "required": "required", "placeholder": "you@example.com"}),
        ),
        _div({"class": "form-group mb-3"},
            _label({"for": "subject"}, "Subject"),
            _input({"type": "text", "id": "subject", "name": "subject", "class": "form-control", "placeholder": "Order enquiry, product question, etc."}),
        ),
        _div({"class": "form-group mb-3"},
            _label({"for": "message"}, "Message"),
            _textarea({"id": "message", "name": "message", "class": "form-control", "rows": "5", "required": "required", "placeholder": "Tell us how we can help..."}),
        ),
        _button({"type": "submit", "class": "btn btn-primary"}, "Send Message"),
    )
    children.append(form)

    return str(_div({"class": "container py-4", "style": "max-width:600px;"}, *children))


@noauth()
@get("/contact")
async def contact_page(request, response):
    html_content = _build_contact_form()
    return response(render("base_wrap.twig", {"inner_html": html_content}, request))


@noauth()
@post("/contact")
async def contact_submit(request, response):
    name = request.body.get("name", "").strip()
    email = request.body.get("email", "").strip()
    message = request.body.get("message", "").strip()

    if not name or not email or not message:
        html_content = _build_contact_form(error="Please fill in all required fields.")
        return response(render("base_wrap.twig", {"inner_html": html_content}, request))

    # In a real app, this would use Messenger to send an email
    html_content = _build_contact_form(success=True)
    return response(render("base_wrap.twig", {"inner_html": html_content}, request))
