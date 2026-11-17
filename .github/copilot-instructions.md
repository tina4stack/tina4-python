# tina4-python Copilot Instructions

Tina4 Python v3. 140 cataloged features, zero dependencies.

## Route Pattern

```python
from tina4_python.core.router import get, post, noauth

@get("/api/users")
async def list_users(request, response):
    return response({"users": []})

@noauth()
@post("/api/users")
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

For the complete API reference, read `CLAUDE.md` in this repo and the docs it links. `llms.txt` is the link index (llmstxt.org format); https://tina4.com/llms-full.txt has the full documentation in one file.
