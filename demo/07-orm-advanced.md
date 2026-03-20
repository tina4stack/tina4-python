# ORM Advanced

Beyond basic CRUD, Tina4's ORM supports relationships, soft delete, reusable scopes, query caching, and field validation.

## Relationships

### has_one

Load a single related record. The foreign key defaults to `<parent_class>_id`.

```python
from tina4_python.orm import ORM, Field

class User(ORM):
    id   = Field(int, primary_key=True, auto_increment=True)
    name = Field(str)

class Profile(ORM):
    id      = Field(int, primary_key=True, auto_increment=True)
    user_id = Field(int)
    bio     = Field(str)

# Usage
user = User.find(1)
profile = user.has_one(Profile)  # SELECT * FROM profiles WHERE user_id = 1
if profile:
    print(profile.bio)
```

### has_many

Load multiple related records.

```python
class Post(ORM):
    id      = Field(int, primary_key=True, auto_increment=True)
    user_id = Field(int)
    title   = Field(str)

# Get all posts for a user
user = User.find(1)
posts = user.has_many(Post)  # SELECT * FROM posts WHERE user_id = 1
for post in posts:
    print(post.title)

# With pagination
posts = user.has_many(Post, limit=10, skip=0)
```

### belongs_to

Load the parent record from a child.

```python
post = Post.find(5)
author = post.belongs_to(User)  # Looks up user_id on the post
print(author.name)
```

### Custom Foreign Key

```python
# If the FK column does not follow the convention
profile = user.has_one(Profile, foreign_key="owner_id")
posts = user.has_many(Post, foreign_key="author_id")
author = post.belongs_to(User, foreign_key="author_id")
```

## Soft Delete

Enable soft delete by setting `soft_delete = True` and adding a `deleted_at` field.

```python
class Article(ORM):
    soft_delete = True
    id         = Field(int, primary_key=True, auto_increment=True)
    title      = Field(str)
    deleted_at = Field(str, default=None)
```

### Soft Delete Operations

```python
article = Article.find(1)

# Soft delete — sets deleted_at to current timestamp
article.delete()

# Restore — sets deleted_at back to None
article.restore()

# Hard delete — removes the row even with soft_delete enabled
article.force_delete()
```

### Querying with Soft Delete

```python
# Normal queries exclude soft-deleted records automatically
articles, count = Article.all()        # Only non-deleted
articles, count = Article.where("category = ?", ["tech"])  # Only non-deleted

# Include soft-deleted records
all_articles, count = Article.with_trashed()
all_articles, count = Article.with_trashed("category = ?", ["tech"])
```

## Scopes

Scopes are reusable query filters registered on a model class.

```python
# Register scopes
User.scope("active", "active = ?", [1])
User.scope("admins", "role = ?", ["admin"])

# Use them — returns (list_of_models, count)
active_users, count = User.active()
admin_users, count = User.admins(limit=50)
```

## Query Caching

Cache query results in memory with TTL-based expiry. Cached results are automatically invalidated when `.save()` is called on the same model class.

```python
# Cache for 120 seconds
users, count = User.cached(
    "SELECT * FROM users WHERE active = ?",
    [1],
    ttl=120,
    limit=50
)

# Manually clear cache for a model
User.clear_cache()
```

## Validation

Field constraints are checked on `.save()` and can be checked explicitly with `.validate()`.

```python
from tina4_python.orm import ORM, Field

class Order(ORM):
    id     = Field(int, primary_key=True, auto_increment=True)
    amount = Field(float, required=True, min_value=0.01, max_value=999999.99)
    status = Field(str, choices=["pending", "paid", "shipped", "cancelled"])
    code   = Field(str, regex=r'^ORD-\d{6}$')
    notes  = Field(str, max_length=500)

# Check for errors before saving
order = Order({"amount": -5, "status": "invalid"})
errors = order.validate()
if errors:
    print(errors)
    # ["Field 'amount': minimum value is 0.01, got -5",
    #  "Field 'status': value must be one of ['pending', 'paid', 'shipped', 'cancelled']"]
```

### Validation Constraints

| Constraint | Field Types | Description |
|-----------|-------------|-------------|
| `required=True` | All | Value cannot be None |
| `min_length=N` | str | Minimum string length |
| `max_length=N` | str | Maximum string length |
| `min_value=N` | int, float | Minimum numeric value |
| `max_value=N` | int, float | Maximum numeric value |
| `regex=r'...'` | str | Must match regex pattern |
| `choices=[...]` | str, int | Must be one of the listed values |
| `validator=fn` | All | Custom callable that raises ValueError |

### Custom Validator

```python
def validate_positive_even(value):
    if value <= 0 or value % 2 != 0:
        raise ValueError("Must be a positive even number")

class Widget(ORM):
    count = Field(int, validator=validate_positive_even)
```

## Pagination

Use `limit` and `skip` parameters on query methods to paginate.

```python
# Page 1 (first 20 records)
users, total = User.all(limit=20, skip=0)

# Page 2
users, total = User.all(limit=20, skip=20)

# From a route handler
@get("/api/users")
async def list_users(request, response):
    page = int(request.params.get("page", 1))
    per_page = int(request.params.get("per_page", 20))
    skip = (page - 1) * per_page

    users, total = User.all(limit=per_page, skip=skip)
    return response({
        "users": [u.to_dict() for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
    })
```

## Named Database Connections

Different models can use different databases.

```python
from tina4_python.orm import orm_bind

orm_bind(main_db)                   # Default for all models
orm_bind(analytics_db, name="analytics")

class PageView(ORM):
    _db = "analytics"  # Uses the "analytics" database
    id = Field(int, primary_key=True, auto_increment=True)
    url = Field(str)
    views = Field(int)
```

## Tips

- Relationships use convention-based foreign key names (`<parent>_id`). Override with the `foreign_key` parameter.
- Soft delete requires both `soft_delete = True` and a `deleted_at` field on the model.
- Scopes are class-level -- register them once (e.g., in `app.py`), use everywhere.
- Cached queries are automatically invalidated when any instance of the same model class calls `.save()`.
- Always validate user input before saving to the database.
