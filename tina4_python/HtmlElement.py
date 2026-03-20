"""
Tina4 - This is not a 4ramework.
Programmatic HTML builder - avoids string concatenation.

Usage:
    el = HTMLElement("div", {"class": "card"}, ["Hello"])
    str(el)  # <div class="card">Hello</div>

    # Builder pattern (via __call__)
    el = HTMLElement("div")(HTMLElement("p")("Text"))

    # Helper functions
    add_html_helpers(globals())
    html = _div({"class": "card"}, _p("Hello"))
"""

import html as _html


class HTMLElement:
    """A single HTML element that renders itself and its children to a string."""

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, tag, attrs=None, children=None):
        self.tag = tag.lower()
        self.attrs = attrs or {}
        self.children = children or []

    def __call__(self, *children):
        """Builder pattern - append children/attrs and return a new element."""
        attrs = dict(self.attrs)
        kids = list(self.children)

        for child in children:
            if isinstance(child, dict):
                # Dict argument merges as attributes
                attrs.update(child)
            elif isinstance(child, (list, tuple)):
                kids.extend(child)
            else:
                kids.append(child)

        return HTMLElement(self.tag, attrs, kids)

    def __str__(self):
        """Render to HTML string."""
        parts = [f"<{self.tag}"]

        for key, value in self.attrs.items():
            if value is True:
                parts.append(f" {key}")
            elif value is not False and value is not None:
                escaped = _html.escape(str(value), quote=True)
                parts.append(f' {key}="{escaped}"')

        if self.tag in self.VOID_TAGS:
            parts.append(">")
            return "".join(parts)

        parts.append(">")

        for child in self.children:
            if isinstance(child, HTMLElement):
                parts.append(str(child))
            else:
                parts.append(_html.escape(str(child), quote=True))

        parts.append(f"</{self.tag}>")
        return "".join(parts)

    def __repr__(self):
        return str(self)


def _make_element(tag, *args):
    """Smart constructor: first dict arg becomes attrs, rest are children."""
    attrs = {}
    children = []
    for arg in args:
        if isinstance(arg, dict) and not attrs:
            attrs = arg
        elif isinstance(arg, (list, tuple)):
            children.extend(arg)
        else:
            children.append(arg)
    return HTMLElement(tag, attrs, children)


# All common HTML tags for helper generation
HTML_TAGS = [
    "a", "abbr", "address", "area", "article", "aside", "audio",
    "b", "base", "bdi", "bdo", "blockquote", "body", "br", "button",
    "canvas", "caption", "cite", "code", "col", "colgroup",
    "data", "datalist", "dd", "del", "details", "dfn", "dialog", "div", "dl", "dt",
    "em", "embed",
    "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html",
    "i", "iframe", "img", "input", "ins",
    "kbd",
    "label", "legend", "li", "link",
    "main", "map", "mark", "menu", "meta", "meter",
    "nav", "noscript",
    "object", "ol", "optgroup", "option", "output",
    "p", "param", "picture", "pre", "progress",
    "q",
    "rp", "rt", "ruby",
    "s", "samp", "script", "section", "select", "slot", "small", "source", "span",
    "strong", "style", "sub", "summary", "sup",
    "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time",
    "title", "tr", "track",
    "u", "ul",
    "var", "video",
    "wbr",
]


def add_html_helpers(namespace):
    """Inject _div(), _p(), _a(), _span(), etc. into the given namespace."""
    for tag in HTML_TAGS:
        namespace[f"_{tag}"] = lambda *args, t=tag, **kwargs: _make_element(t, *args, **kwargs)
