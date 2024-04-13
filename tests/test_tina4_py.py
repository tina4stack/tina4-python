#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
from tina4_python import *


def test_route_match():
    assert Router.match('/url', '/url') == True, "Test if route matches"


def test_route_match_variable():
    assert Router.match('/url/hello', '/url/{name}') == True, "Test if route matches"
