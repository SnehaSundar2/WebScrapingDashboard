"""Data processing for scrape runs: statistics, distributions, data quality,
run-to-run comparison and plain-English insights."""

import math
import re
import statistics
from collections import Counter, defaultdict
from decimal import Decimal

STOPWORDS = set("""a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most my
myself no nor not now of off on once only or other our ours ourselves out over own same she should so some
such than that the their theirs them themselves then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your yours yourself
yourselves s t don can't won't it's i'm you're isn't""".split())
WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]+")


def humanize(name):
    return name.replace("_", " ")


def money(value, symbol=""):
    return f"{symbol}{value:,.2f}"


# ------------------------------------------------------------------ numbers
def numeric_stats(values):
    values = [Decimal(v) for v in values]
    if not values:
        return None
    mean = sum(values) / len(values)
    return {"count": len(values), "min": min(values), "max": max(values), "total": sum(values),
            "mean": mean.quantize(Decimal("0.01")), "median": Decimal(statistics.median(values)).quantize(Decimal("0.01")),
            "stdev": Decimal(statistics.pstdev([float(v) for v in values])).quantize(Decimal("0.01"))}


def _nice_step(span, target_bins):
    raw = span / target_bins
    magnitude = 10 ** math.floor(math.log10(raw))
    for nice in (1, 2, 2.5, 5, 10):
        if raw <= nice * magnitude:
            return nice * magnitude
    return 10 * magnitude


def histogram(values, target_bins=8):
    """Bins with 'nice' edges (e.g. 10-20, 20-30): list of (low, high, count)."""
    nums = [float(v) for v in values]
    if not nums:
        return []
    lo, hi = min(nums), max(nums)
    if lo == hi:
        return [(lo, hi, len(nums))]
    step = _nice_step(hi - lo, target_bins)
    start = math.floor(lo / step) * step
    bins = []
    edge = start
    while edge <= hi:
        bins.append([round(edge, 10), round(edge + step, 10), 0])
        edge += step
    for n in nums:
        index = min(int((n - start) // step), len(bins) - 1)
        bins[index][2] += 1
    return [tuple(b) for b in bins]


# ------------------------------------------------------------------ per-field summaries
def summarize_field(items, f, units=None):
    values = [item.get(f.name) for item in items]
    present = [x for x in values if x is not None and x != []]
    summary = {"type": f.type, "filled": len(present), "missing": len(values) - len(present)}
    if f.type in ("number", "money", "count"):
        summary["stats"] = numeric_stats(present)
        summary["histogram"] = histogram(present)
        summary["unit"] = (units or {}).get(f.name, "")
    elif f.type == "rating":
        summary["stats"] = numeric_stats(present)
        counts = Counter(int(x) for x in present)
        summary["distribution"] = [(stars, counts.get(stars, 0)) for stars in range(1, 6)]
    elif f.type == "bool":
        summary["true"] = sum(1 for x in present if x)
        summary["false"] = len(present) - summary["true"]
    elif f.type == "category":
        counts = Counter(present)
        summary["distinct"] = len(counts)
        summary["top"] = counts.most_common(10)
    elif f.type == "list":
        counts = Counter(v for lst in present for v in lst)
        summary["distinct"] = len(counts)
        summary["top"] = counts.most_common(15)
        summary["average_per_item"] = round(sum(len(x) for x in present) / len(present), 1) if present else 0
    elif f.type == "text":
        lengths = [len(x) for x in present]
        summary["average_length"] = round(sum(lengths) / len(lengths), 1) if lengths else 0
        summary["longest"] = max(lengths, default=0)
        words = Counter(w.lower().strip("'-") for x in present for w in WORD.findall(x))
        summary["top_words"] = [(w, n) for w, n in words.most_common(40)
                                if w not in STOPWORDS and len(w) > 2][:10]
    elif f.type == "url":
        summary["distinct"] = len(set(present))
    return summary


def summarize(run):
    return {name: summarize_field(run.items, f, run.units) for name, f in run.profile.fields.items()}


def group_means(items, group_field, value_field):
    """Average of value_field per value of group_field, e.g. average price per star rating."""
    groups = defaultdict(list)
    for item in items:
        g, val = item.get(group_field), item.get(value_field)
        if g is not None and val is not None:
            groups[g].append(Decimal(val))
    return sorted(((g, (sum(vals) / len(vals)).quantize(Decimal("0.01")), len(vals))
                   for g, vals in groups.items()), key=lambda row: row[0])


def top_items(run, field_name, n=5, highest=True):
    with_value = [i for i in run.items if i.get(field_name) is not None]
    return sorted(with_value, key=lambda i: i[field_name], reverse=highest)[:n]


# ------------------------------------------------------------------ data quality
def quality(run):
    total = len(run.items)
    fields = []
    for name, f in run.profile.fields.items():
        filled = sum(1 for item in run.items if item.get(name) not in (None, []))
        fields.append({"field": name, "type": f.type, "filled": filled, "missing": total - filled,
                       "percent": round(100 * filled / total, 1) if total else 0.0})
    cells = total * len(fields)
    completeness = round(100 * sum(f["filled"] for f in fields) / cells, 1) if cells else 0.0
    skipped = sum(1 for w in run.warnings if "skipped" in w)
    issues = []
    for f in fields:
        if total and f["percent"] < 90:
            issues.append(f"'{f['field']}' is missing in {f['missing']} of {total} items.")
    if skipped:
        issues.append(f"{skipped} item(s) were skipped because a required field was missing.")
    if run.duplicates:
        issues.append(f"{run.duplicates} duplicate item(s) were removed.")
    unreadable = sum(1 for w in run.warnings if "could not be read" in w)
    if unreadable:
        issues.append(f"{unreadable} value(s) could not be converted (see warnings).")
    return {"fields": fields, "completeness": completeness, "items": total, "skipped": skipped, "issues": issues}


# ------------------------------------------------------------------ comparison
def compare(old, new):
    """What changed between two runs of the same profile, matched by the profile's key field."""
    key = new.profile.key
    if not key:
        raise ValueError("This profile has no key field, so runs cannot be compared item by item.")
    old_by = {i[key]: i for i in old.items if i.get(key) is not None}
    new_by = {i[key]: i for i in new.items if i.get(key) is not None}
    label = new.profile.label or key
    added = [new_by[k] for k in new_by if k not in old_by]
    removed = [old_by[k] for k in old_by if k not in new_by]
    changed = []
    for k in new_by.keys() & old_by.keys():
        for name in new.profile.fields:
            if name != key and old_by[k].get(name) != new_by[k].get(name):
                changed.append({"key": k, "label": new_by[k].get(label), "field": name,
                                "old": old_by[k].get(name), "new": new_by[k].get(name)})
    changed.sort(key=lambda c: (str(c["label"]), c["field"]))
    numeric = {}
    for f in new.profile.fields.values():
        if f.type in ("money", "number", "count"):
            moves = [c for c in changed if c["field"] == f.name and c["old"] is not None and c["new"] is not None]
            if moves:
                pct = [float((Decimal(c["new"]) - Decimal(c["old"])) / Decimal(c["old"]) * 100)
                       for c in moves if Decimal(c["old"]) != 0]
                numeric[f.name] = {"up": sum(1 for c in moves if c["new"] > c["old"]),
                                   "down": sum(1 for c in moves if c["new"] < c["old"]),
                                   "average_change_pct": round(sum(pct) / len(pct), 1) if pct else 0.0}
    return {"added": added, "removed": removed, "changed": changed, "numeric": numeric,
            "unchanged": len(new_by.keys() & old_by.keys()) - len({c["key"] for c in changed})}


# ------------------------------------------------------------------ insights
def insights(run, summaries=None):
    summaries = summaries or summarize(run)
    found = []
    n = len(run.items)
    if not n:
        return ["No items were collected in this run."]
    found.append(f"{n} item(s) collected from {len(run.pages)} page(s) in {run.duration:.1f} s.")
    for name, s in summaries.items():
        label = humanize(name)
        if s["type"] == "money" and s["stats"]:
            st, sym = s["stats"], s["unit"]
            found.append(f"Average {label} {money(st['mean'], sym)} (median {money(st['median'], sym)}, "
                         f"range {money(st['min'], sym)} – {money(st['max'], sym)}).")
            above = sum(1 for i in run.items if i.get(name) is not None and i[name] > st["mean"])
            found.append(f"{above} of {s['filled']} ({100 * above // s['filled']}%) are above the average {label}.")
        elif s["type"] == "rating" and s["stats"]:
            stars, count = max(s["distribution"], key=lambda d: d[1])
            found.append(f"Most common {label}: {stars} star(s) ({count} of {s['filled']}, "
                         f"{100 * count // s['filled']}%); average {s['stats']['mean']}.")
        elif s["type"] == "bool" and s["filled"]:
            pct = 100 * s["true"] // s["filled"]
            found.append(f"{pct}% have '{label}' = yes ({s['true']} of {s['filled']}).")
        elif s["type"] == "category" and s.get("top"):
            top, count = s["top"][0]
            found.append(f"Most frequent {label}: {top} ({count} of {s['filled']}); {s['distinct']} different in total.")
        elif s["type"] == "list" and s.get("top"):
            found.append(f"Most common {label}: " + ", ".join(f"{v} ({c})" for v, c in s["top"][:3]) + ".")
    ratings = [f for f in run.profile.fields.values() if f.type == "rating"]
    prices = [f for f in run.profile.fields.values() if f.type == "money"]
    if ratings and prices:
        rows = group_means(run.items, ratings[0].name, prices[0].name)
        if len(rows) >= 2:
            low, high = min(rows, key=lambda r: r[1]), max(rows, key=lambda r: r[1])
            sym = run.units.get(prices[0].name, "")
            found.append(f"Average {humanize(prices[0].name)} by {humanize(ratings[0].name)}: lowest "
                         f"{money(low[1], sym)} for {low[0]}-star items, highest {money(high[1], sym)} "
                         f"for {high[0]}-star items.")
    q = quality(run)
    found.extend(q["issues"])
    return found
