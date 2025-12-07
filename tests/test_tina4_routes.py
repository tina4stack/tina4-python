import pytest
import os
from unittest.mock import patch, MagicMock
import tina4_python
from tina4_python import Constant
from tina4_python.Router import Router
from tina4_python.Debug import Debug
from tina4_python.Template import Template

# Fixture to reset routes before each test
@pytest.fixture(autouse=True)
def reset_routes():
    tina4_python.tina4_routes = {}
    yield
    tina4_python.tina4_routes = {}

# Mock Debug to avoid actual logging
@pytest.fixture
def mock_debug():
    with patch.object(Debug, 'debug') as mock_debug, patch.object(Debug, 'error') as mock_error:
        yield mock_debug, mock_error

def test_add_single_route_single_method(mock_debug):
    mock_debug, mock_error = mock_debug  # Unpack the tuple
    def callback():
        pass

    Router.add(Constant.TINA4_GET, '/test', callback)

    assert callback in tina4_python.tina4_routes
    entry = tina4_python.tina4_routes[callback]
    assert entry['routes'] == ['/test']
    assert entry['methods'] == [Constant.TINA4_GET]
    assert entry['secure'] is False  # Since it's GET
    assert mock_debug.called

def test_add_multiple_methods_same_route(mock_debug):
    def callback():
        pass

    Router.add(Constant.TINA4_GET, '/test', callback)
    Router.add(Constant.TINA4_POST, '/test', callback)

    assert callback in tina4_python.tina4_routes
    entry = tina4_python.tina4_routes[callback]
    assert entry['routes'] == ['/test']
    assert set(entry['methods']) == {Constant.TINA4_GET, Constant.TINA4_POST}
    assert entry['secure'] is True  # Since GET is present

def test_add_multiple_routes_same_callback(mock_debug):
    def callback():
        pass

    Router.add(Constant.TINA4_GET, '/test1', callback)
    Router.add(Constant.TINA4_GET, '/test2', callback)

    assert callback in tina4_python.tina4_routes
    entry = tina4_python.tina4_routes[callback]
    assert set(entry['routes']) == {'/test1', '/test2'}
    assert entry['methods'] == [Constant.TINA4_GET]
    assert entry['secure'] is False

def test_add_duplicate_route_same_method(mock_debug):
    mock_debug, mock_error = mock_debug  # Unpack the tuple if necessary, but assuming it's already unpacked or adjust based on fixture
    def callback1():
        pass
    def callback2():
        pass

    Router.add(Constant.TINA4_GET, '/test', callback1)
    with patch.object(Debug, 'error') as mock_error:
        Router.add(Constant.TINA4_GET, '/test', callback2)
        mock_error.assert_called_with(f"Route already exists: {Constant.TINA4_GET} /test")

    # Ensure second add didn't overwrite
    assert len(tina4_python.tina4_routes) == 1
    assert list(tina4_python.tina4_routes.keys())[0] == callback1

def test_add_same_route_different_method_different_callback(mock_debug):
    def callback1():
        pass
    def callback2():
        pass

    Router.add(Constant.TINA4_GET, '/test', callback1)
    Router.add(Constant.TINA4_POST, '/test', callback2)

    assert len(tina4_python.tina4_routes) == 2
    assert tina4_python.tina4_routes[callback1]['routes'] == ['/test']
    assert tina4_python.tina4_routes[callback1]['methods'] == [Constant.TINA4_GET]
    assert tina4_python.tina4_routes[callback2]['routes'] == ['/test']
    assert tina4_python.tina4_routes[callback2]['methods'] == [Constant.TINA4_POST]

def test_add_route_with_params(mock_debug):
    def callback():
        pass

    Router.add(Constant.TINA4_GET, '/test/{id}', callback)

    entry = tina4_python.tina4_routes[callback]
    assert entry['params'] == ['id']

def test_add_multiple_routes_with_different_params(mock_debug):
    def callback():
        pass

    Router.add(Constant.TINA4_GET, '/test/{id}', callback)
    Router.add(Constant.TINA4_GET, '/test/{id}/{name}', callback)

    entry = tina4_python.tina4_routes[callback]
    assert set(entry['params']) == {'id', 'name'}

def test_match_simple_url():
    matched = Router.match('/test', ['/test'])
    assert matched is True
    assert Router.variables == {}

def test_match_with_param():
    matched = Router.match('/test/123', ['/test/{id}'])
    assert matched is True
    assert Router.variables == {'id': '123'}

def test_match_no_match_different_length():
    matched = Router.match('/test/123', '/test')
    assert matched is False

def test_match_no_match_different_segment():
    matched = Router.match('/test/abc', '/test/{id}/def')
    assert matched is False

def test_get_variables():
    variables = Router.get_variables('/test/123', '/test/{id}')
    assert variables == {'id': '123'}

def test_requires_auth_explicit_secure():
    route = {'secure': True}
    assert Router.requires_auth(route, Constant.TINA4_GET, True) is True
    assert Router.requires_auth(route, Constant.TINA4_GET, False) is True

def test_requires_auth_write_method_not_validated():
    route = {}
    assert Router.requires_auth(route, Constant.TINA4_POST, False) is True

def test_requires_auth_write_method_validated():
    route = {}
    assert Router.requires_auth(route, Constant.TINA4_POST, True) is False

def test_requires_auth_get_method():
    route = {}
    assert Router.requires_auth(route, Constant.TINA4_GET, False) is False

def test_clean_url():
    assert Router.clean_url('//test//abc') == '/test/abc'

# Test decorators
def test_get_decorator_single_path():
    @get('/test')
    def callback():
        pass

    assert callback in tina4_python.tina4_routes
    entry = tina4_python.tina4_routes[callback]
    assert entry['routes'] == ['/test']
    assert entry['methods'] == [Constant.TINA4_GET]

def test_get_decorator_multiple_paths_list():
    @get(['/test1', '/test2'])
    def callback():
        pass

    entry = tina4_python.tina4_routes[callback]
    assert set(entry['routes']) == {'/test1', '/test2'}
    assert entry['methods'] == [Constant.TINA4_GET]

def test_get_decorator_pipe_separated():
    @get('/test1|/test2')
    def callback():
        pass

    entry = tina4_python.tina4_routes[callback]
    assert set(entry['routes']) == {'/test1', '/test2'}
    assert entry['methods'] == [Constant.TINA4_GET]

def test_post_decorator():
    @post('/test')
    def callback():
        pass

    entry = tina4_python.tina4_routes[callback]
    assert entry['routes'] == ['/test']
    assert entry['methods'] == [Constant.TINA4_POST]
    assert entry['secure'] is True

def test_cached_decorator():
    def callback():
        pass

    cached(True, 120)(callback)
    assert 'cache' in tina4_python.tina4_routes[callback]
    assert tina4_python.tina4_routes[callback]['cache'] == {'cached': True, 'max_age': 120}

def test_middleware_decorator():
    class TestMiddleware:
        pass

    def callback():
        pass

    middleware(TestMiddleware, ['method1'])(callback)
    assert 'middleware' in tina4_python.tina4_routes[callback]
    assert tina4_python.tina4_routes[callback]['middleware'] == {'class': TestMiddleware, 'methods': ['method1']}

def test_secured_decorator():
    def callback():
        pass

    secured()(callback)
    assert tina4_python.tina4_routes[callback]['secure'] is True

def test_noauth_decorator():
    def callback():
        pass

    noauth()(callback)
    assert tina4_python.tina4_routes[callback]['noauth'] is True

def test_wsdl_decorator():
    @wsdl('/test')
    def callback():
        pass

    entry = tina4_python.tina4_routes[callback]
    assert set(entry['routes']) == {'/test'}
    assert set(entry['methods']) == {Constant.TINA4_GET, Constant.TINA4_POST}

# For async parts, we might need more setup, but since get_result is complex, perhaps integration tests or mock deeper
# For now, focus on the routing addition and matching

@pytest.mark.asyncio
async def test_resolve_no_route():
    # Mock necessary parts
    with patch('tina4_python.Template.Template.render_twig_template') as mock_render:
        mock_render.return_value = "404 Not Found"
        request = {"params": {}, "body": {}}
        headers = {}
        session = {}
        result = await Router.resolve(Constant.TINA4_GET, '/nonexistent', request, headers, session)
        assert result.http_code == Constant.HTTP_NOT_FOUND
        assert result.content == "404 Not Found"



# Reset Router state before each test
@pytest.fixture(autouse=True)
def reset_router():
    Router.variables = {}
    # Clear any previously added routes (in case of side effects)
    from tina4_python import tina4_routes
    tina4_routes.clear()


def test_exact_match():
    assert Router.match("/hello", "/hello") is True
    assert Router.variables == {}


def test_exact_match_with_trailing_slash():
    assert Router.match("/hello/", "/hello/") is True
    assert Router.match("/hello", "/hello/") is True
    assert Router.match("/hello/", "/hello") is True


def test_no_match_different_length():
    assert Router.match("/test/123", "/test") is False
    assert Router.match("/test", "/test/123") is False
    assert Router.match("/a/b/c", "/a/b") is False


def test_no_match_wrong_segment():
    assert Router.match("/users/123", "/posts/123") is False
    assert Router.match("/admin", "/user") is False


def test_basic_param_str():
    assert Router.match("/user/john", "/user/{username}") is True
    assert Router.variables == {"username": "john"}

    assert Router.match("/user/alice", "/user/{name}") is True
    assert Router.variables == {"name": "alice"}


def test_explicit_str_converter():
    assert Router.match("/user/jane", "/user/{username:str}") is True
    assert Router.variables == {"username": "jane"}


def test_int_converter_success():
    assert Router.match("/user/42", "/user/{id:int}") is True
    assert Router.variables == {"id": 42}
    assert isinstance(Router.variables["id"], int)


def test_int_converter_failure():
    assert Router.match("/user/abc", "/user/{id:int}") is False
    assert Router.match("/user/12.5", "/user/{id:int}") is False
    assert Router.match("/user/-5", "/user/{id:int}") is True  # negative OK
    assert Router.variables.get("id") == -5


def test_float_converter():
    assert Router.match("/price/19.99", "/price/{amount:float}") is True
    assert Router.variables == {"amount": 19.99}
    assert isinstance(Router.variables["amount"], float)

    assert Router.match("/price/0.01", "/price/{amount:float}") is True
    assert Router.match("/price/-5.5", "/price/{amount:float}") is True
    assert Router.variables["amount"] == -5.5

    assert Router.match("/price/hello", "/price/{amount:float}") is False


def test_path_greedy_converter():
    assert Router.match("/files/images/avatar.png", "/files/{filepath:path}") is True
    assert Router.variables == {"filepath": "images/avatar.png"}

    assert Router.match("/files/a/b/c/d.txt", "/files/{file:path}") is True
    assert Router.variables == {"file": "a/b/c/d.txt"}

    assert Router.match("/files/", "/files/{path:path}") is True
    assert Router.variables == {"path": ""}  # or "/" — both acceptable


def test_path_must_be_last():
    # {path:path} not allowed in middle
    assert Router.match("/api/files/temp/data.txt", "/api/files/{path:path}/data.txt") is False
    assert Router.match("/api/files/data.txt/temp", "/api/files/data.txt/{path:path}") is True


def test_mixed_params():
    assert Router.match("/user/123/posts/456", "/user/{id:int}/posts/{post_id}") is True
    assert Router.variables == {"id": 123, "post_id": "456"}

    assert Router.match("/user/123/posts/abc", "/user/{id:int}/posts/{post_id:int}") is False


def test_multiple_routes_same_callback():
    # Simulate adding two routes for same handler
    Router.add(Constant.TINA4_GET, "/profile", lambda: None)
    Router.add(Constant.TINA4_GET, "/user/{id:int}", lambda: None)

    assert Router.match("/profile", "/profile") is True
    assert Router.match("/user/99", "/user/{id:int}") is True
    assert Router.variables == {"id": 99}


def test_query_string_ignored_in_matching():
    assert Router.match("/search?q=python", "/search") is True
    assert Router.match("/user/55?name=John", "/user/{id:int}") is True
    assert Router.variables == {"id": 55}


def test_empty_path_root():
    assert Router.match("/", "/") is True
    assert Router.match("", "/") is True
    assert Router.match("/ ", "/") is True  # cleaned


def test_leading_trailing_slashes_normalized():
    assert Router.match("  /hello/world  ", "/hello/world") is True
    assert Router.match("/hello/world/", "/hello/world") is True


def test_no_false_positive_on_partial_match():
    assert Router.match("/testing", "/test") is False
    assert Router.match("/test", "/testing") is False
    assert Router.match("/api/v1/users", "/api/v1/user") is False  # note: plural vs singular


def test_path_param_with_slashes_and_type():
    assert Router.match("/download/2025/12/report.pdf", "/download/{year:int}/{month:int}/{file:path}") is True
    assert Router.variables == {
        "year": 2025,
        "month": 12,
        "file": "report.pdf"
    }


def test_complex_real_world_example():
    assert Router.match("/api/v1/users/123/orders/987/items", "/api/v1/users/{id:int}/orders/{order_id:int}/items") is True
    assert Router.variables == {"id": 123, "order_id": 987}

    assert Router.match("/static/css/app.min.css", "/static/{filepath:path}") is True
    assert Router.variables["filepath"] == "css/app.min.css"


def test_converter_case_insensitive():
    assert Router.match("/age/30", "/age/{years:Int}") is True
    assert Router.variables == {"years": 30}

    assert Router.match("/price/9.99", "/price/{cost:Float}") is True
    assert Router.variables["cost"] == 9.99



def test_stacked_get_and_post_on_same_function():
    """Test that @get + @post on the same function registers both methods"""
    from tina4_python import get, post

    async def users_endpoint(request, response):
        return response({"method": request.method, "message": "Handled"})

    # Stack decorators — this is the key feature!
    decorated = get("/users")(users_endpoint)
    decorated = post("/users")(decorated)   # Stack second decorator

    # Or more pythonic: @get("/users") @post("/users")
    # But we do it step-by-step to test stacking

    # Verify the route was registered once, with both methods
    assert users_endpoint in tina4_python.tina4_routes
    route_data = tina4_python.tina4_routes[users_endpoint]

    assert "/users" in route_data["routes"]
    assert Constant.TINA4_GET in route_data["methods"]
    assert Constant.TINA4_POST in route_data["methods"]
    assert len(route_data["methods"]) == 2
    assert route_data["callback"] is users_endpoint


def test_stacked_multiple_methods_with_different_paths():
    """Allow same function on multiple paths with different methods"""
    from tina4_python import get, post, put

    async def multi_handler(request, response):
        return response("OK")

    # Stack on different paths
    get("/api/v1/items")(multi_handler)
    post("/api/v1/items")(multi_handler)
    put("/api/v1/items/{id:int}")(multi_handler)

    route_data = tina4_python.tina4_routes[multi_handler]

    assert set(route_data["routes"]) == {"/api/v1/items", "/api/v1/items/{id:int}"}
    assert set(route_data["methods"]) == {Constant.TINA4_GET, Constant.TINA4_POST, Constant.TINA4_PUT}


def test_stacked_decorators_in_reverse_order():
    """Order of stacking shouldn't matter"""
    from tina4_python import get, post

    async def handler(request, response):
        return response("Reverse order works too")

    # Apply POST first, then GET
    func = post("/test")(handler)
    func = get("/test")(func)

    route_data = tina4_python.tina4_routes[handler]
    assert Constant.TINA4_GET in route_data["methods"]
    assert Constant.TINA4_POST in route_data["methods"]
    assert "/test" in route_data["routes"]


def test_stacked_decorators_with_type_converters():
    """Stacking works even with {id:int} style routes"""
    from tina4_python import get, delete

    async def user_detail(id: int, request, response):
        return response({"id": id, "deleted": request.method == "DELETE"})

    get("/users/{id:int}")(user_detail)
    delete("/users/{id:int}")(user_detail)

    route_data = tina4_python.tina4_routes[user_detail]

    assert "/users/{id:int}" in route_data["routes"]
    assert Constant.TINA4_GET in route_data["methods"]
    assert Constant.TINA4_DELETE in route_data["methods"]
    assert "id" in route_data.get("params", [])


def test_actual_request_matching_after_stacking():
    """Real matching works after stacking"""
    from tina4_python import get, post

    async def endpoint(request, response):
        return response({"you_called": request.method})

    get("/stacked")(endpoint)
    post("/stacked")(endpoint)

    # Test GET
    assert Router.match("/stacked", "/stacked") is True
    assert Router.match("/stacked/", "/stacked") is True

    # Test POST (same route, different method — still matches path)
    assert Router.match("/stacked", "/stacked") is True

    # Variables should be empty (no params)
    assert Router.variables == {}


def test_no_duplicate_route_error_when_stacking_same_path():
    """Stacking same path + method should be blocked (duplicate protection)"""
    from tina4_python import get

    async def dup(request, response):
        return response("oops")

    get("/dup")(dup)
    result = get("/dup")(dup)  # Second time → should warn but not crash

    # Should not raise, and route should still exist
    assert dup in tina4_python.tina4_routes
    assert "/dup" in tina4_python.tina4_routes[dup]["routes"]
    assert len(tina4_python.tina4_routes[dup]["methods"]) == 1  # Only one GET


def test_pipe_separated_paths_with_stacking():
    """Stacking works with | syntax too"""
    from tina4_python import get, post

    async def multi_path(request, response):
        return response("multi")

    # Using pipe syntax + stacking
    get("/a|/b|/c")(multi_path)
    post("/a|/b|/c")(multi_path)

    route_data = tina4_python.tina4_routes[multi_path]
    assert set(route_data["routes"]) == {"/a", "/b", "/c"}
    assert Constant.TINA4_GET in route_data["methods"]
    assert Constant.TINA4_POST in route_data["methods"]