#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""HTML element builder for constructing HTML markup programmatically in Python.

This module provides two main APIs:

1. **HTMLElement** -- a builder-pattern class that represents a single HTML tag
   with attributes and nested content.  Elements are composable: you can nest
   them, concatenate them with ``+``, and call ``str()`` to get the final HTML.

2. **add_html_helpers()** -- a convenience function that injects shorthand
   factory functions (``_div``, ``_p``, ``_a``, etc.) into a given globals
   dict so you can write HTML in a concise, declarative style.

Quick start::

    from tina4_python.HtmlElement import HTMLElement, add_html_helpers

    # Low-level API
    el = HTMLElement("a", {"href": "/home"}, ["Home"])
    print(el)  # <a href="/home">Home</a>

    # Builder / callable style
    el = HTMLElement("div")(HTMLElement("p")("Hello"))
    print(el)  # <div><p>Hello</p></div>

    # Helper-function style (after calling add_html_helpers)
    add_html_helpers(globals())
    print(_div({"class": "card"}, _p("Hello")))
    # <div class="card"><p>Hello</p></div>
"""

__all__ = ["HTMLElement", "add_html_helpers"]


class HTMLElement:
    """Builder-pattern HTML element that renders to an HTML string.

    Each instance represents a single HTML tag with optional attributes and
    child content.  Content can be plain strings, other ``HTMLElement``
    instances, or any object whose ``__str__`` produces valid markup.

    The class supports a **callable/builder** style: calling an element adds
    content and/or attributes, then returns ``self`` so calls can be chained::

        HTMLElement("div")(HTMLElement("p")("Hello"), class_="card")

    **Void (self-closing) tags** such as ``<br>``, ``<img>``, and ``<input>``
    are rendered without a closing tag and ignore any child content.  The full
    set is listed in :attr:`VOID_TAGS`.

    Concatenation with ``+`` joins the HTML output of both operands, making it
    easy to compose sibling elements::

        HTMLElement("p")("A") + HTMLElement("p")("B")
        # '<p>A</p><p>B</p>'

    Attributes:
        VOID_TAGS: Set of HTML tag names that must not have a closing tag.
        tag_name: Lowercase tag name (e.g. ``"div"``).
        attributes: Dict of attribute key/value pairs.
        content: List of child nodes (strings or ``HTMLElement`` instances).
    """

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "keygen", "link", "meta", "param", "source", "track", "wbr"
    }

    def __init__(self, tag_name="div", attributes=None, content=None):
        """Create an HTML element.

        Args:
            tag_name: HTML tag name (e.g. ``"div"``, ``"img"``).  Defaults to
                ``"div"``.  The value is lowercased and stripped automatically.
            attributes: Optional dict (or iterable of key-value pairs) of HTML
                attributes.  Boolean ``True`` renders a valueless attribute
                (e.g. ``disabled``); ``False``/``None`` values are omitted.
            content: Initial child content -- a single item, or a list/tuple
                of items.  Items can be strings, ``HTMLElement`` instances, or
                any object with a useful ``__str__``.
        """
        self.tag_name = str(tag_name or "div").lower().strip() or "div"

        if attributes is None:
            self.attributes = {}
        elif isinstance(attributes, dict):
            self.attributes = dict(attributes)
        else:
            try:
                self.attributes = dict(attributes)  # for kwargs-like, e.g. [('class','btn')]
            except (ValueError, TypeError):
                self.attributes = {}  # fallback

        self.content = []
        if content is not None:
            if isinstance(content, (list, tuple)):
                self.content.extend(content)
            else:
                self.content.append(content)

    @staticmethod
    def escape(text):
        """Escape a value for safe inclusion in HTML attribute values.

        Replaces ``&``, ``<``, ``>``, ``"``, and ``'`` with their HTML entity
        equivalents.

        Args:
            text: The value to escape.  Non-string values are converted via
                ``str()`` first.

        Returns:
            The escaped string.
        """
        if not isinstance(text, str):
            text = str(text)
        return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

    def add(self, *items):
        """Append one or more child items to this element's content.

        ``None`` values are silently skipped.

        Args:
            *items: Child nodes to append (strings, ``HTMLElement`` instances,
                or any object with ``__str__``).

        Returns:
            ``self``, enabling method chaining.
        """
        for item in items:
            if item is not None:
                self.content.append(item)
        return self

    def render_attributes(self):
        """Serialize ``self.attributes`` into an HTML attribute string.

        Boolean ``True`` values produce valueless attributes (e.g.
        ``disabled``).  ``False`` and ``None`` values are omitted entirely.
        All other values are escaped and double-quoted.

        Returns:
            A string like ``' class="btn" disabled'`` (leading space included),
            or ``""`` when there are no attributes.
        """
        if not self.attributes:
            return ""
        attrs = []
        for key, val in self.attributes.items():
            key = str(key).lower().strip()
            if val is True:
                attrs.append(key)
            elif val in (False, None):
                continue
            else:
                attrs.append(f'{key}="{self.escape(str(val))}"')
        return " " + " ".join(attrs) if attrs else ""

    def __str__(self):
        """Render the element to an HTML string.

        Void tags (e.g. ``<br>``, ``<img>``) are rendered without a closing
        tag.  If ``tag_name`` is falsy, only the concatenated children are
        returned (useful as a fragment container).

        Returns:
            The complete HTML markup for this element and all its descendants.
        """
        if not self.tag_name:
            return "".join(str(c) for c in self.content if c is not None)

        open_tag = f"<{self.tag_name}{self.render_attributes()}>"
        if self.tag_name in self.VOID_TAGS:
            return open_tag

        content_str = "".join(str(c) for c in self.content if c is not None)
        return f"{open_tag}{content_str}</{self.tag_name}>"

    def __call__(self, *content, **attributes):
        """Add content and/or attributes by calling the element like a function.

        This enables the builder pattern::

            HTMLElement("div")(HTMLElement("p")("text"), class_="wrapper")

        Args:
            *content: Child nodes to append (same types as :meth:`add`).
            **attributes: HTML attributes to merge into the existing dict.
                Use trailing underscores for Python-reserved words
                (e.g. ``class_="btn"`` becomes ``class="btn"``).

        Returns:
            ``self``, enabling further chaining.
        """
        if attributes:
            self.attributes.update(attributes)
        if content:
            self.add(*content)
        return self

    def __repr__(self):
        """Return the HTML string representation (same as ``__str__``)."""
        return self.__str__()

    def __add__(self, other):
        """Concatenate this element's HTML with another value (``self + other``).

        Returns:
            A string containing this element's HTML followed by ``str(other)``.
        """
        return str(self) + str(other)

    def __radd__(self, other):
        """Concatenate another value's string with this element (``other + self``).

        Returns:
            A string containing ``str(other)`` followed by this element's HTML.
        """
        return str(other) + str(self)

def add_html_helpers(globals_dict):
    """Inject underscore-prefixed HTML helper functions into a namespace.

    After calling ``add_html_helpers(globals())``, you can build HTML with
    concise factory functions like ``_div``, ``_p``, ``_a``, etc.  Each helper
    accepts an optional leading dict of attributes followed by any number of
    child content items::

        add_html_helpers(globals())

        page = _html(
            _head(_title("My Page")),
            _body(
                _h1({"class": "title"}, "Hello"),
                _p("Welcome to my site"),
            ),
        )
        print(page)

    The helpers cover all standard HTML5 tags grouped by category: document
    structure, sections, headings/text, lists, tables, forms, media, embedded,
    text semantics, and interactive elements.

    Args:
        globals_dict: The dict to inject helpers into -- typically
            ``globals()`` from the calling module.
    """

    def _make(tag):
        """Create a factory function for the given HTML tag.

        The returned helper accepts positional arguments where the **first
        dict** encountered is treated as attributes and all other arguments
        (including lists/tuples, which are flattened) become child content.

        Args:
            tag: The HTML tag name (e.g. ``"div"``).

        Returns:
            A callable ``helper(*args) -> HTMLElement`` for that tag.
        """
        def helper(*args):
            attrs = {}
            content = []
            for arg in args:
                if isinstance(arg, dict) and not attrs:  # first dict = attrs
                    attrs = arg
                elif isinstance(arg, (list, tuple)):
                    content.extend(arg)  # flatten lists/tuples
                else:
                    content.append(arg)
            return HTMLElement(tag, attrs, content)
        return helper

    all_tags = {
        # Document
        "_html": _make("html"), "_head": _make("head"), "_body": _make("body"),
        "_title": _make("title"), "_meta": _make("meta"), "_link": _make("link"),
        "_style": _make("style"), "_script": _make("script"), "_base": _make("base"),

        # Sections
        "_header": _make("header"), "_footer": _make("footer"), "_nav": _make("nav"),
        "_main": _make("main"), "_section": _make("section"), "_article": _make("article"),
        "_aside": _make("aside"), "_hgroup": _make("hgroup"), "_address": _make("address"),

        # Headings & text
        "_h1": _make("h1"), "_h2": _make("h2"), "_h3": _make("h3"),
        "_h4": _make("h4"), "_h5": _make("h5"), "_h6": _make("h6"),
        "_p": _make("p"), "_div": _make("div"), "_span": _make("span"),
        "_pre": _make("pre"), "_code": _make("code"), "_blockquote": _make("blockquote"),
        "_hr": _make("hr"), "_br": _make("br"),

        # Lists
        "_ul": _make("ul"), "_ol": _make("ol"), "_li": _make("li"),
        "_dl": _make("dl"), "_dt": _make("dt"), "_dd": _make("dd"),

        # Tables
        "_table": _make("table"), "_caption": _make("caption"),
        "_thead": _make("thead"), "_tbody": _make("tbody"), "_tfoot": _make("tfoot"),
        "_tr": _make("tr"), "_th": _make("th"), "_td": _make("td"),
        "_col": _make("col"), "_colgroup": _make("colgroup"),

        # Forms
        "_form": _make("form"), "_input": _make("input"), "_textarea": _make("textarea"),
        "_button": _make("button"), "_select": _make("select"), "_option": _make("option"),
        "_optgroup": _make("optgroup"), "_label": _make("label"), "_fieldset": _make("fieldset"),
        "_legend": _make("legend"), "_datalist": _make("datalist"), "_output": _make("output"),

        # Media
        "_img": _make("img"), "_figure": _make("figure"), "_figcaption": _make("figcaption"),
        "_picture": _make("picture"), "_source": _make("source"),
        "_audio": _make("audio"), "_video": _make("video"), "_track": _make("track"),
        "_canvas": _make("canvas"), "_map": _make("map"), "_area": _make("area"),

        # Embedded
        "_iframe": _make("iframe"), "_embed": _make("embed"), "_object": _make("object"),
        "_param": _make("param"),

        # Text semantics
        "_a": _make("a"), "_em": _make("em"), "_strong": _make("strong"), "_small": _make("small"),
        "_s": _make("s"), "_cite": _make("cite"), "_q": _make("q"), "_dfn": _make("dfn"),
        "_abbr": _make("abbr"), "_data": _make("data"), "_time": _make("time"),
        "_var": _make("var"), "_samp": _make("samp"), "_kbd": _make("kbd"),
        "_sub": _make("sub"), "_sup": _make("sup"), "_i": _make("i"), "_b": _make("b"),
        "_u": _make("u"), "_mark": _make("mark"), "_ruby": _make("ruby"),
        "_rt": _make("rt"), "_rp": _make("rp"), "_bdi": _make("bdi"), "_bdo": _make("bdo"),
        "_wbr": _make("wbr"),

        # Interactive
        "_details": _make("details"), "_summary": _make("summary"), "_dialog": _make("dialog"),
        "_menu": _make("menu"), "_menuitem": _make("menuitem"),
    }

    globals_dict.update(all_tags)

# Call once: add_html_helpers(globals())
