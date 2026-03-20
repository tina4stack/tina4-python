"""Tests for HTMLElement builder."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tina4_python.HtmlElement import HTMLElement, _make_element, add_html_helpers


# --- Basic tags ---

def test_basic_div():
    el = HTMLElement("div")
    assert str(el) == "<div></div>"


def test_div_with_text():
    el = HTMLElement("div", children=["Hello"])
    assert str(el) == "<div>Hello</div>"


def test_paragraph_with_text():
    el = HTMLElement("p", children=["Some text"])
    assert str(el) == "<p>Some text</p>"


def test_tag_lowercased():
    el = HTMLElement("DIV")
    assert str(el) == "<div></div>"


# --- Void tags ---

def test_br_void():
    el = HTMLElement("br")
    assert str(el) == "<br>"


def test_img_void_with_attrs():
    el = HTMLElement("img", {"src": "pic.jpg", "alt": "A picture"})
    assert str(el) == '<img src="pic.jpg" alt="A picture">'


def test_input_void():
    el = HTMLElement("input", {"type": "text", "name": "q"})
    assert str(el) == '<input type="text" name="q">'


def test_hr_void():
    el = HTMLElement("hr")
    assert str(el) == "<hr>"


# --- Attributes ---

def test_attributes_rendered():
    el = HTMLElement("a", {"href": "/page", "class": "link"}, ["Click"])
    assert str(el) == '<a href="/page" class="link">Click</a>'


def test_boolean_true_attribute():
    el = HTMLElement("input", {"type": "checkbox", "checked": True})
    assert str(el) == '<input type="checkbox" checked>'


def test_boolean_false_attribute_omitted():
    el = HTMLElement("input", {"type": "text", "disabled": False})
    assert str(el) == '<input type="text">'


def test_none_attribute_omitted():
    el = HTMLElement("div", {"id": "x", "data-foo": None})
    assert str(el) == '<div id="x"></div>'


# --- Escaping ---

def test_attribute_value_escaped():
    el = HTMLElement("div", {"title": 'He said "hello" & goodbye'})
    assert '&quot;' in str(el)
    assert '&amp;' in str(el)


def test_text_child_escaped():
    el = HTMLElement("p", children=["<script>alert(1)</script>"])
    result = str(el)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_html_element_child_not_escaped():
    inner = HTMLElement("em", children=["bold"])
    outer = HTMLElement("p", children=[inner])
    assert str(outer) == "<p><em>bold</em></p>"


# --- Nested elements ---

def test_nested_elements():
    li1 = HTMLElement("li", children=["Item 1"])
    li2 = HTMLElement("li", children=["Item 2"])
    ul = HTMLElement("ul", children=[li1, li2])
    assert str(ul) == "<ul><li>Item 1</li><li>Item 2</li></ul>"


def test_deeply_nested():
    span = HTMLElement("span", children=["deep"])
    p = HTMLElement("p", children=[span])
    div = HTMLElement("div", {"class": "wrap"}, [p])
    assert str(div) == '<div class="wrap"><p><span>deep</span></p></div>'


# --- Builder pattern (__call__) ---

def test_builder_append_children():
    div = HTMLElement("div")
    result = div("Hello", " ", "World")
    assert str(result) == "<div>Hello World</div>"


def test_builder_returns_new_instance():
    original = HTMLElement("div", children=["A"])
    built = original("B")
    assert str(original) == "<div>A</div>"
    assert str(built) == "<div>AB</div>"


def test_builder_with_list_children():
    items = [HTMLElement("li", children=["a"]), HTMLElement("li", children=["b"])]
    ul = HTMLElement("ul")(items)
    assert str(ul) == "<ul><li>a</li><li>b</li></ul>"


def test_builder_with_dict_merges_attrs():
    div = HTMLElement("div", {"class": "a"})
    result = div({"id": "x"}, "text")
    assert str(result) == '<div class="a" id="x">text</div>'


# --- _make_element smart constructor ---

def test_make_element_attrs_and_children():
    el = _make_element("div", {"class": "card"}, "Hello")
    assert str(el) == '<div class="card">Hello</div>'


def test_make_element_no_attrs():
    el = _make_element("p", "Just text")
    assert str(el) == "<p>Just text</p>"


def test_make_element_list_children():
    items = [HTMLElement("li", children=["x"])]
    el = _make_element("ul", items)
    assert str(el) == "<ul><li>x</li></ul>"


# --- Helper functions ---

def test_add_html_helpers():
    ns = {}
    add_html_helpers(ns)
    assert "_div" in ns
    assert "_p" in ns
    assert "_a" in ns
    assert "_img" in ns
    assert "_br" in ns
    assert "_table" in ns


def test_helper_creates_element():
    ns = {}
    add_html_helpers(ns)
    el = ns["_div"]({"class": "test"}, "content")
    assert str(el) == '<div class="test">content</div>'


def test_helper_void_tag():
    ns = {}
    add_html_helpers(ns)
    el = ns["_br"]()
    assert str(el) == "<br>"


def test_helper_nested():
    ns = {}
    add_html_helpers(ns)
    el = ns["_div"](ns["_p"]("inner"))
    assert str(el) == "<div><p>inner</p></div>"


# --- repr ---

def test_repr_same_as_str():
    el = HTMLElement("div", {"id": "r"}, ["ok"])
    assert repr(el) == str(el)
