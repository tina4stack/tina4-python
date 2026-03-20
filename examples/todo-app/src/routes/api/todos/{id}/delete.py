from tina4_python.Router import delete, noauth
from src.models.todo import Todo

@noauth()
@delete("/api/todos/{id}")
async def delete_todo(request, response):
    todo = Todo()
    if not todo.load("id = ?", [request.params["id"]]):
        return response({"error": "Not found"}, HTTP_NOT_FOUND)
    todo.delete()
    return response({"message": "Deleted"}, HTTP_OK)
