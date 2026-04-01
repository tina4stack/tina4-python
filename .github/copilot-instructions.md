# tina4-python Copilot Instructions

Tina4 Python v3. 54 features, zero dependencies.

## Route Pattern

```python
from tina4_python.core.router import get, post, noauth

@get("/api/users")
async def list_users(request, response):
    return response({"users": []})

@post("/api/users")
@noauth()
async def create(request, response):
    return response({"created": request.body["name"]}, 201)
```

## Critical Rules

- Return `response()` NOT `response.json()`
- POST/PUT/DELETE require auth — `@noauth()` makes public
- GET is public — `@secured()` protects
- Import from `tina4_python.core.router` not `tina4_python.router`
- Queue: `job.payload` not `job.data`
- Database: `offset=` not `skip=`
- Decorator order: `@noauth` outermost, `@get`/`@post` innermost

See llms.txt for full API reference.
