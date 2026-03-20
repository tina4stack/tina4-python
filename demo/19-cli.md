# CLI

Tina4 provides a command-line interface for project scaffolding, server management, migrations, seeding, testing, and route inspection. The CLI binary is `tina4python`.

## Available Commands

```bash
tina4python help                    # Show help
tina4python init [dir]              # Scaffold a new project
tina4python serve [port]            # Start dev server
tina4python start [port]            # Alias for serve
tina4python migrate                 # Run pending migrations
tina4python migrate:create <desc>   # Create a new migration file
tina4python migrate:rollback        # Rollback last migration batch
tina4python seed                    # Run database seeders
tina4python routes                  # List all registered routes
tina4python test                    # Run test suite
tina4python build                   # Build distributable package
tina4python ai [--all]              # Detect AI tools and install context
```

## Project Scaffolding

Create a new project with the standard directory structure.

```bash
tina4python init my-project
cd my-project
```

This creates:

```
my-project/
  app.py              # Entry point
  .env                # Environment variables
  .gitignore          # Git ignore rules
  Dockerfile          # Container configuration
  CLAUDE.md           # AI assistant context
  src/
    routes/            # Route handlers
    orm/               # ORM models
    app/               # Shared helpers
    templates/         # Twig templates
    public/            # Static files
    scss/              # SCSS files
    seeds/             # Seeder scripts
  migrations/          # SQL migration files
  tests/               # Test files
```

## Development Server

```bash
# Start on default port (7145)
tina4python serve

# Start on custom port
tina4python serve 8080
```

With `TINA4_DEBUG_LEVEL=ALL` in `.env`, the dev server enables:
- Live-reload on `.py`, `.twig`, `.html`, `.js` changes
- CSS hot-reload on SCSS changes (no full page refresh)
- SCSS auto-compilation
- Error overlay in the browser
- Hot-patching via jurigged

## Migrations

### Create a Migration

```bash
tina4python migrate:create "create users table"
# Creates: migrations/000001_create_users_table.sql
```

Edit the generated SQL file:

```sql
-- migrations/000001_create_users_table.sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Run Migrations

```bash
tina4python migrate
```

Migrations run in alphabetical order. Each runs once -- state is tracked in the `tina4_migration` table. Failed migrations roll back automatically.

### Rollback

```bash
tina4python migrate:rollback
```

Uses `.down.sql` files if available.

## Seeding

```bash
tina4python seed
```

Discovers and runs seeder scripts in `src/seeds/`.

## Routes

List all registered routes with method, path, and auth status.

```bash
tina4python routes
```

Output:

```
METHOD  PATH                 AUTH
GET     /api/users           public
POST    /api/users           required
GET     /api/users/{id:int}  public
PUT     /api/users/{id:int}  required
DELETE  /api/users/{id:int}  required
GET     /health              public
```

## Testing

```bash
tina4python test
```

Discovers `@tests` decorators in `src/**/*.py` files and runs them. Also supports standard pytest:

```bash
python -m pytest tests/
```

## AI Tool Integration

Detect installed AI coding assistants and install framework context files.

```bash
tina4python ai          # Auto-detect and configure
tina4python ai --all    # Install for all supported tools
```

Supports: Claude Code, Cursor, GitHub Copilot, and others.

## Running the App Directly

You can also start the server from `app.py`:

```bash
python app.py
python app.py 8080              # Custom port
python app.py 8080 "My App"     # Custom port and name
```

## Tips

- Always run `tina4python migrate` after creating migration files.
- Use `tina4python routes` to verify your routes are registered correctly.
- Set `TINA4_DEBUG_LEVEL=ALL` in `.env` for the best development experience.
- Run `tina4python ai` after setting up a new project to configure AI assistant context.
- The `serve` and `start` commands are aliases -- use whichever you prefer.
