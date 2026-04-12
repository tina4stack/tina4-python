from tina4_python.core.router import get, middleware
from tina4_python.swagger import description, tags
from tina4_python.database import Database
from src.middleware.admin_auth import AdminAuth


def _get_db():
    return Database("sqlite:data/store.db")


@middleware(AdminAuth)
@tags("Chat")
@description("Get chat history grouped by client session")
@get("/api/chat/history")
async def api_chat_history(request, response):
    """Returns recent chat messages grouped by client_id for the admin helpdesk."""
    try:
        db = _get_db()

        # Get distinct active client sessions (last 24 hours)
        sessions_result = db.fetch(
            "SELECT DISTINCT client_id, MAX(created_at) as last_activity "
            "FROM chat_messages "
            "WHERE created_at > datetime('now', '-24 hours') "
            "GROUP BY client_id "
            "ORDER BY last_activity DESC",
            limit=50
        )

        sessions = []
        if sessions_result and sessions_result.records:
            for row in sessions_result.records:
                client_id = row.get("client_id", "")

                # Get messages for this client
                msgs_result = db.fetch(
                    "SELECT sender, text, is_admin, created_at "
                    "FROM chat_messages "
                    "WHERE client_id = ? "
                    "ORDER BY created_at ASC",
                    params=[client_id],
                    limit=200
                )

                messages = []
                if msgs_result and msgs_result.records:
                    for m in msgs_result.records:
                        messages.append({
                            "sender": m.get("sender", "Guest"),
                            "text": m.get("text", ""),
                            "is_admin": bool(m.get("is_admin", 0)),
                            "created_at": m.get("created_at", ""),
                        })

                # Determine a display name from the first non-admin message sender
                name = client_id
                for m in messages:
                    if not m["is_admin"] and m["sender"] and m["sender"] != "Guest":
                        name = m["sender"]
                        break

                sessions.append({
                    "client_id": client_id,
                    "name": name,
                    "last_activity": row.get("last_activity", ""),
                    "messages": messages,
                })

        return response({"sessions": sessions}, 200)

    except Exception as e:
        return response({"error": str(e)}, 500)
