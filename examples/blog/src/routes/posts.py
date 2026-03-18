from tina4_python.Router import get, post, noauth
from tina4_python.Swagger import description, tags
from src.orm.Post import Post
from src.orm.Comment import Comment


@get("/")
async def home(request, response):
    posts = Post().select("*", order_by="created_at desc", limit=10)
    return response.render("pages/home.twig", {"posts": posts.to_array()})


@get("/post/{slug}")
async def view_post(slug, request, response):
    post_obj = Post()
    if not post_obj.load("slug = ?", [slug]):
        return response("Post not found", 404)
    comments = Comment().select("*", filter="post_id = ?", params=[post_obj.id], order_by="created_at desc")
    return response.render("pages/post.twig", {
        "post": post_obj.to_dict(),
        "comments": comments.to_array(),
    })


@noauth()
@post("/post/{id:int}/comment")
async def add_comment(id, request, response):
    comment = Comment({
        "post_id": id,
        "name": request.body.get("name", "Anonymous"),
        "email": request.body.get("email", ""),
        "body": request.body.get("body", ""),
    })
    comment.save()
    # Find the post slug to redirect back
    post_obj = Post()
    post_obj.load("id = ?", [id])
    return response.redirect(f"/post/{post_obj.slug}")


@description("List all blog posts")
@tags(["posts"])
@get("/api/posts")
async def api_list_posts(request, response):
    limit = int(request.params.get("limit", 10))
    skip = int(request.params.get("skip", 0))
    posts = Post().select("*", order_by="created_at desc", limit=limit, skip=skip)
    return response(posts.to_paginate())


@get("/admin/posts")
async def admin_posts(request, response):
    from tina4_python.Database import Database
    db = Database("sqlite3:app.db")
    result = db.fetch("SELECT id, title, author, created_at FROM post ORDER BY created_at DESC", limit=100)
    return response(result.to_crud(request, {"primary_key": "id", "title": "Post Management"}))
