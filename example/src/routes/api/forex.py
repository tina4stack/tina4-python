# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.core.router import get, noauth
from tina4_python.swagger import description, tags
from src.app.services.forex_service import get_rates, get_currency_info, convert


@noauth()
@tags("Forex")
@description("Get live exchange rates (cached 1hr)")
@get("/api/forex/rates")
async def api_forex_rates(request, response):
    rates = get_rates("USD")
    currencies = get_currency_info()
    return response({"base": "USD", "rates": rates, "currencies": currencies}, 200)


@noauth()
@tags("Forex")
@description("Convert a price to a target currency")
@get("/api/forex/convert/{price}/{currency}")
async def api_forex_convert(price, currency, request, response):
    try:
        price = float(price)
        currency = currency.upper()
        rates = get_rates("USD")
        rate = rates.get(currency)
        if rate is None:
            return response({"error": f"Unsupported currency: {currency}"}, 400)
        converted = convert(price, rate)
        currencies = get_currency_info()
        symbol = currencies.get(currency, {}).get("symbol", "")
        return response({
            "original": price,
            "currency": currency,
            "rate": rate,
            "converted": converted,
            "formatted": f"{symbol}{converted:,.2f}",
        }, 200)
    except (ValueError, TypeError):
        return response({"error": "Invalid price"}, 400)
