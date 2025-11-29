#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

class HTMLElement:
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "keygen", "link", "meta", "param", "source", "track", "wbr"
    }

    def __init__(self, tag_name="div", attributes=None, content=None):
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
        if not isinstance(text, str):
            text = str(text)
        return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

    def add(self, *items):
        for item in items:
            if item is not None:
                self.content.append(item)
        return self

    def render_attributes(self):
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
        if not self.tag_name:
            return "".join(str(c) for c in self.content if c is not None)

        open_tag = f"<{self.tag_name}{self.render_attributes()}>"
        if self.tag_name in self.VOID_TAGS:
            return open_tag

        content_str = "".join(str(c) for c in self.content if c is not None)
        return f"{open_tag}{content_str}</{self.tag_name}>"

    def __call__(self, *content, **attributes):
        if attributes:
            self.attributes.update(attributes)
        if content:
            self.add(*content)
        return self

    def __repr__(self):
        return self.__str__()

    def __add__(self, other):
        return str(self) + str(other)

    def __radd__(self, other):
        return str(other) + str(self)

def add_html_helpers(globals_dict):
# Final fixed _make helper

    def _make(tag):
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
