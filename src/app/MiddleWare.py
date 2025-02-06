# Example of using middleware to intercept and modify routes

class MiddleWare:

    @staticmethod
    def before_route(request, response):
        response.headers['Andre-Control-Allow-Origin-Before'] = '*'
        response.content = "Before"
        return request, response

    @staticmethod
    def after_route(request, response):
        response.headers['Andre-Control-Allow-Origin-After'] = '*'
        response.content += "MEH"
        return request, response

    @staticmethod
    def before_and_after(request, response):
        response.content += "Before After"
        response.headers['Andre-Control-Allow-Origin-BEFORE_AFTER'] = '*'
        return request, response
