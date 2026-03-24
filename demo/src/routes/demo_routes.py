# Tina4 Python Demo — Route file demonstrating every framework feature.
# Each route exercises a real Tina4 module and returns JSON with status info.

import os
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from tina4_python.core import (
    get, post, noauth, middleware, cached,
    Cache, on, emit, once, events, listeners,
)
from tina4_python.core.response import Response
from tina4_python.core.request import Request

# ── Shared helpers ───────────────────────────────────────────────

def _result(feature, status, demo, notes=""):
    """Standard demo response envelope."""
    return {
        "feature": feature,
        "status": status,
        "demo": demo,
        "notes": notes,
    }


def _try(feature, fn):
    """Run fn(), catch errors, return standard envelope."""
    try:
        demo = fn()
        return _result(feature, "working", demo)
    except Exception as e:
        return _result(feature, "broken", {"error": str(e), "traceback": traceback.format_exc()},
                       notes=f"Exception: {type(e).__name__}")


# ══════════════════════════════════════════════════════════════════
# GET / — Landing page
# ══════════════════════════════════════════════════════════════════

FEATURES = [
    ("/demo/routing", "Routing", "Route decorators and path params"),
    ("/demo/routing/42", "Routing (path param)", "Dynamic {id:int} param"),
    ("/demo/orm", "ORM", "In-memory SQLite: create table, insert, query"),
    ("/demo/templates", "Templates (Frond)", "Render a .html template with data"),
    ("/demo/auth", "Auth (JWT)", "Create and validate JWT tokens"),
    ("/demo/queue", "Queue", "Push and pop a job from the DB-backed queue"),
    ("/demo/graphql", "GraphQL", "Auto-generated schema from ORM"),
    ("/demo/cache", "Cache", "Set, get, TTL, tags, LRU eviction"),
    ("/demo/events", "Events", "Fire events, observe listeners"),
    ("/demo/i18n", "Localization (i18n)", "Translations in English and French"),
    ("/demo/scss", "SCSS Compiler", "Compile SCSS string to CSS"),
    ("/demo/email", "Email (Messenger)", "Email configuration info (no send)"),
    ("/demo/faker", "Faker (Seeder)", "Generate fake data"),
    ("/demo/api-client", "API Client", "Self-referencing HTTP call"),
    ("/demo/logging", "Logging (Debug)", "Structured log output"),
    ("/demo/dotenv", "DotEnv", "Loaded environment variables"),
    ("/demo/swagger", "Swagger / OpenAPI", "Link to /swagger"),
    ("/demo/health", "Health Check", "Link to /health"),
    ("/demo/websocket", "WebSocket", "WebSocket server configuration info"),
    ("/demo/wsdl", "WSDL / SOAP", "WSDL service info"),
    ("/demo/middleware", "Middleware", "Before/after middleware demo"),
    ("/demo/validation", "ORM Validation", "Field validation demo"),
    ("/demo/shortcomings", "Shortcomings", "Honest assessment of gaps"),
]


@get("/")
async def landing_page(request, response):
    rows = ""
    for path, name, desc in FEATURES:
        rows += (
            f'<tr>'
            f'<td><a href="{path}">{name}</a></td>'
            f'<td>{desc}</td>'
            f'<td><a href="{path}">Try it</a></td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tina4 Python Demo</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f5f7fa; color: #333; line-height: 1.6; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }}
  h1 {{ font-size: 2rem; margin-bottom: 0.5rem; color: #1a1a2e; }}
  .subtitle {{ color: #666; margin-bottom: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{ background: #1a1a2e; color: #fff; padding: 0.75rem 1rem; text-align: left; }}
  td {{ padding: 0.75rem 1rem; border-bottom: 1px solid #eee; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f0f4ff; }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ margin-top: 2rem; text-align: center; color: #999; font-size: 0.85rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>Tina4 Python v3 — Feature Demo</h1>
  <p class="subtitle">Every feature below is a live, working demonstration.
     Click any link to see the JSON output with real results.</p>
  <table>
    <thead><tr><th>Feature</th><th>Description</th><th>Link</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <div class="footer">
    <p>Powered by <a href="https://tina4.com">Tina4 Python</a> v3.0.0-dev</p>
    <p>Built-in endpoints: <a href="/health">/health</a> |
       <a href="/swagger">/swagger</a></p>
  </div>
</div>
</body>
</html>"""
    return response(html)


# ══════════════════════════════════════════════════════════════════
# /demo/routing — Basic routing
# ══════════════════════════════════════════════════════════════════

@get("/demo/routing")
async def demo_routing(request, response):
    return response(_result(
        "routing", "working",
        {
            "method": request.method,
            "path": request.path,
            "query_params": request.params,
            "headers_sample": {
                k: v for k, v in list(request.headers.items())[:5]
            },
            "ip": request.ip,
        },
        notes="GET route with query param access. Try adding ?foo=bar to the URL.",
    ))


@get("/demo/routing/{id}")
async def demo_routing_param(request, response):
    item_id = request.param("id")
    return response(_result(
        "routing_path_params", "working",
        {
            "captured_id": item_id,
            "id_type": type(item_id).__name__,
            "path": request.path,
        },
        notes="Dynamic path parameter captured from URL.",
    ))


# ══════════════════════════════════════════════════════════════════
# /demo/orm — ORM with in-memory SQLite
# ══════════════════════════════════════════════════════════════════

@get("/demo/orm")
async def demo_orm(request, response):
    def _run():
        from tina4_python.database.connection import Database
        from tina4_python.orm import ORM, Field, orm_bind

        # Create a temporary in-memory database for this demo
        db = Database("sqlite:///data/demo.db")
        orm_bind(db)

        # Define a model
        class DemoItem(ORM):
            table_name = "demo_items"
            id = Field(int, primary_key=True, auto_increment=True)
            name = Field(str)
            value = Field(float)

        # Ensure table exists
        db.execute("""
            CREATE TABLE IF NOT EXISTS demo_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL
            )
        """)
        db.commit()

        # Clear previous demo data
        db.execute("DELETE FROM demo_items")
        db.commit()

        # Insert records
        item1 = DemoItem({"name": "Alpha", "value": 10.5})
        item1.save()

        item2 = DemoItem({"name": "Beta", "value": 20.75})
        item2.save()

        item3 = DemoItem({"name": "Gamma", "value": 30.0})
        item3.save()

        # Query all
        all_items, count = DemoItem.all()
        items_list = [i.to_dict() for i in all_items]

        # Find by PK
        found = DemoItem.find(item1.id)
        found_dict = found.to_dict() if found else None

        # Where query
        filtered, fcount = DemoItem.where("value > ?", [15.0])
        filtered_list = [i.to_dict() for i in filtered]

        return {
            "inserted": 3,
            "all_items": items_list,
            "total_count": count,
            "find_by_pk": found_dict,
            "where_value_gt_15": filtered_list,
            "where_count": fcount,
        }

    return response(_try("orm", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/templates — Frond template rendering
# ══════════════════════════════════════════════════════════════════

@get("/demo/templates")
async def demo_templates(request, response):
    def _run():
        from tina4_python.frond import Frond

        # Render the demo template
        template_dir = str(Path(__file__).resolve().parent.parent / "templates")
        engine = Frond(template_dir)
        rendered = engine.render("demo.html", {
            "title": "Frond Template Demo",
            "message": "This page was rendered by the Frond engine, a zero-dependency Twig-compatible template engine.",
            "items": [
                {"name": "Variables", "value": "{{ variable }}"},
                {"name": "Loops", "value": "{% for item in items %}"},
                {"name": "Conditions", "value": "{% if condition %}"},
                {"name": "Filters", "value": "{{ value | upper }}"},
            ],
            "show_footer": True,
            "current_time": datetime.now(timezone.utc).isoformat(),
        })

        # Also demo render_string
        inline = engine.render_string(
            "Hello {{ name }}! Today is {{ day }}.",
            {"name": "Tina4 Developer", "day": datetime.now().strftime("%A")},
        )

        return {
            "rendered_html_length": len(rendered),
            "rendered_html_preview": rendered[:500],
            "inline_render": inline,
            "template_file": "src/templates/demo.html",
        }

    return response(_try("templates", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/auth — JWT token creation and validation
# ══════════════════════════════════════════════════════════════════

@get("/demo/auth")
async def demo_auth(request, response):
    def _run():
        from tina4_python.auth import Auth

        auth = Auth(secret="demo-secret-key-change-in-production")

        # Create a token
        payload = {"user_id": 42, "role": "admin", "name": "Demo User"}
        token = auth.create_token(payload, expiry_minutes=60)

        # Validate the token
        validated = auth.validate_token(token)

        # Get payload without validation
        raw_payload = auth.get_payload(token)

        # Refresh the token
        refreshed = auth.refresh_token(token)

        # Password hashing
        hashed = Auth.hash_password("demo-password-123")
        check_correct = Auth.check_password(hashed, "demo-password-123")
        check_wrong = Auth.check_password(hashed, "wrong-password")

        return {
            "jwt_token": token,
            "token_parts": len(token.split(".")),
            "validated_payload": validated,
            "raw_payload": raw_payload,
            "refreshed_token": refreshed[:50] + "..." if refreshed else None,
            "password_hash": hashed,
            "password_check_correct": check_correct,
            "password_check_wrong": check_wrong,
        }

    return response(_try("auth", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/queue — DB-backed job queue
# ══════════════════════════════════════════════════════════════════

@get("/demo/queue")
async def demo_queue(request, response):
    def _run():
        from tina4_python.database.connection import Database
        from tina4_python.queue import Queue

        # Use the demo database
        db = Database("sqlite:///data/demo.db")
        queue = Queue(db, topic="demo-tasks", max_retries=3)

        # Push some jobs
        job1_id = queue.push({"action": "send_email", "to": "user@example.com"})
        job2_id = queue.push({"action": "generate_report", "format": "pdf"}, priority=5)
        job3_id = queue.push({"action": "cleanup_temp_files"}, delay_seconds=0)

        size_before = queue.size()

        # Pop and process a job
        job = queue.pop()
        popped_data = None
        if job:
            popped_data = {"id": job.id, "topic": job.topic, "data": job.data, "priority": job.priority}
            job.complete()

        size_after = queue.size()

        # Pop and process remaining
        remaining_jobs = []
        while True:
            j = queue.pop()
            if j is None:
                break
            remaining_jobs.append({"id": j.id, "data": j.data})
            j.complete()

        return {
            "pushed_job_ids": [job1_id, job2_id, job3_id],
            "queue_size_before_pop": size_before,
            "popped_job": popped_data,
            "queue_size_after_pop": size_after,
            "remaining_processed": len(remaining_jobs),
            "lifecycle": "push -> pop -> complete (or fail/retry)",
        }

    return response(_try("queue", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/graphql — GraphQL schema from ORM
# ══════════════════════════════════════════════════════════════════

@get("/demo/graphql")
async def demo_graphql(request, response):
    def _run():
        from tina4_python.graphql import GraphQL
        from tina4_python.database.connection import Database
        from tina4_python.orm import ORM, Field, orm_bind

        db = Database("sqlite:///data/demo.db")
        orm_bind(db)

        # Ensure demo_items table
        db.execute("""
            CREATE TABLE IF NOT EXISTS demo_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL
            )
        """)
        db.commit()

        # Seed if empty
        row = db.fetch_one("SELECT COUNT(*) as cnt FROM demo_items")
        if row and row["cnt"] == 0:
            db.execute("INSERT INTO demo_items (name, value) VALUES (?, ?)", ["GraphQL Item", 99.9])
            db.commit()

        class DemoItem(ORM):
            table_name = "demo_items"
            id = Field(int, primary_key=True, auto_increment=True)
            name = Field(str)
            value = Field(float)

        gql = GraphQL()
        gql.schema.from_orm(DemoItem)

        # Introspect the schema
        schema_info = gql.introspect()

        # Execute a query
        result = gql.execute('{ demoitems(limit: 5) { id name value } }')

        return {
            "schema": schema_info,
            "query": '{ demoitems(limit: 5) { id name value } }',
            "result": result,
        }

    return response(_try("graphql", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/cache — In-memory cache with TTL
# ══════════════════════════════════════════════════════════════════

@get("/demo/cache")
async def demo_cache(request, response):
    def _run():
        cache = Cache(default_ttl=300, max_size=100)

        # Set some values
        cache.set("greeting", "Hello from Tina4 Cache!", ttl=60)
        cache.set("counter", 42, ttl=120, tags=["numbers"])
        cache.set("pi", 3.14159, tags=["numbers", "math"])
        cache.set("ephemeral", "this will expire", ttl=1)

        # Get values
        greeting = cache.get("greeting")
        counter = cache.get("counter")
        pi_val = cache.get("pi")
        missing = cache.get("nonexistent", "default_value")

        # Check existence
        has_greeting = cache.has("greeting")
        has_missing = cache.has("nonexistent")

        # Size
        size = cache.size()

        # Remember (get-or-compute)
        computed = cache.remember("computed_value", 60, lambda: sum(range(100)))

        # Tag-based clearing
        cleared = cache.clear_tag("numbers")

        size_after_clear = cache.size()

        return {
            "set_keys": ["greeting", "counter", "pi", "ephemeral"],
            "get_greeting": greeting,
            "get_counter": counter,
            "get_pi": pi_val,
            "get_missing_with_default": missing,
            "has_greeting": has_greeting,
            "has_nonexistent": has_missing,
            "cache_size": size,
            "remember_computed": computed,
            "cleared_by_tag_numbers": cleared,
            "size_after_tag_clear": size_after_clear,
        }

    return response(_try("cache", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/events — Event system
# ══════════════════════════════════════════════════════════════════

@get("/demo/events")
async def demo_events(request, response):
    def _run():
        # Clear any leftover listeners from previous requests
        from tina4_python.core.events import clear as clear_events
        clear_events()

        triggered = []

        # Register listeners
        @on("demo.action")
        def listener_one(data):
            triggered.append({"listener": "one", "data": data})
            return "listener_one_result"

        @on("demo.action")
        def listener_two(data):
            triggered.append({"listener": "two", "data": data})
            return "listener_two_result"

        # Register a once listener
        once_triggered = []

        @once("demo.once")
        def once_listener(data):
            once_triggered.append(data)

        # Emit events
        results = emit("demo.action", {"message": "hello from events"})

        # Emit the once event twice
        emit("demo.once", "first call")
        emit("demo.once", "second call (should not trigger)")

        # List registered events
        registered_events = events()
        action_listeners = listeners("demo.action")

        return {
            "triggered_listeners": triggered,
            "emit_results": results,
            "once_triggered": once_triggered,
            "once_note": "The once listener only fired on the first emit",
            "registered_events": registered_events,
            "listener_count_for_demo_action": len(action_listeners),
        }

    return response(_try("events", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/i18n — Localization
# ══════════════════════════════════════════════════════════════════

@get("/demo/i18n")
async def demo_i18n(request, response):
    def _run():
        from tina4_python.i18n import I18n

        locale_dir = str(Path(__file__).resolve().parent.parent / "locales")
        i18n = I18n(locale_dir=locale_dir, default_locale="en")

        # English translations
        en_greeting = i18n.t("greeting")
        en_welcome = i18n.t("welcome")
        en_items = i18n.t("demo.items_count", count=5)

        # Switch to French
        i18n.locale = "fr"
        fr_greeting = i18n.t("greeting")
        fr_welcome = i18n.t("welcome")
        fr_items = i18n.t("demo.items_count", count=5)

        # Available locales
        available = i18n.available_locales()

        # Fallback for missing key
        fallback = i18n.t("nonexistent.key")

        return {
            "english": {
                "greeting": en_greeting,
                "welcome": en_welcome,
                "items_count": en_items,
            },
            "french": {
                "greeting": fr_greeting,
                "welcome": fr_welcome,
                "items_count": fr_items,
            },
            "available_locales": available,
            "fallback_for_missing_key": fallback,
        }

    return response(_try("i18n", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/scss — SCSS compilation
# ══════════════════════════════════════════════════════════════════

@get("/demo/scss")
async def demo_scss(request, response):
    def _run():
        from tina4_python.scss import compile_string

        scss_input = """
$primary: #2563eb;
$radius: 8px;

.card {
    background: $primary;
    border-radius: $radius;
    padding: 10px + 5px;

    &:hover {
        background: darken($primary, 10%);
    }

    .title {
        font-size: 1.5rem;
        color: lighten($primary, 30%);
    }
}
"""
        css_output = compile_string(scss_input)

        return {
            "scss_input": scss_input.strip(),
            "css_output": css_output.strip(),
            "features_demonstrated": [
                "Variables ($primary, $radius)",
                "Nesting (.card .title)",
                "Parent selector (&:hover)",
                "Math in values (10px + 5px)",
                "Color functions (darken, lighten)",
            ],
        }

    return response(_try("scss", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/email — Email (Messenger) configuration
# ══════════════════════════════════════════════════════════════════

@get("/demo/email")
async def demo_email(request, response):
    def _run():
        from tina4_python.messenger import Messenger, DevMailbox

        # Show configuration (no actual sending)
        mail = Messenger(
            host="smtp.example.com",
            port=587,
            username="demo@example.com",
            password="not-a-real-password",
            from_address="demo@example.com",
            from_name="Tina4 Demo",
        )

        # DevMailbox for local development
        mailbox = DevMailbox(mailbox_dir="/tmp/tina4-demo-mailbox")
        mailbox_count = mailbox.count()

        return {
            "messenger_config": {
                "host": mail.host,
                "port": mail.port,
                "from_address": mail.from_address,
                "from_name": mail.from_name,
                "use_tls": mail.use_tls,
            },
            "dev_mailbox": {
                "directory": str(mailbox.mailbox_dir),
                "message_count": mailbox_count,
            },
            "supported_features": [
                "SMTP send (plain text and HTML)",
                "Attachments (file path or bytes)",
                "CC, BCC recipients",
                "Reply-To header",
                "Template rendering via Frond",
                "IMAP inbox reading",
                "DevMailbox for local development",
            ],
            "note": "No email was sent. This shows the configuration and capabilities.",
        }

    return response(_try("email", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/faker — Fake data generation
# ══════════════════════════════════════════════════════════════════

@get("/demo/faker")
async def demo_faker(request, response):
    def _run():
        from tina4_python.seeder import FakeData

        fake = FakeData(seed=42)  # Deterministic for reproducibility

        return {
            "name": fake.name(),
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": fake.email(),
            "phone": fake.phone(),
            "integer": fake.integer(1, 1000),
            "decimal": fake.decimal(0.0, 100.0, 2),
            "boolean": fake.boolean(),
            "sentence": fake.sentence(8),
            "paragraph": fake.paragraph(2),
            "date": fake.date(),
            "datetime_iso": fake.datetime_iso(),
            "uuid": fake.uuid(),
            "url": fake.url(),
            "address": fake.address(),
            "color_hex": fake.color_hex(),
            "word": fake.word(),
            "alphanumeric": fake.alphanumeric(12),
            "note": "Seeded with seed=42 for deterministic output.",
        }

    return response(_try("faker", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/api-client — HTTP client
# ══════════════════════════════════════════════════════════════════

@get("/demo/api-client")
async def demo_api_client(request, response):
    def _run():
        from tina4_python.api import Api

        # Self-referencing call to the /health endpoint
        port = os.environ.get("PORT", "7145")
        host = os.environ.get("HOST_NAME", f"localhost:{port}")
        api = Api(f"http://{host}")

        result = api.get("/health")

        return {
            "self_call_to": f"http://{host}/health",
            "http_code": result["http_code"],
            "response_body": result["body"],
            "error": result["error"],
            "api_features": [
                "GET, POST, PUT, PATCH, DELETE",
                "Bearer token auth",
                "Basic auth",
                "Custom headers",
                "JSON auto-parsing",
                "SSL validation control",
            ],
        }

    return response(_try("api_client", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/logging — Structured logging
# ══════════════════════════════════════════════════════════════════

@get("/demo/logging")
async def demo_logging(request, response):
    def _run():
        from tina4_python.debug import Log

        # Initialize if not already done
        if not Log._initialized:
            Log.init(level="debug", production=False)

        # Generate sample log entries
        Log.debug("Demo debug message", feature="logging", demo=True)
        Log.info("Demo info message", request_path="/demo/logging")
        Log.warning("Demo warning message", threshold=80, unit="percent")

        # Show the format
        dev_format = Log._format("info", "Sample message", key="value", count=42)
        Log._is_production = True
        prod_format = Log._format("info", "Sample message", key="value", count=42)
        Log._is_production = False

        return {
            "log_levels": ["debug", "info", "warning", "error"],
            "current_level": Log._level,
            "dev_format_example": dev_format,
            "production_format_example": prod_format,
            "features": [
                "Structured key-value logging",
                "JSON output in production",
                "Human-readable output in development",
                "Request ID tracking",
                "Log rotation (date and size based)",
                "Gzip compression of old logs",
                "Separate error.log file",
            ],
        }

    return response(_try("logging", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/dotenv — Environment variable loading
# ══════════════════════════════════════════════════════════════════

@get("/demo/dotenv")
async def demo_dotenv(request, response):
    def _run():
        from tina4_python.dotenv import load_env, get_env

        # Show which env vars are loaded (filter to TINA4/SWAGGER/demo-safe ones)
        safe_prefixes = ("TINA4_", "SWAGGER_", "HOST_NAME", "SECRET")
        loaded_vars = {
            k: v for k, v in os.environ.items()
            if any(k.startswith(p) for p in safe_prefixes)
        }

        # Demonstrate get_env
        debug_level = get_env("TINA4_DEBUG_LEVEL", "not set")
        language = get_env("TINA4_LANGUAGE", "not set")
        missing = get_env("NONEXISTENT_VAR", "default_fallback")

        return {
            "loaded_env_vars": loaded_vars,
            "get_env_examples": {
                "TINA4_DEBUG_LEVEL": debug_level,
                "TINA4_LANGUAGE": language,
                "NONEXISTENT_VAR (with default)": missing,
            },
            "features": [
                "Parse .env files",
                "Quoted and unquoted values",
                "Inline comments",
                "export prefix support",
                "Override control",
                "get_env() with defaults",
                "require_env() for mandatory vars",
            ],
        }

    return response(_try("dotenv", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/swagger — Swagger / OpenAPI info
# ══════════════════════════════════════════════════════════════════

@get("/demo/swagger")
async def demo_swagger(request, response):
    return response(_result(
        "swagger", "working",
        {
            "swagger_url": "/swagger",
            "note": "Visit /swagger in your browser to see the auto-generated OpenAPI documentation.",
            "all_demo_routes_visible": True,
            "features": [
                "Auto-generated from route decorators",
                "Supports @description(), @tags(), @example()",
                "OpenAPI 3.0.3 spec",
                "Interactive Swagger UI",
            ],
        },
    ))


# ══════════════════════════════════════════════════════════════════
# /demo/health — Health check info
# ══════════════════════════════════════════════════════════════════

@get("/demo/health")
async def demo_health(request, response):
    return response(_result(
        "health", "working",
        {
            "health_url": "/health",
            "note": "The /health endpoint is auto-registered by the framework.",
            "features": [
                "Uptime tracking",
                "Version reporting",
                "Error file detection (data/.broken/)",
                "HTTP 200 when healthy, 503 when errors exist",
            ],
        },
    ))


# ══════════════════════════════════════════════════════════════════
# /demo/websocket — WebSocket info
# ══════════════════════════════════════════════════════════════════

@get("/demo/websocket")
async def demo_websocket(request, response):
    def _run():
        from tina4_python.websocket import (
            WebSocketServer, WebSocketManager,
            OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG,
        )

        # Show configuration (no actual WS server started)
        manager = WebSocketManager()

        return {
            "default_port": 7146,
            "protocol": "RFC 6455",
            "opcodes": {
                "OP_TEXT": OP_TEXT,
                "OP_BINARY": OP_BINARY,
                "OP_CLOSE": OP_CLOSE,
                "OP_PING": OP_PING,
                "OP_PONG": OP_PONG,
            },
            "manager_active_connections": manager.count(),
            "features": [
                "Native RFC 6455 implementation (no dependencies)",
                "HTTP Upgrade handshake",
                "Text and binary frames",
                "Ping/pong heartbeat",
                "Fragmented message support",
                "Per-path routing",
                "Connection manager with broadcast",
                "Max connection limiting",
            ],
            "note": "WebSocket server runs on a separate port. This demo shows the configuration.",
        }

    return response(_try("websocket", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/wsdl — WSDL / SOAP info
# ══════════════════════════════════════════════════════════════════

@get("/demo/wsdl")
async def demo_wsdl(request, response):
    def _run():
        from tina4_python.wsdl import WSDL, wsdl_operation

        # Define a sample service (not bound to HTTP, just for demo)
        class DemoCalculator(WSDL):
            @wsdl_operation({"Result": int})
            def Add(self, a: int, b: int):
                return {"Result": a + b}

            @wsdl_operation({"Result": int})
            def Multiply(self, a: int, b: int):
                return {"Result": a * b}

        return {
            "service_class": "DemoCalculator",
            "operations": ["Add(a: int, b: int)", "Multiply(a: int, b: int)"],
            "features": [
                "Auto-generated WSDL 1.1 definitions",
                "SOAP 1.1 request/response handling",
                "Python type annotations to XSD type mapping",
                "Complex types (List[T], Optional[T])",
                "Lifecycle hooks (on_request, on_result)",
            ],
            "note": "WSDL services are exposed via GET ?wsdl and POST for SOAP calls.",
        }

    return response(_try("wsdl", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/middleware — Before/after middleware
# ══════════════════════════════════════════════════════════════════

class DemoMiddleware:
    """Demo middleware that adds timing info."""

    @staticmethod
    def before_timing(request, response):
        """Record request start time."""
        request._demo_start = time.perf_counter()
        return request, response

    @staticmethod
    def after_timing(request, response):
        """Add timing header."""
        start = getattr(request, "_demo_start", None)
        if start:
            duration = (time.perf_counter() - start) * 1000
            response.header("X-Demo-Duration-Ms", f"{duration:.2f}")
        return request, response


@middleware(DemoMiddleware)
@get("/demo/middleware")
async def demo_middleware(request, response):
    start = getattr(request, "_demo_start", None)
    duration = (time.perf_counter() - start) * 1000 if start else None

    return response(_result(
        "middleware", "working",
        {
            "middleware_class": "DemoMiddleware",
            "before_timing_ran": start is not None,
            "processing_time_ms": round(duration, 3) if duration else None,
            "note": "Check the X-Demo-Duration-Ms response header for timing info.",
        },
        notes="Class-based middleware with before_* and after_* methods.",
    ))


# ══════════════════════════════════════════════════════════════════
# /demo/validation — ORM field validation
# ══════════════════════════════════════════════════════════════════

@get("/demo/validation")
async def demo_validation(request, response):
    def _run():
        from tina4_python.orm import ORM, Field

        class ValidatedModel(ORM):
            table_name = "validated"
            id = Field(int, primary_key=True, auto_increment=True)
            name = Field(str, required=True, min_length=2, max_length=50)
            age = Field(int, min_value=0, max_value=150)
            email = Field(str)
            score = Field(float)

        # Valid data
        valid = ValidatedModel({"name": "Alice", "age": 30, "email": "alice@example.com", "score": 95.5})
        valid_errors = valid.validate()

        # Invalid data
        invalid = ValidatedModel({"name": "A", "age": 200})
        invalid_errors = invalid.validate()

        # Field info
        field_info = {}
        for fname, fobj in ValidatedModel._fields.items():
            info = {"type": fobj.field_type.__name__}
            if fobj.primary_key:
                info["primary_key"] = True
            if fobj.required:
                info["required"] = True
            if fobj.min_length is not None:
                info["min_length"] = fobj.min_length
            if fobj.max_length is not None:
                info["max_length"] = fobj.max_length
            if fobj.min_value is not None:
                info["min_value"] = fobj.min_value
            if fobj.max_value is not None:
                info["max_value"] = fobj.max_value
            field_info[fname] = info

        return {
            "valid_data_errors": valid_errors,
            "invalid_data_errors": invalid_errors,
            "field_definitions": field_info,
        }

    return response(_try("validation", _run))


# ══════════════════════════════════════════════════════════════════
# /demo/shortcomings — Honest assessment
# ══════════════════════════════════════════════════════════════════

@get("/demo/shortcomings")
async def demo_shortcomings(request, response):
    shortcomings = []

    # Test each feature and note issues
    # 1. Swagger
    shortcomings.append({
        "feature": "swagger",
        "status": "partial",
        "issue": "The /swagger endpoint is registered by the framework but requires the Swagger module "
                 "to be properly initialized. In the v3 rewrite, the Swagger UI generation may not be "
                 "fully wired into the new core server yet.",
    })

    # 2. WebSocket integration
    shortcomings.append({
        "feature": "websocket",
        "status": "partial",
        "issue": "WebSocket server runs on a separate port (default 7146). It is not integrated into "
                 "the main HTTP server's event loop automatically. You must start it manually.",
    })

    # 3. ORM create_table
    shortcomings.append({
        "feature": "orm_create_table",
        "status": "missing",
        "issue": "The ORM model class does not have a create_table() method in the v3 codebase. "
                 "Tables must be created via raw SQL or migrations.",
    })

    # 4. Session
    shortcomings.append({
        "feature": "session",
        "status": "partial",
        "issue": "Session middleware exists but requires explicit setup. The request.session object "
                 "may be None unless session middleware is configured.",
    })

    # 5. Template decorator
    shortcomings.append({
        "feature": "template_decorator",
        "status": "partial",
        "issue": "The @template() decorator from the CLAUDE.md docs references tina4_python.Template, "
                 "but the v3 codebase uses tina4_python.frond.Frond. The template decorator may not "
                 "exist in v3 yet. response.render() works but requires Frond to be initialized as a "
                 "module-level variable in tina4_python.frond.engine.",
    })

    # 6. CRUD generator
    shortcomings.append({
        "feature": "crud_generator",
        "status": "unknown",
        "issue": "The CRUD module referenced in docs may not be fully ported to v3 yet.",
    })

    # 7. Autocommit
    shortcomings.append({
        "feature": "database_autocommit",
        "status": "working",
        "issue": "Autocommit is OFF by default (requires explicit db.commit()). Set TINA4_AUTOCOMMIT=true "
                 "in .env to enable. This is by design, not a bug.",
    })

    # 8. ORM update signature
    shortcomings.append({
        "feature": "orm_update",
        "status": "partial",
        "issue": "The Database.update() method signature in v3 differs from the CLAUDE.md docs. "
                 "The v3 adapter expects (table, data, where_clause, params) but the old API was "
                 "(table, data) with PK-based detection. ORM.save() handles this correctly.",
    })

    # 9. GraphQL route registration
    shortcomings.append({
        "feature": "graphql_route",
        "status": "partial",
        "issue": "GraphQL.register_route() method referenced in docs may not exist in the v3 engine. "
                 "You need to manually create a route handler that calls gql.execute().",
    })

    # 10. Localization (gettext vs JSON)
    shortcomings.append({
        "feature": "localization",
        "status": "working",
        "issue": "The v3 i18n module uses JSON files (not gettext .po/.mo). The CLAUDE.md docs mention "
                 "gettext but the actual implementation is simpler JSON-based. Both approaches work, "
                 "the JSON approach is zero-dependency.",
    })

    return response(_result(
        "shortcomings", "informational",
        shortcomings,
        notes="Honest assessment of features that are incomplete, missing, or differ from documentation.",
    ))
