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
