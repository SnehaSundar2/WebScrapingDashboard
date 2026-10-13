"""Analyse a single web page: structure, content and common quality issues."""

from collections import Counter
from urllib.parse import urljoin, urlsplit

from .analysis import STOPWORDS, WORD
from .dom import parse_html
from .validators import host_of, in_domains

TITLE_MAX = 60
DESCRIPTION_RANGE = (50, 160)
THIN_CONTENT_WORDS = 250


def analyse_page(page):
    dom = parse_html(page.text)
    title_node = dom.select_one("title")
    title = title_node.text() if title_node else ""
    meta = {(m.get("name") or m.get("property") or "").lower(): m.get("content", "")
            for m in dom.select("meta[content]")}
    description = " ".join(meta.get("description", "").split())
    html_node = dom.select_one("html")
    lang = html_node.get("lang", "") if html_node else ""
    canonical = next((l.get("href") for l in dom.select("link[rel]") if "canonical" in l.get("rel").split()), "")

    headings = [(n.tag, n.text()) for n in dom.iter() if n.tag in ("h1", "h2", "h3")]
    body = dom.select_one("body") or dom
    text = body.text()
    words = [w.lower().strip("'-") for w in WORD.findall(text)]
    top_words = [(w, c) for w, c in Counter(words).most_common(60) if w not in STOPWORDS and len(w) > 2][:12]

    site = host_of(page.url)
    internal, external, nofollow, other = set(), set(), 0, 0
    for a in dom.select("a[href]"):
        href = a.get("href").strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if href.startswith(("mailto:", "tel:")):
            other += 1
            continue
        absolute = urljoin(page.url, href)
        if urlsplit(absolute).scheme not in ("http", "https"):
            other += 1
            continue
        (internal if in_domains(host_of(absolute), [site]) else external).add(absolute.split("#")[0])
        if "nofollow" in (a.get("rel") or "").lower().split():
            nofollow += 1
    images = dom.select("img")
    missing_alt = [img.get("src", "?") for img in images if not (img.get("alt") or "").strip()]

    issues = []
    if not title:
        issues.append("The page has no <title>.")
    elif len(title) > TITLE_MAX:
        issues.append(f"The title is {len(title)} characters; search engines show about {TITLE_MAX}.")
    if not description:
        issues.append("No meta description (the summary search engines show).")
    elif not DESCRIPTION_RANGE[0] <= len(description) <= DESCRIPTION_RANGE[1]:
        issues.append(f"Meta description is {len(description)} characters (aim for {DESCRIPTION_RANGE[0]}-"
                      f"{DESCRIPTION_RANGE[1]}).")
    h1_count = sum(1 for tag, _ in headings if tag == "h1")
    if h1_count != 1:
        issues.append(f"The page has {h1_count} <h1> headings (exactly one is recommended).")
    if missing_alt:
        issues.append(f"{len(missing_alt)} of {len(images)} image(s) have no alt text (needed for screen readers).")
    if not lang:
        issues.append("The <html> element has no lang attribute.")
    if len(words) < THIN_CONTENT_WORDS:
        issues.append(f"Only {len(words)} words of visible text (thin content).")
    score = max(0, 100 - 12 * len(issues))
    return {
        "url": page.url, "status": page.status, "title": title, "description": description, "lang": lang,
        "canonical": canonical, "headings": headings[:25], "h1_count": h1_count, "word_count": len(words),
        "top_words": top_words, "internal_links": len(internal), "external_links": len(external),
        "nofollow_links": nofollow, "other_links": other, "external_domains": Counter(host_of(u) for u in external).most_common(5),
        "images": len(images), "images_missing_alt": len(missing_alt), "size_kb": round(page.size / 1024, 1),
        "load_ms": round(page.elapsed * 1000), "from_cache": page.from_cache, "issues": issues, "score": score,
    }


def test_selector(page, selector, limit=5):
    """How many elements a selector matches on a page, with a preview of the first few."""
    dom = parse_html(page.text)
    matches = dom.select(selector)
    preview = []
    for node in matches[:limit]:
        attrs = {k: v[:60] for k, v in list(node.attrs.items())[:4]}
        preview.append({"tag": node.tag, "text": node.text()[:100], "attrs": attrs})
    return len(matches), preview
