from tina4_python.Router import get, post
from ..orm.Log import Log
from ..orm.User import User


@get("/some/dashboard")
async def some_dashboard(request, response):
    logs = Log().select(column_names="*")
    users = User().select(column_names="id, title, first_name, last_name, email")

    return response.render("dashboard.twig", {"crud_log": logs.to_crud(request, {"card_view": True}), "crud_users": users.to_crud(request, {"card_view": False}) })
