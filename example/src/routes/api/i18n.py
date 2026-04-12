from tina4_python.core.router import get, noauth


@noauth()
@get("/api/locale/{lang}")
async def switch_locale(lang, request, response):
    request.session.set("locale", lang)
    # Redirect back to the referring page, or home
    referer = request.headers.get("referer", "/")
    return response.redirect(referer)
