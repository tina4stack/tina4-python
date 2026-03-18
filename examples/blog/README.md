# Blog Example

A blog with posts, comments, admin CRUD, and API documentation.

## Features
- ORM models (Post, Comment)
- Database migrations (SQLite)
- Twig template inheritance
- Auto-seeding with FakeData (20 posts, 50 comments)
- CRUD admin panel at `/admin/posts`
- Swagger API docs at `/swagger`
- Comment form with CSRF token

## Run
```bash
cd examples/blog
python app.py
# Open http://localhost:7145
```
