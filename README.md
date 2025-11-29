# Tina4 Python — This is not a framework

Laravel joy. Python speed. 10× less code.

```python app.py
from tina4_python import run_web_server
from tina4_python.Router import get


@get("/")
async def get_hello_world(request, response):
    return response("Hello World!")


def app():
    run_web_server()


if __name__ == "__main__":
    app()
```

That’s it. Save the code above as `app.py`, run it, and you have a fully working Tina4 Python web server.

```bash
pip install tina4-python
python app.py
# → http://localhost:7145
```

You just built your first Tina4 app — zero configuration, zero classes, zero boilerplate.

## Features

- Full ASGI compliance, use any ASGI compliant webserver
- Full async support out of the box
- Built in JWT and Session handling
- Automatic Swagger docs at `/swagger`
- Instant CRUD interfaces with one line: `result.to_crud(request)`
- Built-in Twig templating, migrations, WebSockets, authentication and middleware
- Works with SQLite, PostgreSQL, MySQL, MariaDB, MSSQL, Firebird
- Hot reload in development (`uv run python -m jurigged app.py`)

## Install

```bash
pip install tina4-python
```

## Documentation

https://tina4.com/

## Community

- GitHub: https://github.com/tina4stack/tina4-python

## License

MIT © 2007 – 2025 Tina4 Stack  
https://opensource.org/licenses/MIT

---

**Tina4** – The framework that keeps out of the way of your coding.
