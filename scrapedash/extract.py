"""Extracting and cleaning items from a parsed page, according to a profile.

Problems with single fields never stop the whole page: a field that cannot be
converted becomes None and a warning is recorded; an item missing a required
field is skipped (also with a warning).
"""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

CURRENCY = re.compile(r"(£|\$|€|₹|¥|Rs\.?|INR|USD|GBP|EUR)", re.I)
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?|[-+]?\.\d+")
RATING_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
MAX_LIST_ITEMS = 50


def clean_text(raw):
    return " ".join(str(raw or "").split())


def _decimal(text):
    m = NUMBER.search(text or "")
    if not m:
        raise ValueError(f"no number in '{clean_text(text)[:40]}'")
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        raise ValueError(f"'{m.group(0)}' is not a number") from None


def to_money(raw):
    """'£51.77' -> (Decimal('51.77'), '£');  '₹1,299' -> (Decimal('1299'), '₹')."""
    value = _decimal(raw)
    if value < 0:
        raise ValueError("a price cannot be negative")
    m = CURRENCY.search(raw or "")
    return value, (m.group(1) if m else "")


def to_count(raw):
    """'In stock (22 available)' -> 22."""
    m = re.search(r"\d[\d,]*", raw or "")
    if not m:
        raise ValueError(f"no count in '{clean_text(raw)[:40]}'")
    return int(m.group(0).replace(",", ""))


def to_rating(raw):
    """'star-rating Three' -> 3, '4 out of 5' -> 4, '4.5/5' -> 4.5. Must be 0-5."""
    words = re.findall(r"[a-z]+", (raw or "").lower())
    for word in words:
        if word in RATING_WORDS:
            return RATING_WORDS[word]
    value = _decimal(raw)
    if not 0 <= value <= 5:
        raise ValueError(f"rating {value} is not between 0 and 5")
    return int(value) if value == int(value) else value


def to_bool(raw, true_if=""):
    text = clean_text(raw).lower()
    return (true_if in text) if true_if else bool(text)


def to_url(raw, base_url):
    link = clean_text(raw)
    if not link:
        return None
    absolute = urljoin(base_url, link)
    if urlsplit(absolute).scheme not in ("http", "https"):
        raise ValueError(f"'{link[:40]}' is not a web link")
    return absolute


def _raw_value(node, field):
    if field.attr:
        value = node.get(field.attr)
        return None if value is None else value
    return node.text()


def extract_field(item_node, field, base_url, units):
    """Return the cleaned value of one field (None when the element/attribute is absent)."""
    matches = item_node.select(field.select) if field.select else [item_node]
    if field.type == "list":
        values = []
        for node in matches[:MAX_LIST_ITEMS]:
            raw = clean_text(_raw_value(node, field))
            if raw and raw not in values:
                values.append(raw)
        return values
    if not matches:
        return None
    raw = _raw_value(matches[0], field)
    if raw is None:
        return None
    if field.type in ("text", "category"):
        return clean_text(raw) or None
    if field.type == "number":
        return _decimal(raw)
    if field.type == "money":
        value, symbol = to_money(raw)
        if symbol:
            units.setdefault(field.name, symbol)
        return value
    if field.type == "count":
        return to_count(raw)
    if field.type == "rating":
        return to_rating(raw)
    if field.type == "bool":
        return to_bool(raw, field.true_if)
    if field.type == "url":
        return to_url(raw, base_url)
    raise ValueError(f"unknown field type {field.type}")


def extract_items(dom, profile, base_url, page_label="page"):
    """Returns (items, warnings, units). `units` maps money fields to their currency symbol."""
    items, warnings, units = [], [], {}
    for position, node in enumerate(dom.select(profile.item), 1):
        item, missing = {}, []
        for f in profile.fields.values():
            try:
                value = extract_field(node, f, base_url, units)
            except ValueError as exc:
                warnings.append(f"{page_label}, item {position}: '{f.name}' could not be read ({exc}).")
                value = None
            if f.required and (value is None or value == []):
                missing.append(f.name)
            item[f.name] = value
        if missing:
            warnings.append(f"{page_label}, item {position} skipped: required field(s) "
                            f"{', '.join(missing)} missing.")
            continue
        items.append(item)
    return items, warnings, units
