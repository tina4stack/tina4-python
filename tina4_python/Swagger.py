#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os, re
import tina4_python
from tina4_python import Messages, Constant


class Swagger:
    @staticmethod
    def set_swagger_value(callback, key_name, value):
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {}
        if "swagger" not in tina4_python.tina4_routes[callback]:
            tina4_python.tina4_routes[callback]["swagger"] = {}
        tina4_python.tina4_routes[callback]["swagger"][key_name] = value

    @staticmethod
    def add_descripton(description, callback):
        Swagger.set_swagger_value(callback, "description", description)

    @staticmethod
    def add_summary(summary, callback):
        Swagger.set_swagger_value(callback, "summary", summary)

    @staticmethod
    def add_secure(callback):
        Swagger.set_swagger_value(callback, "secure", True)

    @staticmethod
    def add_tags(tags, callback):
        Swagger.set_swagger_value(callback, "tags", tags)

    @staticmethod
    def add_example(example, callback):
        Swagger.set_swagger_value(callback, "example", example)

    @staticmethod
    def add_params(params, callback):
        Swagger.set_swagger_value(callback, "params", params)

    @staticmethod
    def get_path_inputs(route_path):
        url_segments = route_path.strip('/').split('/')
        route_segments = route_path.strip('/').split('/')
        try:
            variables = {}
            for i, segment in enumerate(route_segments):
                if '{' in segment and '}' in segment:  # parameter part
                    param_name = re.search(r'{(.*?)}', segment).group(1)
                    variables[param_name] = url_segments[i]

            params = []
            for variable in variables:
                params.append({"name": variable, "in": "path", "type": "string"})
        except Exception as e:
            return []

        return params

    @staticmethod
    def get_swagger_entry(url, method, tags, summary, description, produces, security, params=None, example=None,
                          responses=None):

        if params is None:
            params = []

        schema = {}
        if example is not None:
            schema = {"type": "object", "example": example}

        secure_annotation = [],
        if security:
            secure_annotation = [{"bearerAuth": []}];

        new_params = []
        for param in params:
            param_value = param.split("=")
            if len(param_value) < 2:
                param_value.append("")
            new_params.append({"name": param_value[0], "in": "query", "type": "string", "default": param_value[1]})

        params = [*new_params, *Swagger.get_path_inputs(url)]

        entry = {
            "tags": tags,
            "summary": summary,
            "description": description,
            "produces": produces,
            "parameters": params,
            "requestBody": {
                "description": "Example Object",
                "required": True,
                "content": {
                    "application/json": {
                        "schema": schema
                    }
                }
            },
            "security": secure_annotation,
            "responses": responses
        };

        if method == Constant.TINA4_GET or example is None:
            del entry["requestBody"]

        return entry

    @staticmethod
    def parse_swagger(swagger):
        if not "tags" in swagger:
            swagger["tags"] = []
        if not "params" in swagger:
            swagger["params"] = []
        if not "description" in swagger:
            swagger["description"] = ""
        if not "summary" in swagger:
            swagger["summary"] = ""
        if not "example" in swagger:
            swagger["example"] = None
        if not "secure" in swagger:
            swagger["secure"] = None

        if isinstance(swagger["tags"], str):
            swagger["tags"] = [swagger["tags"]]

        return swagger

    @staticmethod
    def get_json(request):
        paths = {}
        for route in tina4_python.tina4_routes.values():

            if "swagger" in route:
                if route["swagger"] is not None:
                    swagger = Swagger.parse_swagger(route["swagger"])
                    produces = {}

                    responses = {
                        "200": {"description": "Success"},
                        "400": {"description": "Failed"}
                    }

                    if not route["route"] in paths:
                        paths[route["route"]] = {}
                    paths[route["route"]][route["method"].lower()] = Swagger.get_swagger_entry(route["route"],
                                                                                               route["method"].lower(),
                                                                                               swagger["tags"],
                                                                                               swagger["summary"],
                                                                                               swagger["description"],
                                                                                               ["application/json",
                                                                                                "html/text"],
                                                                                               swagger["secure"],
                                                                                               swagger["params"],
                                                                                               swagger["example"],
                                                                                               responses)

        if "host" in request.headers:
            host_name = request.headers["host"]
        else:
            host_name = os.getenv("HOST_NAME", "localhost")

        json_object = {
            "openapi": "3.0.0",
            "host": host_name,
            "info": {
                "title": os.getenv("SWAGGER_TITLE", "Tina4 Project(SWAGGER_TITLE)"),
                "description": os.getenv("SWAGGER_DESCRIPTION", "Description(SWAGGER_DESCRIPTION)"),
                "version": os.getenv("SWAGGER_VERSION", "1.0.0(SWAGGER_VERSION)")
            },
            "components": {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
            "basePath": "",
            "paths": paths
        }

        return json_object


def description(text):
    def actual_description(callback):
        Swagger.add_descripton(text, callback)
        return callback

    return actual_description


def summary(text):
    def actual_summary(callback):
        Swagger.add_summary(text, callback)
        return callback

    return actual_summary


def secure():
    def actual_secure(callback):
        Swagger.add_secure(callback)
        return callback

    return actual_secure


def tags(tags):
    def actual_tags(callback):
        Swagger.add_tags(tags, callback)
        return callback

    return actual_tags


def example(example):
    def actual_example(callback):
        Swagger.add_example(example, callback)
        return callback

    return actual_example


def params(params):
    def actual_params(callback):
        Swagger.add_params(params, callback)
        return callback

    return actual_params
