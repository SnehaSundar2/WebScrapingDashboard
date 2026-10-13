import unittest

from scrapedash.dom import parse_html
from scrapedash.exceptions import SelectorError
from scrapedash.selectors import parse_selector


class TestDom(unittest.TestCase):
    def test_messy_html_is_repaired(self):
        dom = parse_html("<ul><li>One<li>Two</ul><p>First<p>Second<div>Block</div></span>")
        self.assertEqual([li.text() for li in dom.select("ul > li")], ["One", "Two"])  # <li> closes <li>
        self.assertEqual([p.text() for p in dom.select("p")], ["First", "Second"])       # <p> closes <p>
        self.assertIsNotNone(dom.select_one("div"))                                      # stray </span> ignored
        self.assertEqual(dom.select_one("div").parent.tag, "#document")                  # <div> closed the <p>

    def test_void_elements_entities_and_text(self):
        dom = parse_html("<p>Price&nbsp;&pound;5 &amp; up<br>today<img src=x.png ALT='Cover'></p>"
                         "<script>var hidden = 1;</script><style>p{}</style>")
        p = dom.select_one("p")
        self.assertEqual(p.text(), "Price £5 & up today")
        self.assertEqual(dom.select_one("img").get("alt"), "Cover")       # attribute names lower-cased
        self.assertNotIn("hidden", dom.text())                            # script/style never in visible text
        self.assertEqual(len(p.element_children), 2)                       # <br> and <img> have no children

    def test_self_closing_and_repr(self):
        dom = parse_html('<div class="a"/><span id="s">x</span>')
        self.assertEqual(dom.select_one("div").children, [])
        self.assertEqual(dom.select_one("span").parent.tag, "#document")
        self.assertIn("<span", repr(dom.select_one("span")))


class TestSelectors(unittest.TestCase):
    HTML = """
    <div id="main" class="box wide">
      <ul class="list"><li class="item first">A</li><li class="item">B</li><li class="item last">C</li></ul>
      <p><a href="/tag/love/" rel="tag nofollow">love</a> <a href="https://x.example.com/page.html">ext</a></p>
    </div>
    <section><div class="box"><a href="/tag/life/">life</a></div></section>"""

    def setUp(self):
        self.dom = parse_html(self.HTML)

    def texts(self, selector):
        return [n.text() for n in self.dom.select(selector)]

    def test_simple_selectors(self):
        self.assertEqual(self.texts("li"), ["A", "B", "C"])
        self.assertEqual(self.texts("li.item.last"), ["C"])
        self.assertEqual(len(self.dom.select("#main")), 1)
        self.assertEqual(len(self.dom.select("div.box")), 2)
        self.assertEqual(len(self.dom.select("*")), len(list(self.dom.iter())))

    def test_attribute_operators(self):
        self.assertEqual(self.texts("a[href^='/tag/']"), ["love", "life"])
        self.assertEqual(self.texts('a[href$=".html"]'), ["ext"])
        self.assertEqual(self.texts("a[href*=example]"), ["ext"])
        self.assertEqual(self.texts("a[rel~=nofollow]"), ["love"])
        self.assertEqual(self.texts("a[href='/tag/life/']"), ["life"])
        self.assertEqual(len(self.dom.select("a[rel]")), 1)

    def test_combinators_groups_and_pseudos(self):
        self.assertEqual(self.texts("#main a"), ["love", "ext"])            # descendant
        self.assertEqual(self.texts("#main > a"), [])                       # child only
        self.assertEqual(self.texts("section > div.box > a"), ["life"])
        self.assertEqual(self.texts("li:first-child"), ["A"])
        self.assertEqual(self.texts("li:last-child"), ["C"])
        self.assertEqual(self.texts("ul > li:nth-child(2)"), ["B"])
        self.assertEqual(self.texts("li.last, li.first, li"), ["A", "B", "C"])  # document order, no duplicates

    def test_invalid_selectors_explain_the_problem(self):
        cases = {"": "empty", "div!": "position 4", "a >": "ends with", "> a": "nothing before",
                 "a,,b": "nothing before", "[href": "position 1", "li:hover": "position 3", "a" * 301: "too long",
                 ".item div#": "position 10"}
        for selector, hint in cases.items():
            with self.assertRaises(SelectorError, msg=selector) as ctx:
                parse_selector(selector)
            self.assertIn(hint, str(ctx.exception), selector)


if __name__ == "__main__":
    unittest.main()
