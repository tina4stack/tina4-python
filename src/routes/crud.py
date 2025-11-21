from tina4_python.Router import get, post
from ..orm.Log import Log


@get("/some/dashboard")
async def some_dashboard(request, response):
    logs = Log().select(column_names="*")

    return response.render("dashboard.twig", {"crud_log": logs.to_crud(request)})
