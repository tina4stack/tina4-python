#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import ast
import html
import os
import re
import json
import base64
import tina4_python
from tina4_python import Constant
from tina4_python.Debug import Debug
from pathlib import Path
from datetime import datetime, date
from jinja2 import Environment, FileSystemLoader, Undefined
from tina4_python.Session import Session
from random import random as RANDOM
from typing import Dict, Any


class Template:
    # initializes the twig template engine
    @staticmethod
    def init_twig(path):
        if hasattr(Template, "twig"):
            Debug("Twig found on " + path, Constant.TINA4_LOG_DEBUG)
            return Template.twig
        Debug("Initializing Twig on " + path, Constant.TINA4_LOG_DEBUG)
        twig_path = Path(path)
        Template.twig = Environment(loader=FileSystemLoader(Path(twig_path)))
        Template.twig.add_extension('jinja2.ext.debug')
        Template.twig.add_extension('jinja2.ext.do')
        Template.twig.globals['RANDOM'] = RANDOM
        Template.twig.globals['json'] = json
        Template.twig.globals['base64encode'] = Template.base64encode
        Template.twig.filters['base64encode'] = Template.base64encode
        Template.twig.filters['detect_image'] = Template.detect_image
        Template.twig.filters['json_encode'] = json.dumps
        Template.twig.globals['json_encode'] = json.dumps
        Template.twig.filters['json_decode'] = Template.json_decode
        Template.twig.globals['json_decode'] = Template.json_decode
        Template.twig.filters['nice_label'] = Template.get_nice_label
        Template.twig.globals['formToken'] = Template.get_form_token
        Template.twig.filters['formToken'] = Template.get_form_token_input
        if Constant.TINA4_LOG_DEBUG in os.getenv("TINA4_DEBUG_LEVEL") or Constant.TINA4_LOG_ALL in os.getenv(
                "TINA4_DEBUG_LEVEL"):
            Template.twig.globals['dump'] = Template.dump
        else:
            Template.twig.globals['dump'] = Template.production_dump
        Debug("Twig Initialized on " + path, Constant.TINA4_LOG_INFO)
        return Template.twig

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
        param = html.unescape(param)
        if param is not None and not isinstance(param, Undefined):
            def json_serialize(obj):
                if isinstance(obj, (date, datetime)):
                    return obj.isoformat()
                if isinstance(obj, Session):
                    return obj.session_values
                raise TypeError("Type %s not serializable to Jinja2 template" % type(obj))

            return "<pre>" + json.dumps(param, indent=True, default=json_serialize) + "</pre>"
        else:
            return ""

    @staticmethod
    def base64encode(param):
        value =  base64.b64encode(param.encode('utf-8')).decode('utf-8')
        Debug.info(value)
        return value

    @staticmethod
    def get_form_token(payload={}):
        return tina4_python.tina4_auth.get_token(payload)

    @staticmethod
    def get_form_token_input(form_name):
        return '<input type="hidden" name="formToken" value="' + Template.get_form_token(
            {"formName": form_name}) + '"><!--"' + str(datetime.now().isoformat()) + '"-->'

    @staticmethod
    def convert_special_types(obj):
        """
        Recursively convert non-JSON-serializable objects:
          • datetime/date → ISO 8601 string
          • bytes base64 string
          • dict/list/tuple/set → recursively processed
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
            # Primitives: str, int, float, bool, None → pass through
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
            if twig.get_template(template_or_file_name):
                template = twig.get_template(template_or_file_name)
                content = template.render(data)
            else:
                template = twig.from_string(template_or_file_name)
                content = template.render(data)

        except Exception as e:
            Debug("Error rendering twig file", template_or_file_name, e, Constant.TINA4_LOG_ERROR)
            content = str(e)

        return content

    @staticmethod
    def render(template_or_file_name, data=None):
        return Template.render_twig_template(template_or_file_name, data)

    @staticmethod
    def get_nice_label(field_name: str) -> str:
        # snake_case / camelCase / PascalCase → words
        s = re.sub(r'[_.-]+', ' ', field_name)
        s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
        # Capitalize words & strip id
        words = s.split()
        return " ".join(word.capitalize() for word in words )


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
                    return  {"content": value, "content_type": ""}

                content_type = data.get('content_type', '')
                if content_type.startswith('image/'):
                    mime_type = content_type.split('/')[1]
                    return  {"content": content, "content_type": mime_type}

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
                    return  {"content": content, "content_type": ""}

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
