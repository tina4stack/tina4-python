# Example of using middleware to intercept and modify routes


class MiddleWare:

    # Example usage:
    # print(generate_xml(xml_response))

    @staticmethod
    def before_route(request, response):
        response.headers['Andre-Control-Allow-Origin-Before'] = '*'
        response.content = "Before"
        return request, response

    @staticmethod
    def after_route(request, response):
        print(response.content)

        response.content = generate_xml(response.content)
        return request, response

    @staticmethod
    def before_and_after(request, response):
        response.content += "Before After"
        response.headers['Andre-Control-Allow-Origin-BEFORE_AFTER'] = '*'
        return request, response

