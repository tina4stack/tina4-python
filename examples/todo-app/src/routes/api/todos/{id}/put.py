from tina4_python.Router import put, noauth
from src.models.todo import Todo

@noauth()
@put("/api/todos/{id}")
async def update_todo(request, response):
    todo = Todo()
    if not todo.load("id = ?", [request.params["id"]]):
        return response({"error": "Not found"}, HTTP_NOT_FOUND)
    todo = Todo(request.body)
    todo.id = int(request.params["id"])
    todo.save()
    return response(todo.to_dict(), HTTP_OK)
