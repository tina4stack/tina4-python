"""Shared Frond template engine instance with session-aware rendering."""
from tina4_python.frond import Frond
from tina4_python.i18n import I18n
from src.app.services.forex_service import get_rates, get_currency_info, convert
import os

# Single shared instance — all routes import this
frond = Frond()

# ── Currency filter: {{ 49.99|currency }} → "$49.99 / €45.99 / R905.38"
_DISPLAY_CURRENCIES = ["USD", "EUR", "GBP", "ZAR"]


def _currency_filter(price):
    """Format a USD price with conversions to selected currencies."""
    try:
        price = float(price or 0)
    except (ValueError, TypeError):
        return str(price)
    rates = get_rates("USD")
    info = get_currency_info()
    parts = []
    for code in _DISPLAY_CURRENCIES:
        rate = rates.get(code, 1)
        sym = info.get(code, {}).get("symbol", "")
        converted = convert(price, rate)
        if code == "JPY":
            parts.append(f"{sym}{converted:,.0f}")
        else:
            parts.append(f"{sym}{converted:,.2f}")
    return " / ".join(parts)


frond.add_filter("currency", _currency_filter)

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

        # Cart count + total for nav badge
        from src.app.services.cart_service import cart_count, get_cart_total
        context["cart_count"] = cart_count(request.session)
        context["cart_total"] = get_cart_total(request.session)

        # Switch locale per session
        locale = request.session.get("locale")
        if locale:
            i18n.locale = locale

    # Pass current locale to templates for the language toggle
    context["locale"] = i18n.locale

    # Override t() with our session-aware i18n instance
    context["t"] = i18n.t

    if data:
        context.update(data)
    return frond.render(template_name, context)
