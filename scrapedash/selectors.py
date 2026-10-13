"""A compact CSS selector engine for the DOM in dom.py.

Supported:
    tag  *  #id  .class  [attr]  [attr=value]  [attr~=word]  [attr^=start]
    [attr$=end]  [attr*=part]  :first-child  :last-child  :nth-child(n)
    descendant (space)  child (>)  groups (a, b)

Examples: "article.product_pod h3 > a", "li.next > a", "div.quote small.author",
          "a[href^='/tag/']", "ul > li:nth-child(2)"

Invalid selectors raise SelectorError with the position of the problem.
"""

import re
from functools import lru_cache

from .exceptions import SelectorError

_IDENT = r"-?[A-Za-z_][A-Za-z0-9_-]*"
_TOKEN = re.compile(
    rf"""(?P<space>\s*>\s*|\s*,\s*|\s+)
       |(?P<tag>{_IDENT}|\*)
       |\#(?P<id>{_IDENT})
       |\.(?P<cls>{_IDENT})
       |\[\s*(?P<attr>{_IDENT})\s*(?:(?P<op>[~^$*]?=)\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\]\s]+))\s*)?\]
       |:(?P<pseudo>first-child|last-child|nth-child\(\s*(?P<nth>\d+)\s*\))
    """, re.VERBOSE)
MAX_SELECTOR_LENGTH = 300


class Compound:
    """One simple selector like 'p.price_color' or 'a[href]'."""
    __slots__ = ("tag", "ids", "classes", "attrs", "pseudos")

    def __init__(self):
        self.tag, self.ids, self.classes, self.attrs, self.pseudos = None, [], [], [], []

    def is_empty(self):
        return not (self.tag or self.ids or self.classes or self.attrs or self.pseudos)

    def matches(self, node):
        if node.is_text or node.tag == "#document":
            return False
        if self.tag and self.tag != "*" and node.tag != self.tag:
            return False
        if any(node.attrs.get("id") != i for i in self.ids):
            return False
        node_classes = node.classes
        if any(c not in node_classes for c in self.classes):
            return False
        for name, op, value in self.attrs:
            actual = node.attrs.get(name)
            if actual is None:
                return False
            if op == "=" and actual != value:
                return False
            if op == "~=" and value not in actual.split():
                return False
            if op == "^=" and not (value and actual.startswith(value)):
                return False
            if op == "$=" and not (value and actual.endswith(value)):
                return False
            if op == "*=" and not (value and value in actual):
                return False
        for pseudo in self.pseudos:
            siblings = node.parent.element_children if node.parent else [node]
            position = siblings.index(node) + 1
            if pseudo == "first-child" and position != 1:
                return False
            if pseudo == "last-child" and position != len(siblings):
                return False
            if isinstance(pseudo, int) and position != pseudo:
                return False
        return True


@lru_cache(maxsize=256)
def parse_selector(selector):
    """'div.a > p, span' -> [[Compound, '>', Compound], [Compound]] (combinators between compounds)."""
    if not isinstance(selector, str) or not selector.strip():
        raise SelectorError("Selector cannot be empty.")
    if len(selector) > MAX_SELECTOR_LENGTH:
        raise SelectorError(f"Selector is too long (max {MAX_SELECTOR_LENGTH} characters).")
    text = selector.strip()
    groups, chain, compound = [], [], Compound()
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise SelectorError(f"Unexpected '{text[pos]}' at position {pos + 1} in selector '{selector}'.")
        if m.group("space") is not None:
            sep = m.group("space").strip()
            if compound.is_empty():
                raise SelectorError(f"Selector '{selector}' has a combinator with nothing before it "
                                    f"(position {pos + 1}).")
            chain.append(compound)
            compound = Compound()
            if sep == ",":
                groups.append(chain)
                chain = []
            else:
                chain.append(">" if sep == ">" else " ")
        elif m.group("tag"):
            if not compound.is_empty():
                raise SelectorError(f"Tag name must come first in '{selector}' (position {pos + 1}).")
            compound.tag = m.group("tag").lower()
        elif m.group("id"):
            compound.ids.append(m.group("id"))
        elif m.group("cls"):
            compound.classes.append(m.group("cls"))
        elif m.group("attr"):
            value = next((v for v in (m.group("dq"), m.group("sq"), m.group("bare")) if v is not None), None)
            compound.attrs.append((m.group("attr").lower(), m.group("op"), value))
        else:
            compound.pseudos.append(int(m.group("nth")) if m.group("nth") else m.group("pseudo"))
            if m.group("nth") and int(m.group("nth")) < 1:
                raise SelectorError(":nth-child() needs a number of 1 or more.")
        pos = m.end()
    if compound.is_empty():
        raise SelectorError(f"Selector '{selector}' ends with a combinator.")
    chain.append(compound)
    groups.append(chain)
    return tuple(tuple(g) for g in groups)


def _matches_chain(node, chain, index):
    """Does `node` match chain[index], with the rest of the chain matching its ancestors?"""
    if not chain[index].matches(node):
        return False
    if index == 0:
        return True
    combinator, previous = chain[index - 1], index - 2
    parent = node.parent
    if combinator == ">":
        return parent is not None and _matches_chain(parent, chain, previous)
    while parent is not None:  # descendant: any ancestor may match
        if _matches_chain(parent, chain, previous):
            return True
        parent = parent.parent
    return False


def select(root, selector):
    """All elements under `root` matching the selector, in document order, without duplicates."""
    groups = parse_selector(selector)
    return [node for node in root.iter()
            if any(_matches_chain(node, chain, len(chain) - 1) for chain in groups)]
