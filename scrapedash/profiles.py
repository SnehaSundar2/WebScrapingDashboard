"""Scraper profiles: what to scrape from a site, described as data (JSON-compatible dicts).

A profile lists the CSS selector of each repeated item (e.g. one book), the fields
to read inside it (selector + attribute + type), and how to find the next page.
Profiles are validated thoroughly, so a typo is reported before any request is made.

Field types and what they become:
    text      cleaned text                         category  text grouped in charts (e.g. author)
    number    Decimal (first number in the text)   money     Decimal price (£51.77 -> 51.77)
    count     whole number ("22 available" -> 22)  rating    1-5 ("star-rating Three" -> 3)
    bool      True/False (true_if text matches)    url       absolute link
    list      every match, as a list of text (e.g. tags)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import validators as v
from .exceptions import ValidationError

FIELD_TYPES = ("text", "category", "number", "money", "count", "rating", "bool", "url", "list")
NUMERIC_TYPES = ("number", "money", "count", "rating")
MAX_FIELDS = 20
MAX_PROFILE_BYTES = 50_000


@dataclass
class Field:
    name: str
    select: str = ""         # "" means the item element itself
    attr: str = ""           # "" means the element's text
    type: str = "text"
    required: bool = False
    true_if: str = ""        # bool fields: case-insensitive text that means True


@dataclass
class Profile:
    name: str
    description: str
    start_url: str
    allowed_domains: list
    item: str
    fields: dict             # name -> Field (insertion order kept)
    next_page: str = ""
    key: str = ""            # field that identifies an item (used for duplicates and comparing runs)
    label: str = ""          # field shown as the item's name in tables
    raw: dict = field(default_factory=dict, repr=False)

    def numeric_fields(self):
        return [f for f in self.fields.values() if f.type in NUMERIC_TYPES]


BUILTIN = {
    "books": {
        "name": "books",
        "description": "Books to Scrape — a sandbox bookshop made for scraping practice",
        "start_url": "https://books.toscrape.com/",
        "allowed_domains": ["books.toscrape.com"],
        "item": "article.product_pod",
        "next_page": "li.next > a",
        "key": "url",
        "label": "title",
        "fields": {
            "title": {"select": "h3 > a", "attr": "title", "type": "text", "required": True},
            "price": {"select": "p.price_color", "type": "money", "required": True},
            "rating": {"select": "p.star-rating", "attr": "class", "type": "rating"},
            "in_stock": {"select": "p.availability", "type": "bool", "true_if": "in stock"},
            "url": {"select": "h3 > a", "attr": "href", "type": "url", "required": True},
            "image": {"select": "img.thumbnail", "attr": "src", "type": "url"},
        },
    },
    "quotes": {
        "name": "quotes",
        "description": "Quotes to Scrape — a sandbox quotes site made for scraping practice",
        "start_url": "https://quotes.toscrape.com/",
        "allowed_domains": ["quotes.toscrape.com"],
        "item": "div.quote",
        "next_page": "li.next > a",
        "key": "text",
        "label": "text",
        "fields": {
            "text": {"select": "span.text", "type": "text", "required": True},
            "author": {"select": "small.author", "type": "category", "required": True},
            "tags": {"select": "a.tag", "type": "list"},
            "author_url": {"select": "a[href^='/author/']", "attr": "href", "type": "url"},
        },
    },
}


def _expect(data, key, kind, where, required=True, default=None):
    if key not in data:
        if required:
            raise ValidationError(f"{where}: missing '{key}'.")
        return default
    value = data[key]
    if not isinstance(value, kind):
        names = kind.__name__ if isinstance(kind, type) else " or ".join(k.__name__ for k in kind)
        raise ValidationError(f"{where}: '{key}' must be a {names}.")
    return value


def load_profile(data):
    """Validate a profile dict and return a Profile."""
    if not isinstance(data, dict):
        raise ValidationError("A profile must be a JSON object.")
    known = {"name", "description", "start_url", "allowed_domains", "item", "next_page", "key", "label", "fields"}
    unknown = set(data) - known
    if unknown:
        raise ValidationError(f"Profile has unknown setting(s): {', '.join(sorted(unknown))}.")
    name = _expect(data, "name", str, "Profile").strip()
    if not v.FIELD_NAME.match(name.replace("-", "_")):
        raise ValidationError("Profile name must be lowercase letters, digits, - or _ (e.g. 'books').")
    where = f"Profile '{name}'"
    domains = _expect(data, "allowed_domains", list, where)
    if not domains or not all(isinstance(d, str) and d.strip() for d in domains):
        raise ValidationError(f"{where}: 'allowed_domains' must list at least one domain, e.g. [\"example.com\"].")
    domains = [d.strip().lower() for d in domains]
    for d in domains:
        v.validate_url(d)  # checks it is a real host name
    start_url = v.validate_url(_expect(data, "start_url", str, where), domains)
    item = v.validate_selector(_expect(data, "item", str, where), f"{where}: 'item' selector")
    next_page = _expect(data, "next_page", str, where, required=False, default="").strip()
    if next_page:
        v.validate_selector(next_page, f"{where}: 'next_page' selector")

    raw_fields = _expect(data, "fields", dict, where)
    if not raw_fields:
        raise ValidationError(f"{where}: define at least one field.")
    if len(raw_fields) > MAX_FIELDS:
        raise ValidationError(f"{where}: at most {MAX_FIELDS} fields.")
    fields = {}
    for fname, spec in raw_fields.items():
        fname = v.validate_field_name(fname)
        fwhere = f"{where}, field '{fname}'"
        if not isinstance(spec, dict):
            raise ValidationError(f"{fwhere}: must be an object like {{\"select\": \"h3 > a\", \"type\": \"text\"}}.")
        extra = set(spec) - {"select", "attr", "type", "required", "true_if"}
        if extra:
            raise ValidationError(f"{fwhere}: unknown option(s) {', '.join(sorted(extra))}.")
        ftype = _expect(spec, "type", str, fwhere, required=False, default="text")
        if ftype not in FIELD_TYPES:
            raise ValidationError(f"{fwhere}: type must be one of {', '.join(FIELD_TYPES)}.")
        select = _expect(spec, "select", str, fwhere, required=False, default="").strip()
        if select:
            v.validate_selector(select, f"{fwhere}: selector")
        attr = _expect(spec, "attr", str, fwhere, required=False, default="").strip().lower()
        if attr and not v.FIELD_NAME.match(attr.replace("-", "_")):
            raise ValidationError(f"{fwhere}: '{attr}' is not a valid attribute name.")
        fields[fname] = Field(fname, select, attr, ftype,
                              bool(_expect(spec, "required", bool, fwhere, required=False, default=False)),
                              _expect(spec, "true_if", str, fwhere, required=False, default="").strip().lower())
    key = _expect(data, "key", str, where, required=False, default="")
    label = _expect(data, "label", str, where, required=False, default="")
    for setting, value in (("key", key), ("label", label)):
        if value and value not in fields:
            raise ValidationError(f"{where}: '{setting}' must be one of the fields ({', '.join(fields)}).")
    if key and not fields[key].required:
        raise ValidationError(f"{where}: the key field '{key}' must be marked \"required\": true.")
    return Profile(name, _expect(data, "description", str, where, required=False, default="").strip(),
                   start_url, domains, item, fields, next_page, key, label or next(iter(fields)), raw=dict(data))


def load_profile_file(path):
    path = Path(str(path).strip().strip('"'))
    if not path.exists():
        raise ValidationError(f"Profile file not found: {path}")
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ValidationError("Profile file is too large to be a scraper profile.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path.name} is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno}).") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"Could not read {path.name}: {exc}") from None
    return load_profile(data)


def builtin(name):
    key = str(name or "").strip().lower()
    if key not in BUILTIN:
        raise ValidationError(f"Unknown profile '{name}'. Built-in profiles: {', '.join(BUILTIN)}.")
    return load_profile(BUILTIN[key])
