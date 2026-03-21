from tina4_python.Router import get
from src.models.todo import Todo

@get("/api/todos")
async def list_todos(request, response):
    todos = Todo().select(limit=100).to_array()
    return response(todos, HTTP_OK)
