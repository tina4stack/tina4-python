#
# Tina4 - This is not a framework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
import re
from typing import List, Dict, Any, Optional, Callable

import tina4_python
from tina4_python import Constant

class Swagger:
    """
    OpenAPI 3.0.3 compliant Swagger documentation generator for Tina4-Python
    """

    @staticmethod
    def set_swagger_value(callback: Callable, key_name: str, value: Any) -> None:
        """Internal helper to attach swagger metadata to a route callback"""
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes":[], "methods":[]}
        if "swagger" not in tina4_python.tina4_routes[callback] or tina4_python.tina4_routes[callback]["swagger"] is None:
            tina4_python.tina4_routes[callback]["swagger"] = {}
        tina4_python.tina4_routes[callback]["swagger"][key_name] = value

    @staticmethod
    def add_description(description: str, callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "description", description)

    @staticmethod
    def add_summary(summary: str, callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "summary", summary)

    @staticmethod
    def add_secure(callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "secure", True)

    @staticmethod
    def add_noauth(callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "secure", False)

    @staticmethod
    def add_tags(tags: List[str] | str, callback: Callable) -> None:
        if isinstance(tags, str):
            tags = [tags]
        Swagger.set_swagger_value(callback, "tags", tags)

    @staticmethod
    def add_example(example: Any, callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "example", example)

    @staticmethod
    def add_example_response(example: Any, callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "example_response", example)

    @staticmethod
    def add_params(params: List[str] | Dict[str, str], callback: Callable) -> None:
        Swagger.set_swagger_value(callback, "params", params)

    @staticmethod
    def _python_type_to_openapi(value: Any) -> str:
        """Map a Python value to an OpenAPI type string."""
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"

    @staticmethod
    def _schema_from_example(example: Any) -> Dict[str, Any]:
        """Infer an OpenAPI schema from a Python example value."""
        if example is None:
            return {"type": "object"}
        if isinstance(example, list):
            items_schema = Swagger._schema_from_example(example[0]) if example else {"type": "object"}
            return {"type": "array", "items": items_schema, "example": example}
        if isinstance(example, dict):
            properties = {}
            for key, value in example.items():
                prop = {"type": Swagger._python_type_to_openapi(value)}
                if isinstance(value, dict):
                    prop = Swagger._schema_from_example(value)
                elif isinstance(value, list) and value:
                    prop = {"type": "array", "items": {"type": Swagger._python_type_to_openapi(value[0])}}
                properties[key] = prop
            return {
                "type": "object",
                "properties": properties,
                "example": example
            }
        return {"type": Swagger._python_type_to_openapi(example), "example": example}

    @staticmethod
    def get_path_parameters(route_path: str) -> List[Dict[str, Any]]:
        """Extract {id} or {id:int} style path parameters and return proper OpenAPI parameter objects"""
        params = []
        type_map = {"int": "integer", "float": "number", "path": "string"}
        segments = route_path.strip("/").split("/")
        for segment in segments:
            if segment.startswith("{") and segment.endswith("}"):
                raw = segment[1:-1].strip()
                if ":" in raw:
                    param_name, param_type = raw.split(":", 1)
                    schema_type = type_map.get(param_type, "string")
                else:
                    param_name = raw
                    schema_type = "string"
                params.append({
                    "name": param_name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": schema_type},
                    "description": f"Path parameter: {param_name}"
                })
        return params

    @staticmethod
    def parse_query_params(raw_params: List[str] | Dict[str, str]) -> List[Dict[str, Any]]:
        """Convert ['page=1', 'limit'] or {'page': '1'} into OpenAPI parameter objects"""
        params = []
        if isinstance(raw_params, dict):
            raw_params = [f"{k}={v}" if v else k for k, v in raw_params.items()]

        for param in raw_params or []:
            name = param.split("=")[0].strip()
            default = param.split("=", 1)[1] if "=" in param else None
            params.append({
                "name": name,
                "in": "query",
                "required": False,
                "schema": {
                    "type": "string",
                    "default": default
                },
                "description": f"Query parameter: {name}"
            })
        return params

    @staticmethod
    def get_operation_id(route: str, method: str) -> str:
        """Generate a unique, readable operationId"""
        clean_route = re.sub(r"[{}]", "", route.strip("/"))
        parts = [p for p in clean_route.split("/") if p]
        name = "_".join(parts) if parts else "root"
        return f"{method.lower()}_{name}"

    @staticmethod
    def get_swagger_entry(
            route: str,
            method: str,
            tags: List[str],
            summary: str,
            description: str,
            secure: bool,
            query_params: List[str] | Dict,
            example: Any,
            example_response: Any
    ) -> Dict[str, Any]:

        """Build a complete OpenAPI 3.0 operation object"""
        operation = {
            "tags": tags or [],
            "summary": summary or "",
            "description": description or "",
            "operationId": Swagger.get_operation_id(route, method),
            "parameters": [
                *Swagger.get_path_parameters(route),
                *Swagger.parse_query_params(query_params)
            ],
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": Swagger._schema_from_example(example_response)
                        } if example_response else {}
                    }
                },
                "400": {
                    "description": "Bad Request",
                    "content": {"application/json": {"schema": {"type": "object", "properties": {"error": {"type": "string"}}}}}
                },
                "401": {
                    "description": "Unauthorized",
                    "content": {"application/json": {"schema": {"type": "object", "properties": {"error": {"type": "string"}}}}}
                } if secure else None,
                "404": {
                    "description": "Not Found",
                    "content": {"application/json": {"schema": {"type": "object", "properties": {"error": {"type": "string"}}}}}
                }
            },
            "security": [{"bearerAuth": []}, {"basicAuth": []}] if secure else []
        }

        # Clean None responses
        operation["responses"] = {k: v for k, v in operation["responses"].items() if v}

        # Add requestBody only for methods that support it
        if method in [Constant.TINA4_POST, Constant.TINA4_PUT, Constant.TINA4_PATCH]:
            if example is not None:
                schema = Swagger._schema_from_example(example)
            else:
                schema = {"type": "object"}

            operation["requestBody"] = {
                "required": True,
                "description": "Request payload",
                "content": {
                    "application/json": {
                        "schema": schema
                    }
                }
            }

        return operation

    @staticmethod
    def parse_swagger_metadata(swagger: Dict) -> Dict:
        """Normalize and set defaults for route swagger metadata"""
        defaults = {
            "tags": [],
            "params": [],
            "description": "",
            "summary": "",
            "example": None,
            "example_response": None,
            # Note: 'secure' default is now set per-method in get_json
        }
        for key, value in defaults.items():
            if key not in swagger or swagger[key] is None:
                swagger[key] = value

        if isinstance(swagger["tags"], str):
            swagger["tags"] = [swagger["tags"]]

        return swagger

    @staticmethod
    def get_json(request) -> Dict[str, Any]:
        """Generate full OpenAPI 3.0.3 document with BOTH Basic and Bearer Auth"""
        paths: Dict[str, Dict] = {}

        for route_info in tina4_python.tina4_routes.values():
            if "swagger" not in route_info or route_info["swagger"] is None:
                continue

            swagger = Swagger.parse_swagger_metadata(route_info["swagger"].copy())
            # Preserve the original swagger-level secure value (may be None)
            swagger_secure_orig = swagger.get("secure")

            for route in route_info.get("routes", []):
                for method in route_info.get("methods", []):
                    # Apply per-method secure default if not explicitly set
                    secured = swagger_secure_orig
                    if secured is None:
                        secured = method != Constant.TINA4_GET

                    route_noauth = route_info.get("noauth")
                    route_secure = route_info.get("secure")

                    if route_secure is not None and route_secure:
                        secured = True

                    if route_noauth is not None and route_noauth:
                       secured = False

                    operation = Swagger.get_swagger_entry(
                        route=route,
                        method=method,
                        tags=swagger["tags"],
                        summary=swagger["summary"],
                        description=swagger["description"],
                        secure=secured,
                        query_params=swagger["params"],
                        example=swagger["example"],
                        example_response=swagger["example_response"]
                    )

                    # Re-apply security based on resolved auth state
                    if secured:
                        operation["security"] = [
                            {"bearerAuth": []},
                            {"basicAuth": []}
                        ]
                    else:
                        operation["security"] = []  # public endpoint

                    if route not in paths:
                        paths[route] = {}

                    paths[route][method.lower()] = operation

        # Determine server URL
        host = request.headers.get("host", os.getenv("HOST_NAME", "localhost:8000"))
        scheme = request.headers.get("x-forwarded-proto", "http")
        base_url = os.getenv("BASE_URL", "")

        json_object = {
            "openapi": "3.0.3",
            "info": {
                "title": os.getenv("SWAGGER_TITLE", "Tina4 Python API"),
                "description": os.getenv("SWAGGER_DESCRIPTION", "Auto-generated API documentation"),
                "version": os.getenv("SWAGGER_VERSION", "1.0.0"),
                "contact": {
                    "name": os.getenv("SWAGGER_CONTACT_TEAM","Tina4 Team"),
                    "url": os.getenv("SWAGGER_CONTACT_URL","https://tina4.com"),
                    "email": os.getenv("SWAGGER_CONTACT_EMAIL","support@tina4.com")
                },
                "license": {
                    "name": "MIT",
                    "url": "https://opensource.org/licenses/MIT"
                }
            },
            "servers": [
                {"url": f"{scheme}://{host}{base_url}", "description": "Current server"},
                {"url": os.getenv("SWAGGER_DEV_URL", "http://localhost:7145"), "description": "Local development"}
            ],
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                        "description": "JWT Authorization header using the Bearer scheme. Example: `Bearer {token}`"
                    },
                    "basicAuth": {
                        "type": "http",
                        "scheme": "basic",
                        "description": "Basic authentication using username and password"
                    }
                }
            },
            "security": [],  # global: no auth by default
            "paths": paths
        }

        return json_object


# Decorators - unchanged but now fully compatible
def description(text: str):
    def decorator(callback):
        Swagger.add_description(text, callback)
        return callback
    return decorator


def summary(text: str):
    def decorator(callback):
        Swagger.add_summary(text, callback)
        return callback
    return decorator


def secure():
    def decorator(callback):
        Swagger.add_secure(callback)
        return callback
    return decorator


def noauth():
    def decorator(callback):
        Swagger.add_noauth(callback)
        if callback not in tina4_python.tina4_routes:
            tina4_python.tina4_routes[callback] = {"routes": [], "methods": []}
        tina4_python.tina4_routes[callback]["noauth"] = True
        return callback
    return decorator


def tags(tags: List[str] | str):
    def decorator(callback):
        Swagger.add_tags(tags, callback)
        return callback
    return decorator


def example(example_data: Any):
    def decorator(callback):
        Swagger.add_example(example_data, callback)
        return callback
    return decorator

def example_response(example_data: Any):
    def decorator(callback):
        Swagger.add_example_response(example_data, callback)
        return callback
    return decorator


def params(params_list: List[str] | Dict[str, str]):
    def decorator(callback):
        Swagger.add_params(params_list, callback)
        return callback
    return decorator


def describe(
        description: str = None,
        summary: str = None,
        tags: List[str] | str = None,
        params: List[str] | Dict = None,
        example: Any = None,
        example_response: Any = None,
        secure: bool = None
):
    """All-in-one decorator - most convenient

    Args:
        description: Operation description text.
        summary: Short summary text.
        tags: Tag name(s) for grouping.
        params: Query parameter definitions.
        example: Request body example (for POST/PUT/PATCH).
        example_response: Response body example.
        secure: ``True`` to require auth, ``False`` for public, ``None`` (default) to use per-method defaults.
    """
    def decorator(callback):
        if description is not None:
            Swagger.add_description(description, callback)
        if summary is not None:
            Swagger.add_summary(summary, callback)
        if tags is not None:
            Swagger.add_tags(tags, callback)
        if params is not None:
            Swagger.add_params(params, callback)
        if example is not None:
            Swagger.add_example(example, callback)
        if example_response is not None:
            Swagger.add_example_response(example_response, callback)
        if secure is True:
            Swagger.add_secure(callback)
        elif secure is False:
            Swagger.add_noauth(callback)
        return callback
    return decorator