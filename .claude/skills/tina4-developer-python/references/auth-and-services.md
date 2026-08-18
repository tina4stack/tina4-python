# Authentication & Services (Python)

## OpenID Connect SSO

Configure SSO in `.env`. The issuer drives discovery; do not build provider-specific adapters.

```ini
TINA4_SSO_ISSUER=https://identity.example.com/realms/my-app
TINA4_SSO_CLIENT_ID=my-app
TINA4_SSO_CLIENT_SECRET=replace-me
TINA4_SSO_REDIRECT_URI=https://app.example.com/auth/callback
TINA4_SSO_SCOPES=["openid", "profile", "email"]
TINA4_SSO_VERIFY=introspection
```

When configured, Tina4 mounts `GET /auth/login`, `GET /auth/callback`, and
`POST /auth/logout`. A route collision stops startup. Existing secured routes receive the
normalized identity through `request.user`; provider tokens stay inside reserved Session data.

```python
from tina4_python import Sso

sso = Sso.from_issuer()
identity = sso.identity(request.session)
```

Use a provider recipe only to find its standards-based issuer and client settings. The runtime API
stays provider-neutral. As of 3.13.105, introspection is the supported verification mode; `jwks` fails
during configuration until the application supplies a cryptography capability.

## JWT Authentication

### Setup
Set your secret in `.env`:
```env
TINA4_SECRET=a-long-random-string-here
```

### Generating Tokens
```python
from tina4_python import post
from tina4_python.auth import Auth, get_token

@post("/login")
@noauth()                                  # login is public — the caller has no token yet
async def login(request, response):
    email = request.body["email"]
    password = request.body["password"]

    matches = User.where("email = ?", [email])       # SQL WHERE fragment → list
    user = matches[0] if matches else None
    if not user or not Auth.check_password(password, user.password_hash):
        return response.json({"error": "Invalid credentials"}, 401)

    token = get_token({"user_id": user.id, "email": user.email})   # signed with TINA4_SECRET
    return response.json({"token": token})
```

> Fetch a user by a column with `where("email = ?", [email])[0]` or `find({"email": email})[0]`
> — **not** `select_one("email = ?", ...)`, which needs a full `SELECT ...` statement, and not
> `find("email = ?")`, which treats the string as a primary key.

### Protecting Routes

Write a middleware class with a `before_*` hook. **The `before_` prefix is required** — a method
named exactly `before` is never dispatched (a silent auth bypass):

```python
from tina4_python import middleware, get
from tina4_python.auth import Auth

class AuthRequired:
    @staticmethod
    async def before_auth(request, response):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not Auth.valid_token(token):
            return request, response.json({"error": "Unauthorized"}, 401)
        request.user = Auth.get_payload(token)
        return request, response

@middleware(AuthRequired)
@get("/me")
async def get_profile(request, response):
    user = User.find(request.user["user_id"])   # int PK → single instance
    return response(user)
```

### Password Hashing
```python
hashed = Auth.hash_password("mypassword")
matches = Auth.check_password("mypassword", hashed)  # True
```

## Auth footguns

Tina4's default is **secure**: `POST`/`PUT`/`PATCH`/`DELETE` require a Bearer token;
`GET`/`HEAD`/`OPTIONS` are public (`core/router.py:335`). `@noauth()` opens a write
route; `@secured()` locks a read route. Verified against source — get these wrong and
you either ship an unauthenticated write or fight phantom 401s.

### An unexpected 401 means "authenticate the request", not "open the route"

**`@noauth()` is a LAST RESORT.** When a write route returns 401 in dev or from a
client, the fix is almost always to **send the Bearer token** the route legitimately
requires — not to strip its auth. Reserve `@noauth()` for endpoints that are
*genuinely* public: login, register, health-check, inbound webhooks.

```python
from tina4_python.core.router import post, noauth   # or: from tina4_python import post, noauth

@noauth()                         # login is public — the caller has no token YET
@post("/login")
async def login(request, response):
    ...
```

* **Never blanket `@noauth()` to silence 401s.** Slapping it on every write route that
  returns 401 doesn't "fix auth" — it **ships unauthenticated writes**. A 401 on
  `POST /orders` means the request arrived without a valid token; authenticate it
  (`Authorization: Bearer <token>`), don't open the route.

### Import the auth decorators from `core.router` — swagger decorators don't gate anything

`noauth` / `secured` come from **`tina4_python.core.router`** (also re-exported at the
top level: `from tina4_python import noauth, secured`). There is **no**
`tina4_python.Decorators` module.

The **swagger** module (`tina4_python.swagger`) exports **documentation-only**
decorators — `@description`, `@tags`, `@example`, `@security(...)`, … They annotate the
OpenAPI spec and **never change enforcement**. In particular, **`@security("bearerAuth")`
documents that a route needs a token but does NOT enforce it** (`swagger/__init__.py:191`
sets `_swagger_security` metadata only). The real gate is the method default plus
`@noauth()` / `@secured()`.

```python
from tina4_python.swagger import security
from tina4_python.core.router import get, secured

@secured()                        # THIS enforces auth on the GET
@security("bearerAuth")           # this only documents it in Swagger
@get("/reports")
async def reports(request, response):
    ...
```

* **Breaks:** relying on `@security(...)` alone to protect a public-by-default `GET` —
  the route stays open and Swagger *claims* it's secured (worst kind of drift). Note
  `tina4_python.swagger` does not even define a `noauth`, so
  `from tina4_python.swagger import noauth` raises `ImportError` (it's not a silent
  docs-only bypass — just import from `core.router`).

### Decorator order: route decorator innermost, meta above

```python
@noauth()                 # meta (auth/docs) decorators on top
@description("...")
@post("/webhook")         # @get/@post/... innermost — closest to def
async def webhook(request, response):
    ...
```

Putting `@post(...)` above `@description(...)` crashes at registration. The middleware
decorator is purely additive — it does **not** change a route's auth requirement
(`core/router.py:755`).

## Sessions

Configure in `.env`:
```env
TINA4_SESSION_BACKEND=file    # file, redis, valkey, mongodb, database
```

### Usage
```python
@post("/login")
@noauth()
async def login(request, response):
    # After validating credentials...
    request.session.set("user_id", user.id)
    request.session.set("role", "admin")
    return response.redirect("/dashboard")

@get("/dashboard")
async def dashboard(request, response):
    user_id = request.session.get("user_id")
    if not user_id:
        return response.redirect("/login")
    user = User.find(user_id)
    return response.render("dashboard.twig", {"user": user})

@get("/logout")
async def logout(request, response):
    request.session.clear()
    return response.redirect("/")
```

## Queue System

For background jobs like sending emails, processing uploads, etc.

### Producing Messages
```python
from tina4_python import Queue

@post("/orders")
async def create_order(request, response):
    order = Order(request.body)
    order.save()

    # Queue an email notification for background processing
    Queue(topic="order-emails").push({
        "order_id": order.id,
        "email": request.body["email"],
        "type": "confirmation"
    })

    return response(order, 201)
```

### Consuming Messages
```python
from tina4_python import Queue

# Run as a background worker — consume() is a long-running generator
for job in Queue(topic="order-emails").consume():
    send_order_email(job.data)
    job.complete()
```

### Priority and Delayed Jobs
```python
from datetime import datetime, timedelta

queue = Queue(topic="order-emails")

# High priority
queue.produce("order-emails", data, priority=10)

# Delayed (absolute datetime)
queue.produce("order-emails", data, delay_until=datetime.now() + timedelta(minutes=5))

# Delayed (seconds form)
queue.produce("order-emails", data, delay_seconds=300)
```

## Email (Messenger)

```python
from tina4_python import Messenger

@post("/contact")
@noauth()
async def contact(request, response):
    Messenger().send(
        to=request.body["email"],
        subject="Thanks for reaching out",
        body="<h1>We received your message</h1>",
        html=True,                 # HTML body — the flag is `html`, not `is_html`
    )
    return response({"status": "sent"})
```

## WebSocket

### Server
```python
from tina4_python.core.router import websocket

@websocket("/ws/chat")
async def chat(connection):
    async for message in connection:
        # Broadcast to all connected clients
        await connection.broadcast(message.data)
```

> Import `websocket` from `tina4_python.core.router` — it is not re-exported from the top-level
> `tina4_python` package.

### Client (frond.js)
```javascript
const ws = Frond.ws("/ws/chat", {
    onMessage: (data) => {
        document.getElementById("messages").innerHTML += `<p>${data.text}</p>`;
    }
});

document.getElementById("send").onclick = () => {
    ws.send({ text: document.getElementById("input").value });
};
```

## GraphQL

Auto-generate a GraphQL API from your ORM models. Build the instance, register your models, then
designate it the default so the framework serves it:

```python
from tina4_python import GraphQL

gql = GraphQL()
gql.auto_register(User, Post)
GraphQL.set_default(gql)   # serves the schema at /graphql (GET = GraphiQL IDE, POST = queries)
```

The endpoint path is `/graphql` by default (override with `TINA4_GRAPHQL_ENDPOINT`). There is no
`register_route` method — `set_default(gql)` is what wires the live schema.

Decorator-based resolvers register at import time:
```python
from tina4_python import GraphQL

@GraphQL.resolve("Query", "userByEmail")
def by_email(root, args, ctx):
    return User.find({"email": args["email"]})[0:1]
```

Visit `/graphql` in the browser for the GraphiQL IDE.

## Events

Decouple your app logic with events:
```python
from tina4_python import on, emit

@on("user.created")
async def send_welcome(data):
    Messenger().send(to=data["email"], subject="Welcome!", body="...")

@on("user.created")
async def setup_defaults(data):
    Settings({"user_id": data["id"], "theme": "light"}).save()

# Fire the event:
@post("/register")
@noauth()
async def register(request, response):
    user = User(request.body)
    user.save()
    emit("user.created", {"id": user.id, "email": user.email})
    return response(user, 201)
```

## i18n / Localization

Translation files go in `src/locales/` as JSON:
```json
// src/locales/en.json
{ "welcome": "Welcome, {name}!", "logout": "Sign out" }

// src/locales/fr.json
{ "welcome": "Bienvenue, {name}!", "logout": "Déconnexion" }
```

Set the default language in `.env`:
```env
TINA4_LOCALE=en
```

Translate in Python with the `I18n` class, then pass the strings into your template context —
there is no `| trans` template filter:
```python
from tina4_python.i18n import I18n

i18n = I18n()                                   # reads TINA4_LOCALE / src/locales
i18n.set_locale(request.query.get("lang", "en"))    # route has no {lang} param → read from ?lang=

@get("/")
async def home(request, response):
    return response.render("home.twig", {
        "welcome": i18n.translate("welcome", {"name": user.name}),
        "logout": i18n.translate("logout"),
    })
```

`I18n` also exposes `.t(key, **kwargs)` for keyword-style interpolation. In the template these
are just plain variables: `{{ welcome }}`, `{{ logout }}`.

## Caching

Built-in, zero-dependency caching. Use `{% cache "name" seconds %}` blocks in Frond templates
(see `templates-and-frontend.md`), or the response/cache API in code for expensive operations.
