from tina4_python.Router import get


@get("/")
async def home(request, response):
    return response.redirect("/tasks")
