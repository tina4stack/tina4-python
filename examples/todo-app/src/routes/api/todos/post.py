from tina4_python.Router import post, noauth
from src.models.todo import Todo

@noauth()
@post("/api/todos")
async def create_todo(request, response):
    todo = Todo(request.body)
    todo.save()
    return response(todo.to_dict(), HTTP_CREATED)
