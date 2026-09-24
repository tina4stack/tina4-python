"""Frond globals contract — ADR-0085.

A bare zero-argument callable global is invoked and its RETURN VALUE is used for
both ``{{ g }}`` output and ``{% if g %}`` conditions. Explicit ``g()`` still
works and never double-calls. A non-callable global is unchanged, a global that
returns a callable is called once (not twice), and an unregistered ``nope()`` is
falsy rather than an error.

Node is the reference implementation; these cases mirror
tina4-nodejs/test/frondGlobalsContract.test.ts against the shared fixture
tina4-documentation/plan/v3/fixtures/frond_globals_contract.json.

No mocks: the closures are real and Frond renders real template source in memory.
"""
from tina4_python.frond import Frond


def _frond():
    Frond.clear_registry()
    return Frond()


def test_zero_arg_global_closure_returning_false_is_falsy_in_if():
    """zero arg global closure returning false is falsy in if"""
    f = _frond()
    f.add_global("admin_only", lambda: False)
    assert f.render_string("{% if admin_only %}Y{% else %}N{% endif %}") == "N"


def test_zero_arg_global_closure_returning_true_is_truthy_in_if():
    """zero arg global closure returning true is truthy in if"""
    f = _frond()
    f.add_global("admin_only", lambda: True)
    assert f.render_string("{% if admin_only %}Y{% else %}N{% endif %}") == "Y"


def test_zero_arg_global_closure_prints_its_return_value():
    """zero arg global closure prints its return value"""
    f = _frond()
    f.add_global("greeting", lambda: "hello")
    assert f.render_string("{{ greeting }}") == "hello"


def test_explicit_call_syntax_still_works():
    """explicit call syntax still works"""
    f = _frond()
    f.add_global("admin_only", lambda: False)
    assert f.render_string("{% if admin_only() %}Y{% else %}N{% endif %}") == "N"


def test_non_callable_global_is_unchanged():
    """non callable global is unchanged"""
    f = _frond()
    f.add_global("site_name", "Tina4")
    assert f.render_string("{{ site_name }}") == "Tina4"


def test_global_returning_a_callable_is_not_double_called():
    """global returning a callable is not double called"""
    f = _frond()
    calls = {"outer": 0, "inner": 0}

    def outer():
        calls["outer"] += 1

        def inner():
            calls["inner"] += 1
            return "inner"

        return inner

    f.add_global("outer", outer)
    # A bare reference calls the global ONCE and yields the inner function; the
    # inner function must NOT be invoked (no double-call).
    f.render_string("{% if outer %}Y{% endif %}")
    assert calls["outer"] == 1
    assert calls["inner"] == 0


def test_unregistered_function_call_is_falsy():
    """unregistered function call is falsy"""
    f = _frond()
    assert f.render_string("{% if nope() %}Y{% else %}N{% endif %}") == "N"
    assert f.render_string("{{ nope() }}") == ""
