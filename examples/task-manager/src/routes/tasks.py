from tina4_python.Router import get, post, noauth, middleware
from src.orm.Task import Task
from src.app.middleware import AuthRequired


@middleware(AuthRequired)
@get("/tasks")
async def list_tasks(request, response):
    user_id = request.session.get("user_id")
    tasks = Task().select("*", filter="user_id = ?", params=[user_id], order_by="created_at desc", limit=50)
    return response.render("pages/tasks.twig", {
        "tasks": tasks.to_array(),
        "username": request.session.get("username"),
    })


@middleware(AuthRequired)
@noauth()
@post("/tasks")
async def create_task(request, response):
    user_id = request.session.get("user_id")
    task = Task({
        "user_id": user_id,
        "title": request.body.get("title", ""),
        "description": request.body.get("description", ""),
        "status": "pending",
        "due_date": request.body.get("due_date", None),
    })
    task.save()
    return response.redirect("/tasks")


@middleware(AuthRequired)
@noauth()
@post("/tasks/{id:int}/complete")
async def complete_task(id, request, response):
    task = Task()
    if task.load("id = ?", [id]):
        task.status = "completed"
        task.save()
    return response.redirect("/tasks")


@middleware(AuthRequired)
@noauth()
@post("/tasks/{id:int}/delete")
async def delete_task(id, request, response):
    task = Task()
    if task.load("id = ?", [id]):
        task.delete()
    return response.redirect("/tasks")
