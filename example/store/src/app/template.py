"""Shared Frond template engine instance with session-aware rendering."""
from tina4_python.frond import Frond
from tina4_python.i18n import I18n
import os

# Single shared instance — all routes import this
frond = Frond()

# I18n instance for locale switching
i18n = I18n(
    locale_dir=os.environ.get("TINA4_LOCALE_DIR", "src/locales"),
    default_locale=os.environ.get("TINA4_LOCALE", "en"),
)


def render(template_name, data=None, request=None):
    """Render a template with session globals automatically injected.

    Usage in routes:
        from src.app.template import render
        return response(render("storefront/cart.twig", {"items": items}, request))
    """
    context = {}
    if request and hasattr(request, "session"):
        context["customer_name"] = request.session.get("customer_name")
        context["customer_id"] = request.session.get("customer_id")
        context["role"] = request.session.get("role")

        # Switch locale per session
        locale = request.session.get("locale")
        if locale:
            i18n.locale = locale

    # Override t() with our session-aware i18n instance
    context["t"] = i18n.t

    if data:
        context.update(data)
    return frond.render(template_name, context)
