from tina4_python.Router import get, post
from ..orm.Log import Log
from ..orm.User import User
from .. import dba


@get("/some/dashboard")
async def some_dashboard(request, response):
    logs = Log().select(column_names="id, name, image", order_by="id DESC")
    users = User().select(column_names="id, first_name, last_name", order_by="id DESC")
    other_users = User().select(column_names="id, first_name, last_name", order_by="id DESC")

    moo = dba.fetch("select * from moo")

    return response.render("dashboard.twig", {"crud_log": logs.to_crud(request, {"card_view": True, "something": "Cris"}),
                                              "crud_users": users.to_crud(request, {"search_columns": ["first_name", "last_name", "email"]}

                                                                          ),
                                              "other_users": other_users.to_crud(request, {"name": "other_users"}
                                                                            ),
                                              "moo": moo
                                              })
