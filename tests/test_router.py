#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

from tina4_python.Router import Router


# --- _parse_route_segment ---

def test_parse_simple_param():
    name, conv = Router._parse_route_segment("{id}")
    assert name == "id"
    assert conv == "str"


def test_parse_typed_int():
    name, conv = Router._parse_route_segment("{id:int}")
    assert name == "id"
    assert conv == "int"


def test_parse_typed_float():
    name, conv = Router._parse_route_segment("{price:float}")
    assert name == "price"
    assert conv == "float"


def test_parse_typed_path():
    name, conv = Router._parse_route_segment("{file:path}")
    assert name == "file"
    assert conv == "path"


def test_parse_unknown_type_defaults_str():
    name, conv = Router._parse_route_segment("{val:unknown}")
    assert name == "val"
    assert conv == "str"


def test_parse_fixed_segment():
    name, conv = Router._parse_route_segment("users")
    assert name is None
    assert conv is None


# --- clean_url ---

def test_clean_url_double_slash():
    assert Router.clean_url("//api//test") == "/api/test"


def test_clean_url_empty():
    assert Router.clean_url("") == "/"


def test_clean_url_none():
    assert Router.clean_url(None) == "/"


def test_clean_url_normal():
    assert Router.clean_url("/api/users") == "/api/users"


# --- _normalize_url ---

def test_normalize_url_basic():
    assert Router._normalize_url("/users") == "/users/"


def test_normalize_url_root():
    assert Router._normalize_url("/") == "/"


def test_normalize_url_empty():
    assert Router._normalize_url("") == "/"


def test_normalize_url_strips_query():
    assert Router._normalize_url("/users?page=1") == "/users/"


def test_normalize_url_strips_domain():
    assert Router._normalize_url("https://example.com/api/test") == "/api/test/"


def test_normalize_url_collapses_slashes():
    assert Router._normalize_url("//api///test//") == "/api/test/"


# --- match ---

def test_match_exact():
    assert Router.match("/users", "/users") is True


def test_match_trailing_slash():
    assert Router.match("/users/", "/users") is True


def test_match_variable():
    assert Router.match("/users/42", "/users/{id}") is True


def test_match_typed_int():
    assert Router.match("/users/42", "/users/{id:int}") is True
    assert Router.variables.get("id") == 42


def test_match_typed_int_invalid():
    assert Router.match("/users/abc", "/users/{id:int}") is False


def test_match_typed_float():
    assert Router.match("/products/19.99", "/products/{price:float}") is True
    assert Router.variables.get("price") == 19.99


def test_match_typed_float_invalid():
    assert Router.match("/products/abc", "/products/{price:float}") is False


def test_match_typed_path():
    assert Router.match("/files/docs/readme.md", "/files/{filepath:path}") is True
    assert Router.variables.get("filepath") == "docs/readme.md"


def test_match_path_greedy():
    assert Router.match("/static/css/main/style.css", "/static/{file:path}") is True
    assert Router.variables.get("file") == "css/main/style.css"


def test_match_multiple_variables():
    assert Router.match("/users/42/posts/7", "/users/{user_id}/posts/{post_id}") is True
    assert Router.variables.get("user_id") == "42"
    assert Router.variables.get("post_id") == "7"


def test_match_no_match():
    assert Router.match("/users/42", "/posts/{id}") is False


def test_match_root():
    assert Router.match("/", "/") is True


def test_match_different_lengths():
    assert Router.match("/users/42/extra", "/users/{id}") is False


def test_match_list_of_routes():
    assert Router.match("/api/v1", ["/api/v1", "/api/v2"]) is True


def test_match_list_second_route():
    assert Router.match("/api/v2", ["/api/v1", "/api/v2"]) is True


def test_match_list_none():
    assert Router.match("/api/v3", ["/api/v1", "/api/v2"]) is False


def test_match_with_query_string():
    assert Router.match("/users?page=1", "/users") is True


# --- get_variables ---

def test_get_variables_basic():
    result = Router.get_variables("/users/42", "/users/{id}")
    assert result == {"id": "42"}


def test_get_variables_typed_int():
    result = Router.get_variables("/users/42", "/users/{id:int}")
    assert result == {"id": 42}


def test_get_variables_typed_float():
    result = Router.get_variables("/items/9.99", "/items/{price:float}")
    assert result == {"price": 9.99}


def test_get_variables_typed_path():
    result = Router.get_variables("/files/a/b/c.txt", "/files/{path:path}")
    assert result == {"path": "a/b/c.txt"}


def test_get_variables_multiple():
    result = Router.get_variables("/users/5/posts/10", "/users/{uid}/posts/{pid}")
    assert result == {"uid": "5", "pid": "10"}


def test_get_variables_mismatch():
    result = Router.get_variables("/other/5", "/users/{id}")
    assert result == {}


def test_get_variables_invalid_int():
    result = Router.get_variables("/users/abc", "/users/{id:int}")
    assert result == {}


def test_get_variables_too_few_segments():
    result = Router.get_variables("/users", "/users/{id}")
    assert result == {}


# --- requires_auth ---

def test_requires_auth_secured_route():
    route = {"secure": True}
    assert Router.requires_auth(route, "GET", False) is True


def test_requires_auth_write_method():
    route = {}
    assert Router.requires_auth(route, "POST", False) is True


def test_requires_auth_write_validated():
    route = {}
    assert Router.requires_auth(route, "POST", True) is False


def test_requires_auth_get_not_secured():
    route = {}
    assert Router.requires_auth(route, "GET", False) is False


def test_requires_auth_swagger_secure():
    route = {"swagger": {"secure": True}}
    assert Router.requires_auth(route, "GET", False) is True
