# Tina4 Python Example

A minimal example application demonstrating routing, ORM, templates, and JSON APIs.

## Setup

```bash
cd example
pip install -e ..
```

## Run

```bash
python app.py
```

Then visit http://localhost:7145

## Endpoints

- `GET /` — Welcome page (Twig template)
- `GET /api/hello` — JSON greeting
- `GET /api/users` — List users
- `GET /api/users/{id}` — Get user by id
- `POST /api/users` — Create user (JSON body: `{"name": "...", "email": "..."}`)

## Documentation

See https://tina4.com for full framework documentation.
