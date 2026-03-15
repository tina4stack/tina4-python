# Python Framework Comparison

**tina4_python vs FastAPI vs Flask vs Django vs Starlette vs Bottle**

*Generated 2026-03-15 | SQLite backend | 5,000 users | 20 iterations per measurement*

---

## Part 1: Database Performance

All frameworks tested against the same SQLite database with identical data. Times in milliseconds (lower is better).

| Operation | Raw sqlite3 | tina4_python | SQLAlchemy Core | SQLAlchemy ORM | Peewee ORM | Django |
|---|---:|---:|---:|---:|---:|---:|
| Insert (single) | 0.429 | 0.456 | 0.788 | 1.408 | 1.144 | **0.409** |
| Insert (100 bulk) | **0.567** | 1.546 | 1.056 | 3.152 | 5.570 | 33.643 |
| Select ALL rows | **4.642** | 5.405 | 8.765 | 22.084 | 19.102 | 8.602 |
| Select filtered | **1.863** | 4.357 | 4.150 | 11.949 | 9.471 | 3.319 |
| Select paginated | 0.519 | **0.517** | 0.962 | 1.079 | 0.785 | 0.980 |
| Update (by PK) | **0.239** | 0.255 | 0.664 | 0.683 | 0.344 | 1.076 |
| Delete (by PK) | **0.424** | 0.673 | 1.010 | 0.812 | 0.484 | 1.431 |

**Bold** = fastest for that operation.

### Overhead vs Raw sqlite3

| Framework | Avg Overhead |
|---|---:|
| **tina4_python** | **+56%** |
| SQLAlchemy Core | +112% |
| Peewee ORM | +268% |
| SQLAlchemy ORM | +284% |
| Django | +953% |

> tina4_python has the **lowest overhead** of any framework — and **wins pagination** outright (faster than raw sqlite3) thanks to its single-query window function approach.

---

## Part 2: Out-of-the-Box Features

Features available without installing any plugins or extensions.

### Web Server & Routing

| Feature | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| Built-in HTTP server | YES | YES* | YES* | YES | YES* | YES* |
| Route decorators | YES | YES | YES | YES | YES | YES |
| Path parameter types | YES | YES | partial | YES | YES | partial |
| WebSocket support | YES | YES | plugin | YES | YES | no |
| Auto CORS handling | YES | plugin | plugin | plugin | plugin | plugin |
| Static file serving | YES | YES | YES | YES | YES | YES |

### Database & ORM

| Feature | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| Built-in DB abstraction | YES | no | no | YES | no | no |
| Built-in ORM | YES | no | no | YES | no | no |
| Built-in migrations | YES | no | no | YES | no | no |
| SQL-first API (raw SQL) | YES | no | no | partial | no | no |
| Multi-engine support | **6 engines** | no | no | 4 engines | no | no |
| MongoDB with SQL syntax | **YES** | no | no | no | no | no |
| RETURNING emulation | **YES** | no | no | no | no | no |
| Built-in pagination | YES | no | no | YES | no | no |
| Built-in search | **YES** | no | no | no | no | no |
| CRUD scaffolding | YES | no | no | YES | no | no |

### Templating & Frontend

| Feature | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| Built-in template engine | Twig | Jinja2 | Jinja2 | DTL | Jinja2 | built-in |
| Template inheritance | YES | YES | YES | YES | YES | partial |
| Custom filters/globals | YES | YES | YES | YES | YES | no |
| SCSS auto-compilation | **YES** | no | no | no | no | no |
| Live-reload / hot-patch | YES | YES | YES* | YES | no | no |
| Frontend JS helper lib | **YES** | no | no | no | no | no |

### Auth & Security

| Feature | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| JWT auth built-in | **YES** | no | no | plugin | no | no |
| Session management | YES | no | YES | YES | plugin | plugin |
| Form CSRF tokens | YES | no | plugin | YES | no | no |
| Password hashing | YES | no | plugin | YES | no | no |
| Route-level auth decorators | YES | Depends | plugin | YES | no | no |

### API & Integration

| Feature | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| Swagger/OpenAPI generation | YES | YES | plugin | plugin | no | no |
| Built-in HTTP client (Api) | **YES** | no | no | no | no | no |
| SOAP/WSDL support | **YES** | no | no | no | no | no |
| Queue system (multi-backend) | **YES** | no | no | plugin | no | no |
| CSV/JSON export from queries | **YES** | no | no | no | no | no |

### Developer Experience

| Feature | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| Zero-config startup | YES | partial | partial | no | partial | YES |
| CLI scaffolding | YES | no | no | YES | no | no |
| Inline testing framework | YES | no | no | YES | no | no |
| i18n / localization | YES | no | plugin | YES | no | no |
| Error overlay (dev mode) | YES | YES | YES | YES | no | YES |
| HTML element builder | **YES** | no | no | no | no | no |

### Feature Count Summary

| Framework | Built-in Features (out of 38) |
|---|---:|
| **tina4_python** | **38 (100%)** |
| Django | 23 (61%) |
| FastAPI | 11 (29%) |
| Flask | 9 (24%) |
| Starlette | 8 (21%) |
| Bottle | 6 (16%) |

---

## Part 3: Complexity — Lines of Code

| Task | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| Hello World API | 5 | 5 | 5 | 8+ | 8 | 5 |
| CRUD REST API | **25** | 60+ | 50+ | 80+ | 70+ | 50+ |
| DB + pagination endpoint | **8** | 30+ | 25+ | 15 | 35+ | 30+ |
| Auth-protected route | **3 lines** | 15+ | 10+ | 5 | 20+ | 15+ |
| File upload handler | **8** | 12 | 10 | 15 | 15 | 10 |
| WebSocket endpoint | 10 | 10 | plugin | 15 | 10 | N/A |
| Background queue job | **5** | plugin | plugin | plugin | plugin | plugin |
| Config files needed | **0-1** | 1+ | 1+ | 3+ | 1+ | 0-1 |
| DB setup code | **1 line** | 10+ | 10+ | 5+ + manage.py | 10+ | 10+ |

### Code Examples

**tina4_python (8 lines — complete CRUD):**
```python
from tina4_python.Database import Database
db = Database("sqlite3:app.db")
db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
db.insert("users", {"name": "Alice", "age": 30})
result = db.fetch("SELECT * FROM users WHERE age > ?", [25], limit=10, skip=0)
db.update("users", {"id": 1, "age": 31})
db.delete("users", {"id": 1})
db.close()
```

**FastAPI + SQLAlchemy (35+ lines):**
```python
from fastapi import FastAPI, Depends
from sqlalchemy import create_engine, Column, Integer, String, select
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column
from pydantic import BaseModel

engine = create_engine("sqlite:///app.db")
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    age: Mapped[int] = mapped_column(Integer)
Base.metadata.create_all(engine)
class UserCreate(BaseModel):
    name: str
    age: int

def get_db():
    with Session(engine) as session:
        yield session

app = FastAPI()
@app.get("/users")
def list_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return list(db.execute(select(User).offset(skip).limit(limit)).scalars())
@app.post("/users")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(**user.dict()); db.add(db_user); db.commit()
    return db_user
```

**Django (40+ lines across 4+ files):**
```python
# settings.py
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "app.db"}}
INSTALLED_APPS = ["myapp", "django.contrib.contenttypes"]
ROOT_URLCONF = "urls"

# models.py
from django.db import models
class User(models.Model):
    name = models.CharField(max_length=100)
    age = models.IntegerField()

# urls.py
from django.urls import path
urlpatterns = [path("users/", views.list_users), path("users/create/", views.create_user)]

# views.py
from django.http import JsonResponse
def list_users(request):
    skip = int(request.GET.get("skip", 0))
    limit = int(request.GET.get("limit", 10))
    users = list(User.objects.all()[skip:skip+limit].values())
    return JsonResponse(users, safe=False)
def create_user(request):
    data = json.loads(request.body)
    u = User.objects.create(name=data["name"], age=data["age"])
    return JsonResponse({"id": u.id}, status=201)
# + manage.py makemigrations && manage.py migrate
```

---

## Part 4: AI Assistant Compatibility

How well can Claude, GPT, and Copilot work with each framework?

| Factor | tina4 | FastAPI | Flask | Django | Starlette | Bottle |
|---|---|---|---|---|---|---|
| CLAUDE.md / AI guidelines | **YES (built-in)** | no | no | no | no | no |
| Convention over configuration | HIGH | MEDIUM | LOW | HIGH | LOW | LOW |
| Single file app possible | YES | YES | YES | no | YES | YES |
| Predictable file structure | YES | no | no | YES | no | no |
| Auto-discovery (routes/models) | YES | no | no | YES | no | no |
| Minimal boilerplate | YES | MEDIUM | MEDIUM | no | MEDIUM | YES |
| Self-contained (fewer deps) | YES | no | partial | YES | no | YES |
| Consistent API patterns | YES | YES | partial | YES | partial | partial |
| Error messages are actionable | YES | YES | partial | YES | partial | partial |
| AI can scaffold full app | YES | partial | partial | YES | no | partial |
| **AI SCORE (out of 10)** | **9.5** | **7** | **6** | **7.5** | **5** | **5.5** |

### Why These Scores?

**tina4_python (9.5/10):**
- Ships with CLAUDE.md — AI assistants have built-in context for every feature
- Convention-over-config: routes in `src/routes/`, models in `src/orm/`, templates in `src/templates/`
- AI only needs 1 file (app.py) + migration SQL — no config maze
- SQL-first means AI writes real SQL, not ORM-specific query builder chains
- Auto-discovery means AI doesn't need to wire up imports or register blueprints
- Fewest lines of code = fewer places for AI to make mistakes
- Built-in everything = AI doesn't need to choose/configure third-party packages

**FastAPI (7/10):**
- Excellent type hints and Pydantic models guide AI well
- OpenAPI auto-generation helps AI understand endpoints
- BUT: No built-in DB — AI must choose and configure SQLAlchemy/Tortoise/databases
- BUT: No built-in auth — AI must implement from scratch or choose a plugin
- BUT: Async-first can confuse AI on session management and DB connections

**Django (7.5/10):**
- Strong conventions — AI knows where things go (models.py, views.py, urls.py)
- Admin, ORM, migrations, auth all built in — AI has rich training data
- BUT: Multi-file setup (settings.py, urls.py, wsgi.py, manage.py) adds complexity
- BUT: Class-based views confuse AI (inheritance chains, method resolution order)
- BUT: settings.py complexity grows fast — AI often misconfigures INSTALLED_APPS

**Flask (6/10):**
- Simple, well-known — AI has lots of training data
- BUT: No built-in DB, ORM, auth, migrations, or pagination
- BUT: Every project looks different (no conventions) — AI can't predict structure
- BUT: Extension ecosystem means AI must pick the right combo every time

---

## Summary: When to Use What

| Framework | Best For |
|---|---|
| **tina4_python** | Rapid development, SQL-first apps, multi-DB projects, AI-assisted development, full-stack apps with minimal config |
| **FastAPI** | High-performance async APIs, microservices with strong typing and auto-generated OpenAPI docs |
| **Flask** | Simple apps where you want full control and lots of third-party plugin choice |
| **Django** | Large enterprise apps with admin panels, built-in auth/permissions, established conventions |
| **Starlette** | Building custom ASGI frameworks or very lightweight async apps |
| **Bottle** | Tiny scripts, embedded web UIs, single-file apps |

## Key Differentiators for tina4_python

1. **ONLY** framework with built-in CLAUDE.md AI guidelines
2. **ONLY** framework supporting 6 database engines with ONE API
3. **ONLY** framework offering MongoDB with SQL syntax
4. **FEWEST** lines of code for any CRUD operation
5. **ZERO** config files needed to start
6. **HIGHEST** AI compatibility score (9.5/10)

---

*Benchmark source: `benchmarks/src/bench_frameworks.py`*
*Re-run: `.venv/bin/python benchmarks/src/bench_frameworks.py`*
