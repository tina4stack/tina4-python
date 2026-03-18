# REST API Example

Full REST CRUD API with GraphQL, JWT auth, Swagger docs, and auto-seeding.

## Features
- Full REST CRUD for products (`/api/products`)
- Category listing (`/api/categories`)
- JWT bearer token auth (`POST /api/auth/token` with admin/admin)
- GraphQL endpoint at `/graphql` (GET = GraphiQL IDE, POST = queries)
- Swagger UI at `/swagger` with full documentation
- Auto-seeds 10 categories + 100 products
- Pagination support (`?limit=10&skip=0`)

## Run
```bash
cd examples/rest-api
python app.py
# Swagger: http://localhost:7147/swagger
# GraphQL: http://localhost:7147/graphql
# API:     http://localhost:7147/api/products
```

## Quick Test
```bash
# Get a token
curl -X POST http://localhost:7147/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# Create a product (use the token from above)
curl -X POST http://localhost:7147/api/products \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Widget","price":19.99,"category_id":1,"stock":50}'
```
