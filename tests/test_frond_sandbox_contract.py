"""Sandbox contract: a sandbox denies by revoking capability, not by skipping a step.

Audit feature 38 (plan/v3/features/038-sandboxing.md), P1.

The documented purpose of the sandbox is rendering templates written by someone
you do not trust (``tina4-nodejs/CLAUDE.md:872``: "restrict capabilities for
user-supplied templates"). Two ways an untrusted template could defeat it:

P1  ``{{ x|raw }}`` and ``{{ x|safe }}`` with ``raw``/``safe`` DENIED by the
    filter allow-list still produced UNESCAPED output. The escaping decision read
    the filter NAME out of the parsed source (``engine.py:2278``) instead of
    asking whether the filter was permitted to run, so skipping the filter left
    the value marked safe anyway. Denying raw produced byte-identical output to
    allowing it - the allow-list entry that governs XSS escaping was inert.

P1b ``{% autoescape false %}`` bypassed the TAG allow-list, in all four
    frameworks, because the tag gate is a per-tag-name conditional at a hardcoded
    set of call sites rather than one check where a tag is resolved.

These are pure string rendering. No I/O, no dependency, no doubles.
"""

import pytest

from tina4_python.frond import Frond

XSS = "<script>alert(1)</script>"
ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


def denied():
    """A sandbox whose filter allow-list does NOT include raw or safe."""
    return Frond().sandbox(
        allowed_filters=["upper"], allowed_tags=["if"], allowed_vars=["x"]
    )


def allowed():
    """The same sandbox, but raw IS on the allow-list."""
    return Frond().sandbox(
        allowed_filters=["upper", "raw", "safe"], allowed_tags=["if"], allowed_vars=["x"]
    )


# --- pair 1: raw is revocable ---------------------------------------------

def test_denying_raw_escapes_the_value():
    assert denied().render_string("{{ x|raw }}", {"x": XSS}) == ESCAPED


def test_negative_a_denied_raw_filter_never_produces_unescaped_output():
    """THE P1 reproduction."""
    out = denied().render_string("{{ x|raw }}", {"x": XSS})
    assert "<script>" not in out, (
        f"a DENIED raw filter produced live markup: {out!r}. The sandbox's whole "
        f"purpose is rendering untrusted templates; this is an XSS hole."
    )


# --- pair 2: safe is revocable -------------------------------------------

def test_denying_safe_escapes_the_value():
    assert denied().render_string("{{ x|safe }}", {"x": XSS}) == ESCAPED


def test_negative_a_denied_safe_filter_never_produces_unescaped_output():
    out = denied().render_string("{{ x|safe }}", {"x": XSS})
    assert "<script>" not in out, f"a DENIED safe filter produced live markup: {out!r}"


# --- pair 3: deny must differ from allow ---------------------------------

def test_allowing_raw_renders_verbatim_and_denying_it_does_not():
    assert allowed().render_string("{{ x|raw }}", {"x": XSS}) == XSS
    assert denied().render_string("{{ x|raw }}", {"x": XSS}) == ESCAPED


def test_negative_denying_a_filter_never_produces_the_same_output_as_allowing_it():
    """The finding in one assertion: the two were byte-identical."""
    assert denied().render_string("{{ x|raw }}", {"x": XSS}) != allowed().render_string(
        "{{ x|raw }}", {"x": XSS}
    ), "denying raw and allowing raw produced identical output - the gate is inert"


# --- pair 4: the tag gate cannot be bypassed (P1b) -----------------------

def test_a_denied_autoescape_tag_does_not_disable_escaping():
    out = denied().render_string(
        "{% autoescape false %}{{ x }}{% endautoescape %}", {"x": XSS}
    )
    assert "<script>" not in out, (
        f"{{% autoescape false %}} disabled escaping despite not being on the tag "
        f"allow-list: {out!r}"
    )


def test_negative_no_tag_can_disable_escaping_inside_a_sandbox():
    for tpl in (
        "{% autoescape false %}{{ x }}{% endautoescape %}",
        "{% autoescape off %}{{ x }}{% endautoescape %}",
    ):
        out = denied().render_string(tpl, {"x": XSS})
        assert "<script>" not in out, f"{tpl} disabled escaping: {out!r}"


# --- pair 5: escape is revocable too ------------------------------------
# Python is immune to this BY CONSTRUCTION and these tests exist to keep it that
# way. The ``escape`` filter returns a ``SafeString`` (engine.py), so escaping is
# marked by a value the filter produces only when it actually RUNS -- deny it and
# no SafeString exists, so the value is still auto-escaped. Ruby does the same;
# PHP prepends a RAW_MARKER. Node instead set a flag from the filter NAME and
# therefore DID emit live markup for a denied ``escape`` (fixed in 1eb1c4a).
# Anyone who later "simplifies" escape to return a plain str reopens that hole in
# this framework, so pin it.

def test_negative_a_denied_escape_filter_never_produces_unescaped_output():
    out = denied().render_string("{{ x|escape }}", {"x": XSS})
    assert "<script>" not in out, (
        f"a DENIED escape filter produced live markup: {out!r}. Escaping must be "
        f"conferred by RUNNING the filter, never by its name."
    )


def test_negative_a_denied_e_filter_never_produces_unescaped_output():
    out = denied().render_string("{{ x|e }}", {"x": XSS})
    assert "<script>" not in out, f"a DENIED e filter produced live markup: {out!r}"


def test_an_allowed_escape_filter_escapes_exactly_once():
    """The guard must not cost the allowed path."""
    e = Frond().sandbox(allowed_filters=["escape"], allowed_tags=["if"], allowed_vars=["x"])
    assert e.render_string("{{ x|escape }}", {"x": XSS}) == ESCAPED


# --- pair 6: what must NOT change ---------------------------------------
# The ordinary gates were byte-identical across all four frameworks and are
# correct. Guard them so the fix cannot alter them.

def test_an_allowed_filter_still_runs_and_a_denied_one_is_skipped():
    e = Frond().sandbox(allowed_filters=["upper"], allowed_tags=["if"], allowed_vars=["v"])
    assert e.render_string("{{ v|upper }}", {"v": "MiXeD"}) == "MIXED"
    assert e.render_string("{{ v|lower }}", {"v": "MiXeD"}) == "MiXeD"


def test_a_denied_variable_still_renders_empty():
    e = Frond().sandbox(allowed_filters=["upper"], allowed_tags=["if"], allowed_vars=["ok"])
    assert e.render_string("{{ secret }}", {"ok": "y", "secret": "LEAKED"}) == ""


def test_escaping_outside_a_sandbox_is_unchanged():
    """raw/safe must keep working normally when no sandbox is active."""
    plain = Frond()
    assert plain.render_string("{{ x }}", {"x": XSS}) == ESCAPED
    assert plain.render_string("{{ x|raw }}", {"x": XSS}) == XSS
    assert plain.render_string("{{ x|safe }}", {"x": XSS}) == XSS


def test_unsandbox_restores_raw():
    e = denied()
    assert e.render_string("{{ x|raw }}", {"x": XSS}) == ESCAPED
    e.unsandbox()
    assert e.render_string("{{ x|raw }}", {"x": XSS}) == XSS


# --- empty vs null allow-list -------------------------------------------
# None means "allow everything". An EMPTY list must not silently mean the same,
# or a caller who computes an allow-list and gets nothing back opens the sandbox.

def test_a_null_allow_list_permits_everything():
    e = Frond().sandbox(allowed_filters=None, allowed_tags=None, allowed_vars=None)
    assert e.render_string("{{ x|raw }}", {"x": XSS}) == XSS


def test_negative_an_empty_allow_list_does_not_permit_everything():
    e = Frond().sandbox(allowed_filters=[], allowed_tags=[], allowed_vars=["x"])
    out = e.render_string("{{ x|raw }}", {"x": XSS})
    assert "<script>" not in out, (
        f"an EMPTY filter allow-list behaved like None (allow all): {out!r}"
    )
