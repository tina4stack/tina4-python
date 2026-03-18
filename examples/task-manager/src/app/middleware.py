class AuthRequired:
    """Middleware that checks for an active user session."""

    @staticmethod
    def before_check_session(request, response):
        user_id = request.session.get("user_id")
        if user_id is None:
            return request, response.redirect("/login")
        return request, response
