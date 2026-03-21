"""User API endpoints."""
from tina4_python.Router import get, post, noauth
from src.orm.user import User


@get("/api/users")
async def list_users(request, response):
    """Return all users."""
    try:
        result = User().select(limit=100)
        return response(result.to_array())
    except Exception:
        return response([], 200)


@get("/api/users/{id}")
async def get_user(id, request, response):
    """Return a single user by id."""
    user = User()
    if user.load("id = ?", [id]):
        return response(user.to_dict())
    return response({"error": "User not found"}, 404)


@noauth()
@post("/api/users")
async def create_user(request, response):
    """Create a new user."""
    user = User(request.body)
    user.save()
    return response(user.to_dict(), 201)
