"""Forex service — fetches live exchange rates using tina4 Api client.

Demonstrates: Api (external HTTP client), caching, inline @tests.
Uses the free frankfurter.app API (no key required).
"""
import time
from tina4_python.api import Api
from tina4_python.Testing import tests, expect_true, expect_equal

# Supported currencies for the store
CURRENCIES = {
    "USD": {"symbol": "$", "name": "US Dollar"},
    "EUR": {"symbol": "€", "name": "Euro"},
    "GBP": {"symbol": "£", "name": "British Pound"},
    "ZAR": {"symbol": "R", "name": "South African Rand"},
    "JPY": {"symbol": "¥", "name": "Japanese Yen"},
}

# In-memory cache: { "rates": {...}, "fetched_at": timestamp }
_cache = {"rates": None, "fetched_at": 0}
CACHE_TTL = 3600  # 1 hour


def get_rates(base="USD"):
    """Fetch exchange rates from frankfurter.app, cached for 1 hour.

    Returns dict like {"EUR": 0.92, "GBP": 0.79, "ZAR": 18.12, "JPY": 149.5}
    """
    now = time.time()
    if _cache["rates"] and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["rates"]

    try:
        api = Api(base_url="https://api.frankfurter.app", timeout=5)
        targets = ",".join(c for c in CURRENCIES if c != base)
        result = api.get(f"/latest?from={base}&to={targets}")

        if result.get("http_code") == 200 and result.get("body"):
            body = result["body"]
            if isinstance(body, str):
                import json
                body = json.loads(body)
            rates = body.get("rates", {})
            # Include base currency at 1.0
            rates[base] = 1.0
            _cache["rates"] = rates
            _cache["fetched_at"] = now
            return rates
    except Exception:
        pass

    # Fallback rates if API is unreachable
    return _fallback_rates(base)


def _fallback_rates(base="USD"):
    """Hardcoded fallback so the store never breaks."""
    fallback = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79, "ZAR": 18.12, "JPY": 149.5}
    return fallback


@tests(
    expect_equal((10.0, 0.92), 9.2),
    expect_equal((100.0, 18.12), 1812.0),
    expect_equal((0.0, 5.0), 0.0),
    expect_true((49.99, 1.0)),  # same currency returns truthy (non-zero)
)
def convert(price, rate):
    """Convert a USD price to another currency."""
    return round(price * rate, 2)


def get_currency_info():
    """Return the CURRENCIES dict for templates."""
    return CURRENCIES
