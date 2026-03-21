from tina4_python.Router import get
from src.models.todo import Todo

@get("/api/todos/{id}")
async def get_todo(request, response):
    todo = Todo()
    if todo.load("id = ?", [request.params["id"]]):
        return response(todo.to_dict(), HTTP_OK)
    return response({"error": "Not found"}, HTTP_NOT_FOUND)
