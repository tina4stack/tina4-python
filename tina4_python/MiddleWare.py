#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import asyncio

class MiddleWare:
    def __init__(self, middleware_class):
        """

        :param middleware_class:
        """
        self.before_methods = []
        self.after_methods = []
        self.any_methods = []
        self.middleware_class = middleware_class

        self.methods_list = [method for method in vars(middleware_class) if callable(
            getattr(middleware_class, method)) and not method.startswith("__")]

        for method in self.methods_list:
            if method.startswith("before") and "after" not in method:
                self.before_methods.append(method)
            elif method.startswith("after") and "before" not in method:
                self.after_methods.append(method)
            else:
                self.any_methods.append(method)

    async def call_before_methods(self, request, response):
        """
        Call before methods
        :param request:
        :param response:
        :return:
        """
        for method in self.before_methods:
            method = getattr(self.middleware_class, method)
            result = method(request, response)
            if asyncio.iscoroutine(result):
                request, response = await result
            else:
                request, response = result

        return request, response

    async def call_after_methods(self, request, response):
        """
        Call after methods
        :param request:
        :param response:
        :return:
        """
        for method in self.after_methods:
            method = getattr(self.middleware_class, method)
            result = method(request, response)
            if asyncio.iscoroutine(result):
                request, response = await result
            else:
                request, response = result
        return request, response

    async def call_any_methods(self, request, response):
        """
        Call any methods
        :param request:
        :param response:
        :return:
        """
        for method in self.any_methods:
            method = getattr(self.middleware_class, method)
            result = method(request, response)
            if asyncio.iscoroutine(result):
                request, response = await result
            else:
                request, response = result
        return request, response

    def call_direct_method(self, request, response, method_name):
        """
        Call direct methods
        :param request:
        :param response:
        :param method_name:
        :return:
        """
        method = getattr(self.middleware_class, method_name)
        request, response = method(request, response)
        return request, response
