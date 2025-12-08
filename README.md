# Tina4 Python — This is not a framework

Laravel joy. Python speed. 10× less code.

## Quickstart
```bash
pip install tina4_python
tina4 init my_project
cd my_project
python app.py
```

You've just built your first Tina4 app — zero configuration, zero classes, zero boilerplate!

## Features

- Full ASGI compliance, use any ASGI compliant webserver
- Full async support out of the box
- Built-in JWT and Session handling
- Automatic Swagger docs at `/swagger`
- Instant CRUD interfaces with one line: `result.to_crud(request)`
- Built-in Twig templating, migrations, WebSockets, authentication and middleware
- Works with SQLite, PostgreSQL, MySQL, MariaDB, MSSQL, Firebird
- Hot reload in development (`uv run python -m jurigged app.py`)

## Install

```bash
pip install tina4-python
```

## Routing

Here are some basic GET routes

```python
# .src/__init__.py
from tina4_python import get

# simple get route
@get("/hello")
async def get_hello(request, response):
    return response("Hello, Tina4 Python!")

# simple get route with inline params
@get("/hello/{world}")
async def get_hello_world(world, request, response):
    return response(f"Hello, {world} ")

# simple route responding with json
@get("/hello/json")
async def get_hello_json(world, request, response):
    cars = [{"brand": "BMW"}, {"brand": "Toyota"}]

    return response(cars)

# respond with a file
@get("/hello/{filename}")
async def get_hello_file(filename, request, response):
   
    return response.file(filename, './src/public')

# respond with a redirection to another location
@get("/hello/redirect")
async def get_hello_redirect(request, response):
    
    return response.redirect("/hello/world")

@get("/hello/template")
async def get_hello_template(request, response):
    
    # renders any template in .src/templates
    return response.render("index.twig", {"data": request.params})

```

## Further Documentation

https://tina4.com/

## Community

- GitHub: https://github.com/tina4stack/tina4-python

## License

MIT © 2007 – 2025 Tina4 Stack  
https://opensource.org/licenses/MIT

---

**Tina4** – The framework that keeps out of the way of your coding.
