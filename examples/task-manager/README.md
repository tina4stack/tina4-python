# Task Manager Example

Session-based task management app with user authentication.

## Features
- User registration and login with bcrypt password hashing
- Session-based authentication
- Middleware protection on task routes
- CSRF tokens on all forms
- Task CRUD (create, complete, delete)
- Twig template inheritance

## Run
```bash
cd examples/task-manager
python app.py
# Open http://localhost:7146
# Register a new account, then create tasks
```
