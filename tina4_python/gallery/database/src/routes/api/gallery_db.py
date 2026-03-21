"""Gallery: Database — raw SQL query demo."""
from tina4_python.core.router import get, post, noauth
from tina4_python.database.connection import Database


@get("/api/gallery/db/tables")
async def gallery_db_tables(request, response):
    try:
        db = Database("sqlite:///data/gallery.db")
        db.execute("""
            CREATE TABLE IF NOT EXISTS gallery_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()
        tables = db.get_tables()
        return response({"tables": tables, "engine": "sqlite"})
    except Exception as e:
        return response({"error": str(e)}, 500)


@noauth()
@post("/api/gallery/db/notes")
async def gallery_db_create_note(request, response):
    try:
        db = Database("sqlite:///data/gallery.db")
        body = request.body or {}
        db.insert("gallery_notes", {
            "title": body.get("title", "Untitled"),
            "body": body.get("body", ""),
        })
        db.commit()
        return response({"created": True}, 201)
    except Exception as e:
        return response({"error": str(e)}, 500)


@get("/api/gallery/db/notes")
async def gallery_db_list_notes(request, response):
    try:
        db = Database("sqlite:///data/gallery.db")
        result = db.fetch("SELECT * FROM gallery_notes ORDER BY id DESC", limit=50)
        return response(result.to_array())
    except Exception as e:
        return response({"error": str(e)}, 500)
