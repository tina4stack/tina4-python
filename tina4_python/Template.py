#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Twig template engine for Tina4.

The ``Template`` class wraps Tina4's built-in TwigEngine to provide
Twig/PHP-compatible HTML rendering with automatic template discovery
from ``src/templates/``.

Features:
    - Automatic template path setup scanning ``src/templates/``
    - Built-in filters: ``json_decode``, ``base64_encode``, ``date``,
      ``slugify``, and more
    - Built-in globals: ``url``, ``root``, ``session``, ``uniqid``, ``localize``
    - Custom filter, global, test, and extension registration via
      ``add_filter()``, ``add_global()``, ``add_test()``, ``add_extension()``
    - Static file detection and binary serving
    - Label formatting helpers (``get_nice_label``)

Template paths are relative to ``src/templates/``. The engine
supports ``.twig`` and ``.html`` extensions.

Example::

    html = Template.render("/pages/home.twig", {"title": "Welcome"})
    Template.add_filter("shout", lambda s: s.upper())
"""
import ast
import html
import os
import re
import json
import base64
import tina4_python
from tina4_python import Constant
from tina4_python.Debug import Debug
from tina4_python.TwigEngine import TwigEngine, TemplateNotFound
from pathlib import Path
from datetime import datetime, date
from tina4_python.Session import Session
from random import random as RANDOM
from typing import Dict, Any
from functools import wraps


class Template:
    twig = None
    _custom_filters = {}
    _custom_globals = {}
    _custom_tests = {}
    _custom_extensions = []

    @staticmethod
    def add_filter(name, func):
        """Register a custom template filter."""
        Template._custom_filters[name] = func
        if Template.twig is not None:
            Template.twig.add_filter(name, func)

    @staticmethod
    def add_global(name, value):
        """Register a custom template global (function or value)."""
        Template._custom_globals[name] = value
        if Template.twig is not None:
            Template.twig.add_global(name, value)

    @staticmethod
    def add_test(name, func):
        """Register a custom template test for use with {% if x is testname %}."""
        Template._custom_tests[name] = func
        if Template.twig is not None:
            Template.twig.add_test(name, func)

    @staticmethod
    def add_extension(extension):
        """Register a template extension (kept for API compatibility)."""
        if extension not in Template._custom_extensions:
            Template._custom_extensions.append(extension)

    @staticmethod
    def get_environment():
        """Return the underlying TwigEngine instance, initializing if needed."""
        if Template.twig is None:
            Template.init_twig(tina4_python.root_path + os.sep + "src" + os.sep + "templates")
        return Template.twig

    @staticmethod
    def _reset():
        """Reset the template engine state. Used for testing."""
        Template.twig = None
        Template._custom_filters = {}
        Template._custom_globals = {}
        Template._custom_tests = {}
        Template._custom_extensions = []

    # initializes the twig template engine
    @staticmethod
    def init_twig(path):
        if hasattr(Template, "twig") and Template.twig is not None:
            Debug.debug("Twig found on " + path)
            return Template.twig
        Debug.debug("Initializing Twig on " + path)
        twig_path = Path(path)
        # Search project templates first, then framework built-in templates as fallback
        fw_templates = Path(tina4_python.library_path) / "templates"
        search_paths = [str(twig_path)]
        if fw_templates.is_dir() and str(fw_templates) != str(twig_path):
            search_paths.append(str(fw_templates))
        Template.twig = TwigEngine(search_paths)

        # i18n translation function — available as _() global and | translate filter
        from tina4_python.Localization import localize
        _translate = localize()
        Template.twig.add_global('_', _translate)
        Template.twig.add_filter('translate', _translate)
        Template.twig.add_global('RANDOM', RANDOM)
        Template.twig.add_global('range', range)
        Template.twig.add_global('json', json)
        Template.twig.add_global('base64encode', Template.base64encode)
        Template.twig.add_filter('base64encode', Template.base64encode)
        Template.twig.add_filter('detect_image', Template.detect_image)
        Template.twig.add_filter('json_encode', json.dumps)
        Template.twig.add_global('json_encode', json.dumps)
        Template.twig.add_filter('json_decode', Template.json_decode)
        Template.twig.add_global('json_decode', Template.json_decode)
        Template.twig.add_filter('nice_label', Template.get_nice_label)
        Template.twig.add_global('datetime_format', Template.datetime_format)
        Template.twig.add_filter('datetime_format', Template.datetime_format)
        Template.twig.add_global('formToken', Template.get_form_token)
        Template.twig.add_filter('formToken', Template.get_form_token_input)
        Template.twig.add_global('form_token', Template.get_form_token)
        Template.twig.add_filter('form_token', Template.get_form_token_input)
        debug_level = os.getenv("TINA4_DEBUG_LEVEL", "")
        if Constant.TINA4_LOG_DEBUG in debug_level or Constant.TINA4_LOG_ALL in debug_level:
            Template.twig.add_global('dump', Template.dump)
        else:
            Template.twig.add_global('dump', Template.production_dump)

        # Apply any custom filters, globals, tests registered before init
        for name, func in Template._custom_filters.items():
            Template.twig.add_filter(name, func)
        for name, value in Template._custom_globals.items():
            Template.twig.add_global(name, value)
        for name, func in Template._custom_tests.items():
            Template.twig.add_test(name, func)

        Debug.debug("Twig Initialized on " + path)
        return Template.twig

    @staticmethod
    def datetime_format(value, format="%H:%M %d-%m-%y"):
        if isinstance(value, str) and value.strip().upper() == "NOW":
            value = datetime.now()
        try:
            return value.strftime(format)
        except AttributeError:
            return value

    @staticmethod
    def production_dump(param):
        Debug.error("DUMP FOUND ON PAGE!")
        return ""

    @staticmethod
    def json_decode(param):
        param = html.unescape(param)
        return ast.literal_eval(param)

    @staticmethod
    def dump(param):
        param = html.unescape(str(param)) if param is not None else None
        if param is not None:
            def json_serialize(obj):
                if isinstance(obj, (date, datetime)):
                    return obj.isoformat()
                if isinstance(obj, Session):
                    return obj.session_values
                raise TypeError("Type %s not serializable" % type(obj))

            return "<pre>" + json.dumps(param, indent=True, default=json_serialize) + "</pre>"
        else:
            return ""

    @staticmethod
    def base64encode(param):
        value = base64.b64encode(param.encode('utf-8')).decode('utf-8')
        return value

    @staticmethod
    def get_form_token(payload=None):
        if payload is None:
            payload = {}
        return tina4_python.tina4_auth.get_token(payload)

    @staticmethod
    def get_form_token_input(form_name):
        return '<input type="hidden" name="formToken" value="' + Template.get_form_token(
            {"formName": form_name}) + '"><!--"' + str(datetime.now().isoformat()) + '"-->'

    @staticmethod
    def convert_special_types(obj):
        """
        Recursively convert non-JSON-serializable objects:
          - datetime/date -> ISO 8601 string
          - bytes -> base64 string
          - dict/list/tuple/set -> recursively processed
        Safe for deeply nested data (arrays of arrays, dicts in lists, etc.)
        """
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()

        elif isinstance(obj, bytes):
            return base64.b64encode(obj).decode('utf-8')

        elif isinstance(obj, dict):
            return {
                key: Template.convert_special_types(value)
                for key, value in obj.items()
            }

        elif isinstance(obj, (list, tuple, set)):
            return [
                Template.convert_special_types(item)
                for item in obj
            ]

        else:
            # Primitives: str, int, float, bool, None -> pass through
            return obj

    @staticmethod
    def render_twig_template(template_or_file_name, data=None):
        if data is None:
            data = {"request": tina4_python.tina4_current_request}
        else:
            data.update({"request": tina4_python.tina4_current_request})

        data = Template.convert_special_types(data)

        twig = Template.init_twig(tina4_python.root_path + os.sep + "src" + os.sep + "templates")
        try:
            try:
                template = twig.get_template(template_or_file_name)
                content = template.render(data)
            except TemplateNotFound:
                template = twig.from_string(template_or_file_name)
                content = template.render(data)

        except Exception as e:
            Debug.error("Error rendering twig file", template_or_file_name, e)
            content = str(e)

        return content

    @staticmethod
    def render(template_or_file_name, data=None):
        return Template.render_twig_template(template_or_file_name, data)

    @staticmethod
    def get_nice_label(field_name: str) -> str:
        # snake_case / camelCase / PascalCase -> words
        s = re.sub(r'[_.-]+', ' ', field_name)
        s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
        # Capitalize words & strip id
        words = s.split()
        return " ".join(word.capitalize() for word in words)

    @staticmethod
    def detect_image(value: Any) -> Dict[str, str]:
        if not value or len(value) <= 50:
            return {"content": value, "content_type": ""}

        if value[0] == '{' and value[-1] == '}':
            try:
                value = html.unescape(value)
                data = json.loads(value)
                content = data.get('content', '')

                if not content:
                    return {"content": value, "content_type": ""}

                content_type = data.get('content_type', '')
                if content_type.startswith('image/'):
                    mime_type = content_type.split('/')[1]
                    return {"content": content, "content_type": mime_type}

                # Fallback to magic bytes if no content_type
                if content[:4] == '/9j/':
                    mime_type = 'jpeg'
                elif content[:11] == 'iVBORw0KGgo':
                    mime_type = 'png'
                elif content[:6] == 'R0lGOD':
                    mime_type = 'gif'
                elif content[:5] == 'UklGR':
                    mime_type = 'webp'
                else:
                    return {"content": content, "content_type": ""}

                return {"content": content, "content_type": mime_type}
            except json.JSONDecodeError as e:
                return {"content": str(e), "content_type": ""}
        mime_type = "jpeg"
        # Check magic bytes on value
        if value[:4] == '/9j/':
            mime_type = 'jpeg'
        elif value[:11] == 'iVBORw0KGgo':
            mime_type = 'png'
        elif value[:6] == 'R0lGOD':
            mime_type = 'gif'
        elif value[:5] == 'UklGR':
            mime_type = 'webp'
        else:
            return {"content": value, "content_type": mime_type}

        return {"content": value, "content_type": mime_type}


def template(twig_file: str):
    """
    Auto-render a Twig template when the handler returns a dict.
    Works perfectly with direct parameter injection.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            # If the route returns a dict -> render the template
            if isinstance(result, dict):
                rendered = Template.render(twig_file, result)
                from tina4_python.Response import Response
                return Response(rendered, Constant.HTTP_OK, Constant.TEXT_HTML)

            # Anything else (redirects, JSON, etc.) is passed through unchanged
            return result

        return wrapper
    return decorator
