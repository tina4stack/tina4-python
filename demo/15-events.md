# Events

Tina4 includes a zero-dependency event system based on the observer pattern. Events decouple your application components -- emit an event from one place, handle it in multiple listeners without tight coupling.

## Basic Usage

### Register and Emit

```python
from tina4_python.core.events import on, emit

@on("user.created")
def send_welcome_email(user):
    print(f"Sending welcome email to {user['email']}")

@on("user.created")
def log_signup(user):
    print(f"New signup: {user['name']}")

# Fire the event — all listeners run
emit("user.created", {"name": "Alice", "email": "alice@example.com"})
# Output:
# Sending welcome email to alice@example.com
# New signup: Alice
```

### Non-Decorator Registration

```python
from tina4_python.core.events import on, emit

def handle_order(order):
    print(f"Processing order #{order['id']}")

on("order.placed", handle_order)
emit("order.placed", {"id": 42, "total": 99.99})
```

## Priority

Higher priority listeners run first.

```python
from tina4_python.core.events import on, emit

@on("payment.received", priority=10)
def validate_payment(data):
    print("1. Validating payment")

@on("payment.received", priority=5)
def update_balance(data):
    print("2. Updating balance")

@on("payment.received", priority=0)
def send_receipt(data):
    print("3. Sending receipt")

emit("payment.received", {"amount": 100})
# Output (ordered by priority, highest first):
# 1. Validating payment
# 2. Updating balance
# 3. Sending receipt
```

## One-Time Listeners

`once()` registers a listener that auto-removes after firing.

```python
from tina4_python.core.events import once, emit

@once("app.ready")
def on_startup():
    print("App started! (this runs only once)")

emit("app.ready")  # Prints the message
emit("app.ready")  # Nothing happens — listener was removed
```

## Async Events

For async listeners, use `emit_async()`.

```python
import asyncio
from tina4_python.core.events import on, emit_async

@on("order.placed")
async def process_order(order):
    await send_notification(order)
    print(f"Notification sent for order #{order['id']}")

@on("order.placed")
def log_order(order):
    print(f"Order logged: #{order['id']}")  # Sync listeners work too

# Must be awaited
await emit_async("order.placed", {"id": 42})
```

`emit_async()` handles both sync and async listeners transparently.

## Removing Listeners

```python
from tina4_python.core.events import on, off

def my_handler(data):
    print(data)

on("test.event", my_handler)

# Remove a specific listener
off("test.event", my_handler)

# Remove ALL listeners for an event
off("test.event")
```

## Inspecting Events

```python
from tina4_python.core.events import events, listeners

# List all registered event names
print(events())  # ["user.created", "order.placed", ...]

# Get listeners for a specific event
fns = listeners("user.created")
print(f"{len(fns)} listeners registered")
```

## Clear All

```python
from tina4_python.core.events import clear

clear()  # Remove all listeners for all events
```

## Return Values

`emit()` collects and returns results from all listeners.

```python
from tina4_python.core.events import on, emit

@on("validate.order")
def check_stock(order):
    return {"stock": True}

@on("validate.order")
def check_payment(order):
    return {"payment": True}

results = emit("validate.order", {"id": 1})
print(results)  # [{"stock": True}, {"payment": True}]
```

## Practical Example: User Lifecycle

```python
# src/app/events.py
from tina4_python.core.events import on

@on("user.created")
def welcome_email(user):
    # Send welcome email via queue
    Producer(Queue(db, topic="emails")).push({
        "to": user["email"],
        "subject": "Welcome!",
        "body": f"Hello {user['name']}!",
    })

@on("user.created")
def create_default_settings(user):
    Settings({"user_id": user["id"], "theme": "light"}).save()

@on("user.created", priority=10)
def audit_log(user):
    AuditLog({"action": "user.created", "data": user}).save()

# src/routes/users.py
from tina4_python.core.events import emit

@post("/api/users")
async def create_user(request, response):
    user = User(request.body)
    user.save()
    emit("user.created", user.to_dict())
    return response(user.to_dict(), 201)
```

## Tips

- Use dot-notation for event names (`user.created`, `order.placed`, `payment.failed`).
- Register event listeners in `src/app/events.py` and import it from `app.py`.
- Use `once()` for initialization tasks that should only run at startup.
- Use `emit_async()` when any listener is async -- it handles both sync and async.
- Priority is useful when listeners must run in a specific order (validation before processing).
