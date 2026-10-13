"""An offline stand-in for the internet, used by offline mode, the demo and the tests.

FakeWeb replaces urllib's urlopen: it serves pages from memory, can simulate
HTTP errors, redirects and slow servers, and records every request. The
built-in sample site imitates the HTML structure of books.toscrape.com and
quotes.toscrape.com (with invented books and quotes), so the same profiles
work offline. Version 2 of the bookshop changes some prices and stock so
"compare runs" has something to show.
"""

import email.message
import html
import io
import random
import urllib.error

REASONS = {200: "OK", 301: "Moved", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests",
           500: "Internal Server Error", 503: "Service Unavailable"}


def _headers(content_type, extra=None):
    msg = email.message.Message()
    msg["Content-Type"] = content_type
    for key, value in (extra or {}).items():
        msg[key] = str(value)
    return msg


class FakeResponse:
    def __init__(self, url, status, headers, body):
        self._url, self.status, self.headers, self._body = url, status, headers, body

    def read(self, limit=-1):
        return self._body if limit is None or limit < 0 else self._body[:limit]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWeb:
    """Callable like urllib.request.urlopen(request, timeout=...)."""

    def __init__(self):
        self.routes = {}
        self.requests = []   # (url, user_agent)

    def add(self, url, body="", status=200, content_type="text/html; charset=utf-8", headers=None,
            final_url=None, error=None):
        """Register a response. Several responses for one URL are served in order (the last one repeats)."""
        self.routes.setdefault(url, []).append({"body": body.encode("utf-8") if isinstance(body, str) else body,
                                                "status": status, "content_type": content_type,
                                                "headers": headers or {}, "final_url": final_url, "error": error})
        return self

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requests.append((url, request.get_header("User-agent")))
        responses = self.routes.get(url)
        if not responses:
            raise urllib.error.HTTPError(url, 404, "Not Found", _headers("text/html"), io.BytesIO(b"not found"))
        spec = responses.pop(0) if len(responses) > 1 else responses[0]
        if spec["error"] is not None:
            raise spec["error"]
        headers = _headers(spec["content_type"], spec["headers"])
        if spec["status"] >= 400:
            raise urllib.error.HTTPError(url, spec["status"], REASONS.get(spec["status"], "Error"), headers,
                                         io.BytesIO(spec["body"]))
        return FakeResponse(spec["final_url"] or url, spec["status"], headers, spec["body"])


# ------------------------------------------------------------------ sample bookshop
_ADJ = ["Silent", "Hidden", "Golden", "Midnight", "Lost", "Crimson", "Quiet", "Wild", "Broken", "Endless",
        "Paper", "Secret", "Last", "Distant", "Burning", "Gentle"]
_NOUN = ["Harbor", "Garden", "River", "Kingdom", "Letters", "Mountain", "Library", "Lantern", "Orchard",
         "Compass", "Island", "Voyage", "Archive", "Meadow", "Signal", "Monsoon"]
RATING_WORDS = ["One", "Two", "Three", "Four", "Five"]
BOOKS_PER_PAGE = 20


def sample_books(version=1):
    rng = random.Random(2026)
    titles = []
    for adj in _ADJ:
        for noun in _NOUN:
            titles.append(f"The {adj} {noun}")
    rng.shuffle(titles)
    books = []
    for i, title in enumerate(titles[:60], 1):
        books.append({"id": 1000 - i, "title": title, "price": round(rng.uniform(10, 60), 2),
                      "rating": rng.choices(RATING_WORDS, weights=[22, 20, 20, 19, 19])[0],
                      "in_stock": rng.random() > 0.12})
    books[27]["price"] = None        # one product without a price (shows the "skipped" warning)
    books[33]["rating"] = ""         # one product without a rating word (shows a missing value)
    if version >= 2:
        change = random.Random(7)
        for b in change.sample(books[:50], 8):
            if b["price"] is not None:
                b["price"] = round(b["price"] * change.choice([0.8, 0.85, 0.9, 1.1, 1.2]), 2)
        books[5]["in_stock"] = not books[5]["in_stock"]
        del books[44:46]             # two books disappear
        for j, title in enumerate(titles[60:63], 1):
            books.append({"id": 900 - j, "title": title, "price": round(change.uniform(10, 60), 2),
                          "rating": "Four", "in_stock": True})
    return books


def _slug(book):
    return f"{book['title'].lower().replace(' ', '-')}_{book['id']}"


def books_page(books, page, total_pages, prefix):
    """HTML in the same structure as books.toscrape.com. `prefix` is '' on the home page, '../' elsewhere."""
    pods = []
    for b in books:
        price = f'<p class="price_color">£{b["price"]:.2f}</p>' if b["price"] is not None else ""
        stock = ('<p class="instock availability"><i class="icon-ok"></i> In stock</p>' if b["in_stock"] else
                 '<p class="outofstock availability"><i class="icon-remove"></i> Out of stock</p>')
        link = f'{"catalogue/" if prefix == "" else ""}{_slug(b)}/index.html'
        title = html.escape(b["title"])
        pods.append(f"""
    <li class="col-xs-6 col-sm-4 col-md-3 col-lg-3">
    <article class="product_pod">
        <div class="image_container"><a href="{link}"><img src="{prefix}media/cache/{b['id']}.jpg" alt="{title}" class="thumbnail"></a></div>
        <p class="star-rating {b['rating']}"><i class="icon-star"></i></p>
        <h3><a href="{link}" title="{title}">{title[:20]}{'...' if len(title) > 20 else ''}</a></h3>
        <div class="product_price">{price}
            {stock}
            <form><button type="submit" class="btn btn-primary btn-block">Add to basket</button></form>
        </div>
    </article>
    </li>""")
    pager = ['<ul class="pager">']
    if page > 1:
        pager.append(f'<li class="previous"><a href="{"page-%d.html" % (page - 1)}">previous</a></li>')
    pager.append(f'<li class="current">Page {page} of {total_pages}</li>')
    if page < total_pages:
        href = f"catalogue/page-{page + 1}.html" if prefix == "" else f"page-{page + 1}.html"
        pager.append(f'<li class="next"><a href="{href}">next</a></li>')
    pager.append("</ul>")
    return f"""<!DOCTYPE html>
<html lang="en-us" class="no-js">
<head><title>All products | Books to Scrape - Sandbox (offline sample)</title>
<meta charset="utf-8"><meta name="description" content="">
</head>
<body id="default" class="default">
<header class="header container-fluid"><div class="page_inner"><div class="row">
<div class="col-sm-8 h1"><a href="{prefix}index.html">Books to Scrape</a><small> We love being scraped!</small></div>
</div></div></header>
<div class="page_inner"><ul class="breadcrumb"><li><a href="{prefix}index.html">Home</a></li><li class="active">All products</li></ul>
<div class="row"><aside class="sidebar col-sm-4 col-md-3"><div class="side_categories"><ul class="nav nav-list">
<li><a href="{prefix}catalogue/category/books_1/index.html">Books</a><ul>
<li><a href="{prefix}catalogue/category/books/travel_2/index.html">Travel</a></li>
<li><a href="{prefix}catalogue/category/books/mystery_3/index.html">Mystery</a></li></ul></li></ul></div></aside>
<div class="col-sm-8 col-md-9"><div class="page-header action"><h1>All products</h1></div>
<section><div class="alert alert-warning" role="alert"><strong>Warning!</strong> This is a demo website for web scraping purposes.</div>
<ol class="row">{''.join(pods)}
</ol>
<div>{''.join(pager)}</div>
</section></div></div></div>
<script>var tracking = "not part of the visible text";</script>
</body></html>"""


# ------------------------------------------------------------------ sample quotes site
_QUOTES = [
    ("Small steps taken every day add up to a long journey.", "Asha Rao", ["learning", "habits", "life"]),
    ("Write the code you would like to read tomorrow.", "Vikram Nair", ["programming", "work"]),
    ("A question asked today saves a mistake made tomorrow.", "Meera Iyer", ["learning", "work"]),
    ("Patience is the bridge between effort and results.", "Asha Rao", ["patience", "life"]),
    ("Tests are notes you leave for your future self.", "Vikram Nair", ["programming", "testing"]),
    ("Kindness costs nothing and returns everything.", "Lakshmi Menon", ["kindness", "life"]),
    ("Curiosity turns every problem into a puzzle.", "Meera Iyer", ["learning", "curiosity"]),
    ("Done carefully beats done quickly and done twice.", "Rahul Verma", ["work", "habits"]),
    ("Good friends make long roads short.", "Lakshmi Menon", ["friendship", "life"]),
    ("Read the error message before you search for the answer.", "Vikram Nair", ["programming", "learning"]),
    ("Rest is part of the work, not a break from it.", "Asha Rao", ["habits", "health"]),
    ("Every expert was once a beginner who did not give up.", "Rahul Verma", ["learning", "inspiration"]),
    ("Clear names make clear programs.", "Vikram Nair", ["programming"]),
    ("A shared idea grows; a hidden one fades.", "Lakshmi Menon", ["friendship", "inspiration"]),
    ("The best time to start was yesterday; the next best time is now.", "Rahul Verma", ["inspiration", "habits"]),
    ("Listen twice as much as you speak.", "Meera Iyer", ["life", "kindness"]),
    ("Simple solutions are usually the hardest to find.", "Vikram Nair", ["programming", "work"]),
    ("Gratitude turns what we have into enough.", "Lakshmi Menon", ["life", "inspiration"]),
]


def quotes_page(quotes, page, total_pages):
    blocks = []
    for text, author, tags in quotes:
        slug = author.replace(" ", "-")
        tag_links = "\n".join(f'            <a class="tag" href="/tag/{t}/page/1/">{t}</a>' for t in tags)
        blocks.append(f"""
    <div class="quote" itemscope itemtype="http://schema.org/CreativeWork">
        <span class="text" itemprop="text">“{html.escape(text)}”</span>
        <span>by <small class="author" itemprop="author">{html.escape(author)}</small>
        <a href="/author/{slug}">(about)</a>
        </span>
        <div class="tags">
            Tags:
            <meta class="keywords" itemprop="keywords" content="{','.join(tags)}" />
{tag_links}
        </div>
    </div>""")
    pager = '<nav><ul class="pager">'
    if page > 1:
        pager += f'<li class="previous"><a href="/page/{page - 1}/"><span aria-hidden="true">&larr;</span> Previous</a></li>'
    if page < total_pages:
        pager += f'<li class="next"><a href="/page/{page + 1}/">Next <span aria-hidden="true">&rarr;</span></a></li>'
    pager += "</ul></nav>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Quotes to Scrape (offline sample)</title></head>
<body><div class="container"><div class="row header-box"><div class="col-md-8"><h1><a href="/">Quotes to Scrape</a></h1></div></div>
<div class="row"><div class="col-md-8">{''.join(blocks)}
{pager}
</div></div></div></body></html>"""


def build_sample_web(version=1):
    """FakeWeb holding the offline sample bookshop and quotes site."""
    web = FakeWeb()
    books = sample_books(version)
    pages = [books[i:i + BOOKS_PER_PAGE] for i in range(0, len(books), BOOKS_PER_PAGE)]
    base = "https://books.toscrape.com/"
    web.add(base, books_page(pages[0], 1, len(pages), ""))
    web.add(base + "index.html", books_page(pages[0], 1, len(pages), ""))
    for n, chunk in enumerate(pages, 1):
        web.add(f"{base}catalogue/page-{n}.html", books_page(chunk, n, len(pages), "../"))
    qbase = "https://quotes.toscrape.com/"
    qpages = [_QUOTES[i:i + 10] for i in range(0, len(_QUOTES), 10)]
    web.add(qbase, quotes_page(qpages[0], 1, len(qpages)))
    for n, chunk in enumerate(qpages, 1):
        web.add(f"{qbase}page/{n}/", quotes_page(chunk, n, len(qpages)))
    return web
