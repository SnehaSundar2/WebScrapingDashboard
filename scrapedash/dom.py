"""A small, forgiving HTML document tree built on html.parser.

Real-world HTML is messy: unclosed <p> and <li> tags, stray end tags, void
elements written as <br> or <br/>. The builder repairs these the way browsers
do (in simplified form), so selectors behave predictably.
"""

from html.parser import HTMLParser

VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                 "source", "track", "wbr"}
RAW_TEXT = {"script", "style", "template", "noscript"}  # their contents are never part of visible text
CLOSES_P = {"address", "article", "aside", "blockquote", "div", "dl", "fieldset", "footer", "form", "h1",
            "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section",
            "table", "ul"}
# a new <tag> implicitly closes an open sibling of these tags (until one of the "scope" tags)
IMPLIED_END = {
    "li": ({"li"}, {"ul", "ol"}),
    "dt": ({"dt", "dd"}, {"dl"}),
    "dd": ({"dt", "dd"}, {"dl"}),
    "tr": ({"tr", "td", "th"}, {"table", "thead", "tbody", "tfoot"}),
    "td": ({"td", "th"}, {"tr", "table"}),
    "th": ({"td", "th"}, {"tr", "table"}),
    "option": ({"option"}, {"select", "datalist"}),
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "data")

    def __init__(self, tag=None, attrs=None, parent=None, data=None):
        self.tag = tag            # None for text nodes
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.data = data          # text content for text nodes

    # ------------------------------------------------------------ navigation
    @property
    def is_text(self):
        return self.tag is None

    @property
    def element_children(self):
        return [c for c in self.children if not c.is_text]

    def iter(self):
        """All descendant elements in document order (not including self)."""
        stack = list(reversed(self.element_children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.element_children))

    def get(self, name, default=None):
        return self.attrs.get(name.lower(), default)

    @property
    def classes(self):
        return self.attrs.get("class", "").split()

    def text(self, separator=" "):
        """Visible text of this element, whitespace collapsed (scripts and styles excluded)."""
        parts = []

        def walk(node):
            for child in node.children:
                if child.is_text:
                    parts.append(child.data)
                elif child.tag not in RAW_TEXT:
                    if child.tag == "br":
                        parts.append("\n")
                    walk(child)
                    if child.tag in CLOSES_P or child.tag in ("li", "td", "th", "tr"):
                        parts.append(" ")

        walk(self)
        return separator.join("".join(parts).split())

    # ------------------------------------------------------------ selectors
    def select(self, selector):
        from .selectors import select
        return select(self, selector)

    def select_one(self, selector):
        found = self.select(selector)
        return found[0] if found else None

    def __repr__(self):
        if self.is_text:
            return f"Text({self.data[:30]!r})"
        attrs = "".join(f' {k}="{v}"' for k, v in list(self.attrs.items())[:3])
        return f"<{self.tag}{attrs}>"


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]

    @property
    def current(self):
        return self.stack[-1]

    def _close_until(self, tags, scope):
        for i in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[i].tag
            if tag in tags:
                del self.stack[i:]
                return
            if tag in scope:
                return

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in CLOSES_P:
            self._close_until({"p"}, {"button", "td", "th", "li", "div", "body", "html"} - {tag})
        if tag in IMPLIED_END:
            closes, scope = IMPLIED_END[tag]
            self._close_until(closes, scope)
        node = Node(tag, {k.lower(): (v if v is not None else "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_ELEMENTS and self.current.tag == tag.lower():
            self.stack.pop()  # <div/> is treated as an empty element

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_ELEMENTS:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
        # stray end tag with no matching open element: ignored, like browsers do

    def handle_data(self, data):
        if data:
            self.current.children.append(Node(parent=self.current, data=data))


def parse_html(html):
    """Parse an HTML string into a Node tree (the '#document' root)."""
    builder = _TreeBuilder()
    builder.feed(html or "")
    builder.close()
    return builder.root
