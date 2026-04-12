"""
Tina4 Store — Complete Framework Demo

Run: python app.py
Browse: http://localhost:7145
"""
import os
import sys
import threading

# Add store root to path so src.* imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tina4_python.core import run
from tina4_python.database import Database
from tina4_python.orm import orm_bind
from tina4_python.migration import Migration
from tina4_python.container import Container
from tina4_python.queue import Queue
from tina4_python.i18n import I18n
from tina4_python.crud import AutoCrud
from tina4_python.messenger import create_messenger
from src.app.template import frond

from src.orm.product import Product
from src.orm.category import Category

# ── Dependency Injection Container ─────────────────────────────
container = Container()
container.singleton("db", lambda: Database("sqlite:data/store.db"))
container.singleton("queue", lambda: Queue(topic="orders"))
container.singleton("i18n", lambda: I18n(locale_dir="src/locales", default_locale="en"))
container.singleton("mail", lambda: create_messenger())

# ── i18n + Template Globals ────────────────────────────────────
i18n = container.get("i18n")


def _t(key, **kwargs):
    """Template translation helper — tries dot-notation first, then searches all sections."""
    result = i18n.t(key, **kwargs)
    if result != key:
        return result
    # Search all top-level sections for the flat key
    for section in ("store", "nav", "auth", "account", "admin", "footer"):
        result = i18n.t(f"{section}.{key}", **kwargs)
        if result != f"{section}.{key}":
            return result
    return key


frond.add_global("t", _t)

# ── Database Setup ─────────────────────────────────────────────
db = container.get("db")
orm_bind(db)
Migration(db).migrate()

# ── Auto-CRUD for admin REST endpoints ─────���───────────────────
AutoCrud.register(Product, prefix="/api")
AutoCrud.register(Category, prefix="/api")

# ── Seed Demo Data (only if DB is empty) ───────────────────────
from src.seeds.seed_store import seed
seed(db)

# ── Register Event Handlers ────────────────────────────────────
# Import triggers @on() decorator registrations
import src.app.services.notification_service  # noqa: F401

# ── Register MCP Tools (AI assistant stock queries) ────────────
import src.app.services.mcp_tools  # noqa: F401

# ── Start Queue Worker in Background Thread ────────────────────
from src.app.services.order_service import process_orders


def _run_worker():
    queue = container.get("queue")
    process_orders(queue)


worker_thread = threading.Thread(target=_run_worker, daemon=True)
worker_thread.start()

# ── Start Order Simulator (demo: creates order every 60s) ─────
from src.app.services.order_simulator import run_order_simulator

simulator_thread = threading.Thread(target=run_order_simulator, args=(60,), daemon=True)
simulator_thread.start()

# ── Start Server ───────────────────────────────────────────────
if __name__ == "__main__":
    run()
