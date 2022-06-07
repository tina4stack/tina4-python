#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

from jinja2 import Environment, PackageLoader, select_autoescape
env = Environment(autoescape=select_autoescape(
    enabled_extensions=('html', 'xml', 'twig'),
    default_for_string=True,
))