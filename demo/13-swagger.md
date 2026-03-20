# Swagger / OpenAPI

Tina4 auto-generates OpenAPI 3.0.3 documentation from your route decorators. The Swagger UI is served at `/swagger` and updates automatically as you add routes.

## Documenting Routes

Use decorator metadata to describe your API endpoints.

```python
from tina4_python.core.router import post, get, noauth
from tina4_python.swagger import description, tags, example, example_response, summary

@noauth()
@description("Create a new user account with name and email")
@summary("Create user")
@tags(["Users"])
@example({"name": "Alice", "email": "alice@example.com"})
@example_response({"id": 1, "name": "Alice", "email": "alice@example.com"})
@post("/api/users")
async def create_user(request, response):
    user = User(request.body)
    user.save()
    return response(user.to_dict(), 201)
```

## Available Decorators

### @description(text)

Long-form description of what the endpoint does.

```python
@description("Retrieve a paginated list of all active users")
@get("/api/users")
async def list_users(request, response):
    return response(User.all())
```

### @summary(text)

Short one-line summary (shown in the endpoint list).

```python
@summary("List users")
@get("/api/users")
async def list_users(request, response):
    return response(User.all())
```

### @tags(tag_list)

Group endpoints by tag in the Swagger UI.

```python
@tags(["Users", "Admin"])
@get("/api/admin/users")
async def admin_users(request, response):
    return response(User.all())
```

### @example(data)

Request body example shown in the Swagger UI.

```python
@example({
    "name": "Alice",
    "email": "alice@example.com",
    "role": "admin"
})
@post("/api/users")
async def create_user(request, response):
    return response(User(request.body).save().to_dict(), 201)
```

### @example_response(data)

Response body example.

```python
@example_response({
    "id": 1,
    "name": "Alice",
    "email": "alice@example.com",
    "created_at": "2024-01-15T10:30:00Z"
})
@get("/api/users/{id:int}")
async def get_user(request, response):
    user = User.find(request.params["id"])
    return response(user.to_dict())
```

## Decorator Order

Remember: Swagger decorators go between auth decorators and route decorators.

```python
@noauth()                                    # 1. Auth control (outermost)
@description("Register a new user")          # 2. Swagger metadata
@summary("Register")                         # 2. Swagger metadata
@tags(["Auth"])                               # 2. Swagger metadata
@example({"email": "alice@example.com"})      # 2. Swagger metadata
@example_response({"token": "eyJ..."})        # 2. Swagger metadata
@post("/api/register")                        # 3. Route (innermost)
async def register(request, response):
    return response({"token": "..."}, 201)
```

## Configuration

Customize the Swagger UI via `.env`:

```bash
SWAGGER_TITLE=My API
SWAGGER_VERSION=1.0.0
SWAGGER_DESCRIPTION=REST API for My Application
SWAGGER_CONTACT_TEAM=API Team
SWAGGER_CONTACT_URL=https://example.com
SWAGGER_CONTACT_EMAIL=api@example.com
SWAGGER_DEV_URL=http://localhost:7145
```

## Full CRUD Example

```python
from tina4_python.core.router import get, post, put, delete, noauth
from tina4_python.swagger import description, tags, example, example_response

@description("List all products with pagination")
@tags(["Products"])
@example_response([{"id": 1, "name": "Widget", "price": 9.99}])
@get("/api/products")
async def list_products(request, response):
    page = int(request.params.get("page", 1))
    result = Product.all(limit=20, skip=(page - 1) * 20)
    return response([p.to_dict() for p in result[0]])

@description("Get a single product by ID")
@tags(["Products"])
@example_response({"id": 1, "name": "Widget", "price": 9.99})
@get("/api/products/{id:int}")
async def get_product(request, response):
    product = Product.find(request.params["id"])
    if not product:
        return response({"error": "Not found"}, 404)
    return response(product.to_dict())

@description("Create a new product")
@tags(["Products"])
@example({"name": "Widget", "price": 9.99})
@example_response({"id": 1, "name": "Widget", "price": 9.99})
@post("/api/products")
async def create_product(request, response):
    product = Product(request.body)
    product.save()
    return response(product.to_dict(), 201)

@description("Update a product")
@tags(["Products"])
@example({"name": "Updated Widget", "price": 12.99})
@put("/api/products/{id:int}")
async def update_product(request, response):
    product = Product.find(request.params["id"])
    if not product:
        return response({"error": "Not found"}, 404)
    for k, v in request.body.items():
        setattr(product, k, v)
    product.save()
    return response(product.to_dict())

@description("Delete a product")
@tags(["Products"])
@delete("/api/products/{id:int}")
async def delete_product(request, response):
    product = Product.find(request.params["id"])
    if not product:
        return response({"error": "Not found"}, 404)
    product.delete()
    return response({"deleted": True})
```

## Tips

- Visit `/swagger` in your browser to see the interactive API docs.
- Routes without Swagger decorators still appear, but with minimal documentation.
- Use `@tags()` consistently to group related endpoints together.
- The `@example()` decorator helps API consumers understand the expected request format.
- `@noauth()` routes are marked as "no security" in the Swagger spec; authenticated routes show Bearer auth.
