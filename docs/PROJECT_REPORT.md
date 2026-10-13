# Project Report: Web Scraping Dashboard

**Program:** Virtual Internship – Python Development, Skyrovix IT Solutions Pvt. Ltd.
**Project:** Web Scraping Dashboard
**Developed and submitted by:** Sneha S (Intern ID: SKX-2026-6425)
**Due date:** 30 November 2026

---

## 1. Introduction

A great deal of useful information is published on web pages rather than in downloadable
datasets: product prices, listings, articles and reviews. Web scraping turns those pages into
structured data that can be analysed. Done carelessly, though, it can overload websites, ignore
their rules, or produce messy, unreliable data.

This project is a responsible web scraper with an analytics dashboard. It fetches pages politely,
extracts and cleans data according to a configurable profile, stores every run, and presents
statistics, data-quality checks and changes over time.

## 2. Objectives

1. Build a working scraper and dashboard from clearly separated Python modules.
2. Validate all input (web addresses, CSS selectors, scraper profiles, settings) before any request is made.
3. Process the scraped data: clean and convert values, compute statistics and distributions, assess data quality, compare runs.
4. Handle errors gracefully: network problems, HTTP errors, robots.txt restrictions, broken pages, damaged files.
5. Scrape responsibly, then document the workflow and verify it with automated tests.

## 3. Tools and technologies

| Item | Used |
|---|---|
| Language | Python 3 (tested on 3.13) |
| Libraries | Standard library only: `urllib.request`, `urllib.robotparser`, `html.parser`, `sqlite3`, `re`, `decimal`, `statistics`, `collections`, `csv`, `json`, `dataclasses`, `logging`, `argparse`, `unittest` |
| Practice websites | books.toscrape.com and quotes.toscrape.com (sandbox sites built for scraping practice) |
| Output | Terminal dashboard, self-contained HTML dashboard (inline SVG charts), CSV, JSON |

## 4. System design

### 4.1 Workflow

1. **Validate.** The profile, start URL and settings are checked first.
2. **Fetch politely.** robots.txt is checked (once per site), a wait is enforced between
   requests, and temporary errors are retried with back-off.
3. **Parse.** The HTML becomes a forgiving document tree.
4. **Extract.** The item selector finds each item, and each field is read and converted to its
   type.
5. **Paginate.** The "next page" link is followed if it stays inside the allowed domains, the page
   limit isn't reached and the page hasn't been visited.
6. **Store.** The run, items, pages and warnings are saved in SQLite.
7. **Analyse.** Statistics, histograms, data quality, insights, and changes since the previous
   run.
8. **Present.** Terminal dashboard, HTML dashboard, CSV/JSON export.

### 4.2 Modules

| Module | Responsibility |
|---|---|
| `validators.py` | URL, number, selector, field-name and file-name validation |
| `fetcher.py` | robots.txt, rate limiting, retries, charset detection, size/type limits |
| `dom.py`, `selectors.py` | HTML document tree and CSS selector engine (written from scratch) |
| `profiles.py`, `extract.py` | Profile format and validation; field extraction and conversion |
| `crawler.py` | Pagination, limits, loop/domain protection, duplicate removal |
| `storage.py` | SQLite runs, items, messages, pages, page cache |
| `analysis.py` | Statistics, histograms, data quality, comparison, insights |
| `page_report.py` | Single-page analysis and selector testing |
| `dashboard.py`, `exporters.py` | Terminal and HTML dashboards; CSV/JSON export |
| `sample_site.py` | Offline sample site and in-memory test web |
| `cli.py`, `main.py` | Menu and command-line options |

## 5. Implementation highlights

**A CSS selector engine from scratch.** Selectors such as `article.product_pod h3 > a` or
`a[href^='/tag/']` are tokenised with a regular expression, then matched right to left with
backtracking for descendant combinators. Errors point to the exact character, e.g. "Unexpected
'!' at position 4 in selector 'div!'".

**Configurable profiles.** The scraper isn't hard-coded to one website. A JSON profile names the
item selector and the fields, and the same engine scrapes the bookshop, the quotes site or a
custom category page. Profiles are validated thoroughly, so mistakes such as a start URL outside
the allowed domains, an unknown field type or a bad selector are reported before any request.

**Data cleaning.** `£51.77` becomes Decimal 51.77, with the currency remembered for display.
`star-rating Three` becomes 3, `In stock` becomes yes, and relative links become absolute.
A value that can't be converted becomes empty, with a warning naming the page, item and field.
An item missing a required field is skipped and reported.

**Analysis.** Each field is summarised by type: numbers get statistics and a histogram with
rounded bin edges (£10–20, £20–30, …), ratings a distribution, categories and tags their most
frequent values, and text fields word frequencies. Averages by group (e.g. average price per star
rating) and a data-quality report (completeness per field, skipped items, duplicates,
unconvertible values) feed plain-English insights.

**Comparing runs.** Two runs of the same profile are matched by the profile's key field (e.g.
the book's URL). On the offline sample site, version 2 changes some data. The comparison
reports 3 new books, 2 removed and 9 changed values: 8 price changes (3 up, 5 down, average
−4.4%) and one change in stock.

**HTML dashboard.** One self-contained file with:
- stat tiles, insights, and a chart for each field type, plus rankings and changes since the
  previous run
- a data-quality table, an item preview, and the pages crawled with any problems

Charts follow consistent rules: one validated colour, thin bars with hairline gridlines,
hover and keyboard tooltips, a "show as table" view for every chart, and a dark mode. All
scraped text is HTML-escaped, and only http(s) links are clickable.

## 6. Testing

43 automated tests were written and **all pass**, without internet access. An in-memory web
replaces the network, and a fake clock makes the rate-limit and retry tests instant.

| # | Test case | Expected | Result |
|---|---|---|---|
| 1 | `<ul><li>One<li>Two</ul>`, stray `</span>`, `&pound;` | Two list items, ignored tag, "£" | Pass |
| 2 | Selector `div!`, `a >`, `li:hover` | SelectorError with the position | Pass |
| 3 | robots.txt `Disallow: /private/`, `Crawl-delay: 4` | Private page refused; waits ≥ 4 s | Pass |
| 4 | Two requests to one site, delay 2 s | 2 s wait between them; none when switching sites | Pass |
| 5 | HTTP 503, then 429 with `Retry-After: 7`, then OK | Retried; waited 2 s and 7 s; page returned | Pass |
| 6 | HTTP 404 | Reported once, not retried | Pass |
| 7 | PDF file / 5 KB page with a 1 KB limit | "not a web page" / "larger than" errors | Pass |
| 8 | 9 kinds of broken profile | Each rejected with a specific message | Pass |
| 9 | `£51.77`, `₹1,299`, `star-rating Three`, `7/10` | 51.77 £, 1299 ₹, 3, error (rating above 5) | Pass |
| 10 | Sample bookshop, all pages | 3 pages, 59 books, 1 skipped item reported | Pass |
| 11 | Next link pointing to itself / to another site | Loop detected / link not followed | Pass |
| 12 | Page 2 returns HTTP 500 | Status "partial", page 1's items kept | Pass |
| 13 | Version 1 vs version 2 of the sample site | 3 new, 2 removed, 8 price + 1 stock change | Pass |
| 14 | Title `<script>alert("x")</script>`, link `javascript:alert(1)` | Escaped; not a clickable link | Pass |
| 15 | CSV cell `=HYPERLINK(...)` | Written as text (`'=`), not a formula | Pass |
| 16 | Damaged database file | Clear StorageError; file released | Pass |
| 17 | Menu: bad option, unknown profile, invalid address, bad selector, missing file | Friendly messages, menu continues | Pass |

**Live verification:**
- books.toscrape.com: 40 books from 2 pages, and the 11-book Travel category with a custom
  profile.
- quotes.toscrape.com: 20 quotes from 2 pages.
- A page report of the quotes home page.

These runs used one robots.txt request per site and a 1.5 s wait between requests.

## 7. Challenges and solutions

| Challenge | Solution |
|---|---|
| No HTML parser with CSS selectors in the standard library | Built a forgiving tree builder on `html.parser` and a selector engine |
| Real HTML is messy | Implied end tags (`<p>`, `<li>`, `<td>`, …), void elements and stray end tags handled the way browsers do |
| Being a good citizen on other people's servers | robots.txt always checked (with Crawl-delay), per-site rate limit, retries with back-off, page limit, domain allow-list |
| Exact money values | `Decimal` everywhere; stored as text in SQLite and JSON so no float rounding |
| One bad value should not lose a whole run | Field-level and page-level error handling; partial results are kept and explained |
| Testing network behaviour reliably | An in-memory `FakeWeb` that simulates pages, errors, redirects and Retry-After, plus a fake clock |
| Demonstrating change tracking | An offline sample site with a "version 2" where prices and stock change |
| A damaged database kept the file locked on Windows | The connection is closed before reporting the error (found by a test) |

## 8. Future enhancements

- Scheduled scraping (e.g. daily), with an alert when a price drops
- JavaScript-rendered pages, using a headless browser
- Line charts of a price over many runs
- More selector features (`:not()`, sibling combinators)
- A web interface (Flask) to browse runs and dashboards

## 9. Conclusion

The Web Scraping Dashboard meets all the project objectives. Fifteen focused modules turn web
pages into clean, analysed data. Everything is validated before any request, and the data
processing runs from HTML parsing to statistics, quality checks and change detection. Errors are
handled at every level without losing results. The scraper behaves responsibly by design, and
its behaviour is verified by 43 passing automated tests plus live runs on the practice sites.

## 10. How to run

```bash
cd WebScrapingDashboard
python main.py --demo
python main.py
python main.py --profile books --pages 3 --html dashboards/books.html
python -m unittest discover -s tests -t . -v
```
