#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os, json
import tina4_python
from tina4_python import Constant
from tina4_python.Debug import Debug
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, environment


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
        Template.twig.globals['formToken'] = Template.get_form_token
        Template.twig.filters['formToken'] = Template.get_form_token_input
        if Constant.TINA4_LOG_DEBUG in os.getenv("TINA4_DEBUG_LEVEL") or Constant.TINA4_LOG_ALL in os.getenv("TINA4_DEBUG_LEVEL"):
            Template.twig.globals['dump'] = Template.dump
        Debug("Twig Initialized on "+path, Constant.TINA4_LOG_INFO)
        return Template.twig

    @staticmethod
    def dump(param):
        return "<pre>"+json.dumps(param, indent=True)+"</pre>"

    @staticmethod
    def get_form_token(payload={}):
        return tina4_python.tina4_auth.get_token(payload)

    @staticmethod
    def get_form_token_input(form_name):
        return '<input type="hidden" name="formToken" value="'+Template.get_form_token({"formName": form_name})+'">'

    @staticmethod
    def render_twig_template(template_or_file_name, data=None):
        if data is None:
            data = {"request": tina4_python.tina4_current_request}
        else:
            data.update({"request": tina4_python.tina4_current_request})

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
