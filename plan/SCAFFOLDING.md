# Rich Scaffolding Plan — Python

## Commands

| Command | Output |
|---------|--------|
| `generate model Product --fields "name:string,price:float"` | `src/orm/Product.py` + `migrations/TS_create_product.sql` |
| `generate route products --model Product` | `src/routes/products.py` with ORM CRUD |
| `generate crud Product --fields "name:string,price:float"` | model + migration + routes + template + test |
| `generate migration add_category` | `migrations/TS_add_category.sql` with UP/DOWN |
| `generate middleware AuthLog` | `src/middleware/auth_log.py` with before/after |
| `generate test products` | `tests/test_products.py` with pytest class |

## Field Type Mapping

| CLI | ORM Field | SQL |
|-----|-----------|-----|
| string | StringField | TEXT |
| int/integer | IntegerField | INTEGER |
| float/numeric | NumericField | REAL |
| bool/boolean | BooleanField | INTEGER |
| text | TextField | TEXT |
| datetime | DateTimeField | TEXT |
| blob | BlobField | BLOB |

## Table Convention
- Singular by default: `Product` → `product`
- Override: `plural_table = True` → `products`

## DX Fixes
- `--no-browser` flag + `TINA4_OPEN_BROWSER=false` env var
- Kill existing process on port with warning
- Fix CLI import crash (detect_ai_names → install_all)

## Files to Modify
- `tina4_python/cli/__init__.py` — all generators, flag parsing
- `tina4_python/core/server.py` — --no-browser, port-kill

## Tests
- `tests/test_cli_generate.py` — 15 test cases covering all generators
