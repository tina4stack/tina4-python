# GraphQL

Tina4 includes a zero-dependency GraphQL engine with a recursive-descent parser, schema builder, query executor, and automatic ORM integration. It supports queries, mutations, variables, fragments, aliases, and `@skip`/`@include` directives.

## Quick Start with ORM

The fastest way to get a GraphQL API: auto-generate the schema from your ORM models.

```python
# app.py
from tina4_python.database import Database
from tina4_python.orm import ORM, Field, orm_bind
from tina4_python.graphql import GraphQL

db = Database("sqlite:///data/app.db")
orm_bind(db)

class User(ORM):
    id    = Field(int, primary_key=True, auto_increment=True)
    name  = Field(str)
    email = Field(str)

class Product(ORM):
    id    = Field(int, primary_key=True, auto_increment=True)
    name  = Field(str)
    price = Field(float)

# Auto-generate GraphQL types, queries, and mutations
gql = GraphQL()
gql.schema.from_orm(User)
gql.schema.from_orm(Product)
```

`from_orm()` creates for each model:
- A GraphQL type with all fields
- Single-record query: `user(id: ID!)`, `product(id: ID!)`
- List query: `users(limit: Int, offset: Int)`, `products(limit: Int, offset: Int)`
- Create mutation: `createUser(name: String, email: String)`
- Update mutation: `updateUser(id: ID!, name: String, email: String)`
- Delete mutation: `deleteUser(id: ID!)`

## Route Registration

```python
from tina4_python.core.router import get, post, noauth

@noauth()
@post("/graphql")
async def graphql_post(request, response):
    query = request.body.get("query", "")
    variables = request.body.get("variables", {})
    result = gql.execute(query, variables=variables)
    return response(result)

@get("/graphql")
async def graphql_get(request, response):
    # Serve GraphiQL IDE
    return response.render("graphiql.twig")
```

## Queries

```graphql
# Single record
{ user(id: "1") { name email } }

# List with pagination
{ users(limit: 10, offset: 0) { id name email } }

# Multiple queries
{
  user(id: "1") { name }
  products(limit: 5) { id name price }
}
```

## Mutations

```graphql
# Create
mutation {
  createUser(name: "Alice", email: "alice@example.com") {
    id name email
  }
}

# Update
mutation {
  updateUser(id: "1", name: "Alice Wonder") {
    id name
  }
}

# Delete
mutation {
  deleteUser(id: "1")
}
```

## Manual Schema Definition

For custom types and resolvers beyond ORM auto-generation.

```python
gql = GraphQL()

# Define a type
gql.schema.add_type("Widget", {
    "id": "ID",
    "name": "String",
    "price": "Float",
    "inStock": "Boolean",
})

# Add a query with a resolver
gql.schema.add_query("widget", {
    "type": "Widget",
    "args": {"id": "ID!"},
    "resolve": lambda root, args, ctx: {
        "id": args["id"],
        "name": "Cog",
        "price": 5.0,
        "inStock": True,
    },
})

# Add a mutation
gql.schema.add_mutation("deleteWidget", {
    "type": "Boolean",
    "args": {"id": "ID!"},
    "resolve": lambda root, args, ctx: True,
})
```

## Variables

```graphql
query GetUser($userId: ID!) {
  user(id: $userId) {
    name
    email
  }
}
```

```python
result = gql.execute(
    'query GetUser($userId: ID!) { user(id: $userId) { name email } }',
    variables={"userId": "1"},
)
```

## Fragments

```graphql
fragment UserFields on User {
  id
  name
  email
}

{
  user(id: "1") { ...UserFields }
  users(limit: 5) { ...UserFields }
}
```

## Aliases

```graphql
{
  admin: user(id: "1") { name }
  regular: user(id: "2") { name }
}
```

## Directives

```graphql
query ($showEmail: Boolean!) {
  user(id: "1") {
    name
    email @include(if: $showEmail)
  }
}
```

Supported directives: `@skip(if: Boolean)` and `@include(if: Boolean)`.

## Programmatic Usage

Execute queries without HTTP.

```python
result = gql.execute('{ users(limit: 3) { id name } }')
print(result)
# {"data": {"users": [{"id": 1, "name": "Alice"}, ...]}}
```

## ORM Field to GraphQL Type Mapping

| ORM Field | GraphQL Type |
|-----------|-------------|
| `IntegerField` | `Int` |
| `FloatField` / `NumericField` | `Float` |
| `BooleanField` | `Boolean` |
| `StringField` / `TextField` / `DateTimeField` | `String` |
| Primary key field | `ID` |

## Tips

- Use `from_orm()` for rapid API development -- a full CRUD API in one line per model.
- Resolver exceptions are captured as GraphQL errors (not HTTP 500s).
- Combine auto-generated and manual schema entries freely.
- The engine supports nested selections, so you can query related data if your resolvers return it.
