#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

from tina4_python.HtmlElement import HTMLElement, add_html_helpers


# --- Basic rendering ---

def test_default_div():
    el = HTMLElement()
    assert str(el) == "<div></div>"


def test_custom_tag():
    el = HTMLElement("span")
    assert str(el) == "<span></span>"


def test_tag_with_content():
    el = HTMLElement("p", content="Hello")
    assert str(el) == "<p>Hello</p>"


def test_tag_with_list_content():
    el = HTMLElement("ul", content=["<li>A</li>", "<li>B</li>"])
    assert str(el) == "<ul><li>A</li><li>B</li></ul>"


def test_tag_with_attributes():
    el = HTMLElement("a", {"href": "/home", "class": "link"})
    result = str(el)
    assert 'href="/home"' in result
    assert 'class="link"' in result
    assert result.startswith("<a ")


def test_tag_with_content_and_attributes():
    el = HTMLElement("a", {"href": "/"}, "Home")
    assert str(el) == '<a href="/">Home</a>'


# --- Void tags ---

def test_void_tag_br():
    el = HTMLElement("br")
    assert str(el) == "<br>"


def test_void_tag_img():
    el = HTMLElement("img", {"src": "logo.png", "alt": "Logo"})
    result = str(el)
    assert result.startswith("<img ")
    assert 'src="logo.png"' in result
    assert not result.endswith("</img>")


def test_void_tag_input():
    el = HTMLElement("input", {"type": "text", "name": "email"})
    result = str(el)
    assert 'type="text"' in result
    assert not result.endswith("</input>")


def test_void_tag_hr():
    assert str(HTMLElement("hr")) == "<hr>"


# --- Attribute rendering ---

def test_boolean_attribute_true():
    el = HTMLElement("input", {"disabled": True, "type": "text"})
    result = str(el)
    assert "disabled" in result
    assert 'disabled="' not in result  # bare attribute


def test_boolean_attribute_false():
    el = HTMLElement("input", {"disabled": False, "type": "text"})
    result = str(el)
    assert "disabled" not in result


def test_none_attribute_excluded():
    el = HTMLElement("div", {"id": None, "class": "box"})
    result = str(el)
    assert "id" not in result
    assert 'class="box"' in result


def test_empty_attributes():
    el = HTMLElement("div", {})
    assert str(el) == "<div></div>"


# --- Escaping ---

def test_escape_html():
    assert HTMLElement.escape('<script>alert("xss")</script>') == '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'


def test_escape_ampersand():
    assert HTMLElement.escape("A & B") == "A &amp; B"


def test_escape_single_quotes():
    assert HTMLElement.escape("it's") == "it&#39;s"


def test_attribute_value_escaped():
    el = HTMLElement("div", {"title": 'Say "hello"'})
    assert '&quot;' in str(el)


# --- add() method ---

def test_add_content():
    el = HTMLElement("div")
    el.add("Hello")
    assert str(el) == "<div>Hello</div>"


def test_add_multiple():
    el = HTMLElement("div")
    el.add("A", "B", "C")
    assert str(el) == "<div>ABC</div>"


def test_add_returns_self():
    el = HTMLElement("div")
    result = el.add("test")
    assert result is el


def test_add_none_ignored():
    el = HTMLElement("div")
    el.add(None, "text", None)
    assert str(el) == "<div>text</div>"


def test_add_nested_elements():
    inner = HTMLElement("span", content="inner")
    outer = HTMLElement("div")
    outer.add(inner)
    assert str(outer) == "<div><span>inner</span></div>"


# --- __call__ ---

def test_call_adds_content():
    el = HTMLElement("div")
    el("Hello")
    assert str(el) == "<div>Hello</div>"


def test_call_updates_attributes():
    el = HTMLElement("div")
    el(**{"id": "main"})
    assert 'id="main"' in str(el)


# --- Operators ---

def test_add_operator():
    el = HTMLElement("span", content="A")
    result = el + " B"
    assert result == "<span>A</span> B"


def test_radd_operator():
    el = HTMLElement("span", content="B")
    result = "A " + el
    assert result == "A <span>B</span>"


# --- repr ---

def test_repr():
    el = HTMLElement("p", content="text")
    assert repr(el) == "<p>text</p>"


# --- add_html_helpers ---

def test_add_html_helpers():
    g = {}
    add_html_helpers(g)
    assert "_div" in g
    assert "_p" in g
    assert "_a" in g
    assert "_input" in g
    assert "_table" in g


def test_helper_creates_element():
    g = {}
    add_html_helpers(g)
    div = g["_div"]("Hello")
    assert str(div) == "<div>Hello</div>"


def test_helper_with_attrs_and_content():
    g = {}
    add_html_helpers(g)
    a = g["_a"]({"href": "/home"}, "Home")
    assert str(a) == '<a href="/home">Home</a>'


def test_helper_void_tag():
    g = {}
    add_html_helpers(g)
    br = g["_br"]()
    assert str(br) == "<br>"


def test_helper_nested():
    g = {}
    add_html_helpers(g)
    ul = g["_ul"](
        g["_li"]("Item 1"),
        g["_li"]("Item 2")
    )
    assert str(ul) == "<ul><li>Item 1</li><li>Item 2</li></ul>"


def test_helper_list_content():
    g = {}
    add_html_helpers(g)
    items = [g["_li"]("A"), g["_li"]("B")]
    ul = g["_ul"](items)
    assert str(ul) == "<ul><li>A</li><li>B</li></ul>"
