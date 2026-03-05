#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import gettext

_ = gettext.gettext

# --- Debug level messages ---
MSG_DEBUG = _('Debug: {message}')
MSG_WARNING = _('Warning: {message}')
MSG_ERROR = _('Error: {message}')
MSG_INFO = _('Info: {message}')

# --- Router messages ---
MSG_ROUTER_MATCHING = _('Matching: {matching}')
MSG_ROUTER_VARIABLES = _('Variables: {variables}')
MSG_ROUTER_ROOT_PATH = _('Root Path {root_path} {url}')
MSG_ROUTER_STATIC_FILE = _('Attempting to serve static file: {static_file}')
MSG_ROUTER_CSS_FILE = _('Attempting to serve CSS file: {css_file}')
MSG_ROUTER_IMAGE_FILE = _('Attempting to serve image file: {image_file}')
MSG_ROUTER_FORBIDDEN = _('403 - Forbidden')
MSG_ROUTER_INVALID_PARAM = _("Invalid type for path param '{param_name}': expected {expected}, got '{got}'")
MSG_ROUTER_MISSING_PARAM = _("Missing required parameter: {param_name}")

# --- Server messages ---
MSG_ASSUMING_ROOT_PATH = _('Assuming root path: {root_path}, library path: {library_path}')
MSG_LOAD_ALL_THINGS = _('Load all things')
MSG_SERVER_STARTED = _('Server started http://{host_name}:{port}')
MSG_SERVER_STOPPED = _('Server stopped.')
MSG_STARTING_WEBSERVER = _('Starting webserver on {port}')
MSG_ENTRY_POINT_NAME = _('Entry point name ... {name}')
MSG_SERVER_RUNNING = _('Tina4 Python server running on http://{host_name}:{port}')
MSG_INTERNAL_SERVER_ERROR = _('500 - Internal Server Error')

# --- Response messages ---
MSG_REDIRECTING = _('Redirecting...')
MSG_FORBIDDEN = _('403 - Forbidden')
MSG_FILE_NOT_FOUND = _('404 - File Not Found')
MSG_FILE_READ_ERROR = _('Error reading file: {error}')
MSG_CANNOT_DECODE = _('Cannot decode object of type {type}')

# --- CRUD messages ---
MSG_CRUD_RECORD_ADDED = _('{name} Record added')
MSG_CRUD_RECORD_UPDATED = _('{name} Record updated')
MSG_CRUD_RECORD_DELETED = _('{name} Record deleted')
MSG_CRUD_RENDER_ERROR = _('Error rendering CRUD: {error}')

# --- Database messages ---
MSG_DB_MISSING_CONNECTION = _('Database connection string is missing, try declaring DATABASE_PATH in the .env file.')
MSG_DB_DRIVER_NOT_FOUND = _('Could not load database driver for {driver}')
MSG_DB_MISSING_SQLITE = _('Your python is missing the sqlite3 module, please reinstall or update')
MSG_DB_MISSING_MYSQL = _('Your python is missing the mysql module, please install with {install_cmd}')
MSG_DB_MISSING_POSTGRES = _('Your python is missing the postgres module, please install with {install_cmd}')
MSG_DB_MISSING_FIREBIRD = _('Your python is missing the firebird module, please install with {install_cmd}')
MSG_DB_MISSING_MSSQL = _('Your python is missing the mssql module, please install with {install_cmd}')
MSG_DB_UNIMPLEMENTED = _('Please implement {driver} in Database.py and make a pull request!')

# --- Auth messages ---
MSG_AUTH_NO_SECRET = _('No SECRET env var set - using default secret. Set SECRET in your .env for production.')

# --- WebSocket messages ---
MSG_WS_CREATE_ERROR = _('Error creating Websocket, perhaps you need to install simple_websocket ?')
MSG_WS_CONNECTION_ERROR = _('Could not establish a socket connection: {error}')

# --- Migration messages ---
MSG_MIGRATION_FOUND = _('Migration: Found {path}')
MSG_MIGRATION_CHECKING = _('Migration: Checking file {file}')
MSG_MIGRATION_RUNNING = _('Migration: Running migration for {file}')
MSG_MIGRATION_PASSED = _('PASSED running migration for {file}')
MSG_MIGRATION_FAILED = _('FAILED running migration for {file}')
MSG_MIGRATION_ERROR = _('Migration: Failed to run {file}')

# --- CLI messages ---
MSG_CLI_NOT_INSTALLED = _('Error: tina4_python not installed. Run: pip install tina4-python')
MSG_CLI_OVERWRITING = _("Overwriting existing 'app.py' in {path}")
MSG_CLI_CREATING = _('Creating project in {path}')
MSG_CLI_PROJECT_READY = _('Project ready!')
MSG_CLI_NEXT_STEPS = _('Next steps:')
MSG_CLI_ALREADY_IN_FOLDER = _('You are already in the project folder. Run:')
MSG_CLI_DOCKERFILE_EXISTS = _('Dockerfile already exists – skipping creation')
MSG_CLI_DOCKERFILE_CREATED = _('Dockerfile created (multi-stage + uv)')
MSG_CLI_CLAUDE_EXISTS = _('CLAUDE.md already exists – skipping creation')
MSG_CLI_CLAUDE_CREATED = _('CLAUDE.md created (AI assistant guidelines)')
MSG_CLI_CLAUDE_NOT_FOUND = _('Warning: CLAUDE.md template not found in package')
MSG_CLI_STARTING_SERVER = _('Starting Tina4 server on http://localhost:{port}')
MSG_CLI_MIGRATION_EMPTY = _('Error: Migration description cannot be empty')
MSG_CLI_MIGRATION_EXAMPLE = _('Example: tina4 migrate:create create users table')
MSG_CLI_MIGRATION_CREATED = _('Migration created: {filepath}')
MSG_CLI_TRYING_LOAD = _('Trying to load dba from: {candidate}')
MSG_CLI_FAILED_EXECUTE = _('Failed to execute {candidate}: {error}')
MSG_CLI_FOUND_DBA = _('Found dba in {candidate}')
MSG_CLI_NO_DBA = _('No dba found in {candidate}')
MSG_CLI_NO_DBA_ANYWHERE = _("Could not find a 'dba' instance in any of the following files:")
MSG_CLI_FILE_EXISTS_NO_DBA = _('{file} (exists but no dba)')
MSG_CLI_FILE_NOT_FOUND = _('{file} (not found)')
MSG_CLI_DBA_HINT = _('Make sure you have something like:')
MSG_CLI_USING_DB = _('Using database: {connection}')
MSG_CLI_RUNNING_MIGRATIONS = _('Running migrations...')
MSG_CLI_MIGRATIONS_DONE = _('All migrations completed successfully!')
MSG_CLI_MIGRATION_ERROR = _('Migration error: {error}')
