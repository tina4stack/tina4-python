from tina4_python.core.router import get, middleware
from src.app.template import render
from src.middleware.admin_auth import AdminAuth


@middleware(AdminAuth)
@get("/admin/helpdesk")
async def admin_helpdesk(request, response):
    return response(render("admin/helpdesk.twig", {}, request))
