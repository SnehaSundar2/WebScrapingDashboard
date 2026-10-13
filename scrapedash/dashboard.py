"""Dashboards: terminal text views and a self-contained HTML page.

Chart conventions (kept consistent across every chart):
  * one series per chart, drawn in one validated colour; the title names the series
  * thin bars (max 24 units) with a rounded data-end, square at the baseline, 2-unit gaps
  * solid hairline gridlines; text always in text colours, never the series colour
  * every chart has a "show as table" view, and every bar a hover/focus tooltip
  * yes/no fields are shown as a stat tile, not a two-slice chart
"""

import html
import math
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import analysis
from .exceptions import StorageError

WIDTH = 78
BLOCK = "█"


# ====================================================================== formatting helpers
def fmt_value(value, field=None, unit=""):
    if value is None or value == []:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if field is not None and field.type == "money":
        return analysis.money(value, unit)
    if isinstance(value, Decimal):
        return f"{value:,}"
    return str(value)


def _bin_label(lo, hi, unit=""):
    def n(x):
        return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}".rstrip("0").rstrip(".")
    return f"{unit}{n(lo)}–{n(hi)}"


def _bar(value, top, width=28):
    if not top:
        return ""
    return BLOCK * max(1 if value else 0, round(width * value / top))


def _short(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ====================================================================== terminal
def format_table(rows, columns, right=()):
    if not rows:
        return "  Nothing to show."
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    cell = lambda c, v: str(v).rjust(widths[c]) if c in right else str(v).ljust(widths[c])
    lines = ["  " + "  ".join(cell(c, c.upper()) for c in columns),
             "  " + "  ".join("-" * widths[c] for c in columns)]
    lines += ["  " + "  ".join(cell(c, r.get(c, "")) for c in columns) for r in rows]
    return "\n".join(lines)


def _field_lines(name, f, s, unit):
    out = [f"  {analysis.humanize(name)} ({f.type}) — {s['filled']} filled, {s['missing']} missing"]
    if f.type in ("number", "money", "count") and s.get("stats"):
        st = s["stats"]
        show = (lambda x: analysis.money(x, unit)) if f.type == "money" else (lambda x: f"{x:,}")
        out.append(f"     min {show(st['min'])} · max {show(st['max'])} · mean {show(st['mean'])} · "
                   f"median {show(st['median'])} · std dev {show(st['stdev'])}")
        top = max(c for _, _, c in s["histogram"])
        for lo, hi, count in s["histogram"]:
            out.append(f"     {_bin_label(lo, hi, unit if f.type == 'money' else ''):>14}  {_bar(count, top)} {count}")
    elif f.type == "rating" and s.get("stats"):
        top = max(c for _, c in s["distribution"])
        for stars, count in s["distribution"]:
            out.append(f"     {stars}★  {_bar(count, top)} {count}")
        out.append(f"     average {s['stats']['mean']}")
    elif f.type == "bool":
        total = s["true"] + s["false"]
        out.append(f"     yes {s['true']} · no {s['false']}" + (f" ({100 * s['true'] // total}% yes)" if total else ""))
    elif f.type in ("category", "list") and s.get("top"):
        top = s["top"][0][1]
        label_w = min(24, max(len(str(v)) for v, _ in s["top"][:8]))
        for value, count in s["top"][:8]:
            out.append(f"     {_short(value, 24):<{label_w}}  {_bar(count, top, 24)} {count}")
        out.append(f"     {s['distinct']} different value(s)")
    elif f.type == "text":
        out.append(f"     average length {s['average_length']} characters (longest {s['longest']})")
        if s["top_words"]:
            out.append("     frequent words: " + ", ".join(f"{w} ({c})" for w, c in s["top_words"][:8]))
    elif f.type == "url":
        out.append(f"     {s['distinct']} distinct link(s)")
    return out


def render_terminal(run):
    p = run.profile
    summaries = analysis.summarize(run)
    q = analysis.quality(run)
    out = ["=" * WIDTH,
           f"  RUN #{run.id} · {p.name} · {run.mode.upper()} · {run.started.replace('T', ' ')}",
           f"  {p.description}" if p.description else "",
           f"  {run.start_url}",
           f"  {len(run.pages)} page(s) · {len(run.items)} item(s) · {run.duplicates} duplicate(s) removed · "
           f"{run.duration:.1f} s · {run.status} ({run.stop_reason})",
           "=" * WIDTH, "", "  INSIGHTS"]
    out += [f"   • {line}" for line in analysis.insights(run, summaries)]
    out += ["", f"  DATA QUALITY — completeness {q['completeness']}%",
            format_table([{"field": f["field"], "type": f["type"], "filled": f["filled"], "missing": f["missing"],
                           "filled %": f"{f['percent']}%"} for f in q["fields"]],
                         ["field", "type", "filled", "missing", "filled %"], right={"filled", "missing", "filled %"}),
            "", "  FIELDS"]
    for name, f in p.fields.items():
        out += _field_lines(name, f, summaries[name], run.units.get(name, ""))
    money_fields = [f for f in p.fields.values() if f.type in ("money", "number")]
    if money_fields and run.items:
        mf = money_fields[0]
        unit = run.units.get(mf.name, "")
        rows = [{"#": i, p.label: _short(item.get(p.label), 40), mf.name: fmt_value(item.get(mf.name), mf, unit)}
                for i, item in enumerate(analysis.top_items(run, mf.name, 5), 1)]
        out += ["", f"  TOP 5 BY {mf.name.upper()}", format_table(rows, ["#", p.label, mf.name], right={mf.name})]
    if run.warnings or run.errors:
        out += ["", f"  PROBLEMS ({len(run.errors)} error(s), {len(run.warnings)} warning(s))"]
        out += [f"   ✖ {e}" for e in run.errors] + [f"   ! {w}" for w in run.warnings[:15]]
        if len(run.warnings) > 15:
            out.append(f"   … and {len(run.warnings) - 15} more warning(s)")
    out.append("=" * WIDTH)
    return "\n".join(line for line in out if line is not None)


def render_comparison(old, new, diff):
    p = new.profile
    out = [f"  CHANGES FROM RUN #{old.id} ({old.started[:16].replace('T', ' ')}) TO RUN #{new.id} "
           f"({new.started[:16].replace('T', ' ')})",
           f"  {len(diff['added'])} new · {len(diff['removed'])} removed · {len(diff['changed'])} changed value(s) · "
           f"{diff['unchanged']} unchanged"]
    for name, n in diff["numeric"].items():
        out.append(f"  {analysis.humanize(name)}: {n['up']} went up, {n['down']} went down "
                   f"(average change {n['average_change_pct']:+.1f}%)")
    if diff["changed"]:
        rows = []
        for c in diff["changed"][:25]:
            f = p.fields[c["field"]]
            unit = new.units.get(c["field"], "")
            arrow = ""
            if f.type in ("money", "number", "count") and c["old"] is not None and c["new"] is not None:
                arrow = "▲" if c["new"] > c["old"] else "▼"
            rows.append({"item": _short(c["label"], 34), "field": c["field"], "before": fmt_value(c["old"], f, unit),
                         "after": f"{fmt_value(c['new'], f, unit)} {arrow}".strip()})
        out += ["", format_table(rows, ["item", "field", "before", "after"])]
    for title, items in (("NEW", diff["added"]), ("REMOVED", diff["removed"])):
        if items:
            out += ["", f"  {title}: " + "; ".join(_short(i.get(p.label), 40) for i in items[:10])
                    + (" …" if len(items) > 10 else "")]
    return "\n".join(out)


def render_page_report(report):
    r = report
    out = ["=" * WIDTH, f"  PAGE REPORT — {_short(r['url'], WIDTH - 16)}",
           f"  HTTP {r['status']} · {r['size_kb']} KB · {r['load_ms']} ms{' (cached)' if r['from_cache'] else ''}"
           f" · quality score {r['score']}/100", "=" * WIDTH,
           f"  Title        {r['title'] or '—'} ({len(r['title'])} chars)",
           f"  Description  {_short(r['description'], 60) or '—'} ({len(r['description'])} chars)",
           f"  Language     {r['lang'] or '—'}",
           f"  Words        {r['word_count']:,}",
           f"  Links        {r['internal_links']} internal · {r['external_links']} external · "
           f"{r['nofollow_links']} nofollow · {r['other_links']} email/phone/other",
           f"  Images       {r['images']} ({r['images_missing_alt']} without alt text)", "", "  HEADINGS"]
    out += [f"   {tag.upper()}  {_short(text, 66)}" for tag, text in r["headings"][:12]] or ["   none"]
    if r["top_words"]:
        out += ["", "  FREQUENT WORDS", "   " + ", ".join(f"{w} ({c})" for w, c in r["top_words"])]
    if r["external_domains"]:
        out += ["", "  LINKED SITES", "   " + ", ".join(f"{d} ({c})" for d, c in r["external_domains"])]
    out += ["", "  ISSUES"] + ([f"   ! {i}" for i in r["issues"]] or ["   ✔ No common issues found."])
    out.append("=" * WIDTH)
    return "\n".join(out)


# ====================================================================== HTML
CSS = """
.dash{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--series:#2a78d6;--border:rgba(11,11,11,.10);--good:#0ca30c;--warning:#fab219;
--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .dash{color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--series:#3987e5;
--border:rgba(255,255,255,.10)}}
:root[data-theme="dark"] .dash{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--series:#3987e5;--border:rgba(255,255,255,.10)}
*{box-sizing:border-box}html,body{margin:0}
body.dash{background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:24px;margin:0}h2{font-size:17px;margin:0 0 4px}h3{font-size:15px;margin:0 0 2px}
.sub{color:var(--ink2);font-size:13px}.muted{color:var(--muted)}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--border);
color:var(--ink2);margin-left:6px;vertical-align:2px}
section{margin-top:28px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px}
.tile .label{color:var(--ink2);font-size:13px}.tile .value{font-size:26px;font-weight:600;line-height:1.2}
.tile.hero .value{font-size:48px}.tile .note{color:var(--muted);font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;margin-top:12px}
.stats{color:var(--ink2);font-size:13px;margin:2px 0 8px}
svg.chart{width:100%;height:auto;display:block;overflow:visible}
svg.chart text{fill:var(--muted);font-size:13px;font-family:inherit}
svg.chart .label{fill:var(--ink2)}svg.chart .value{fill:var(--ink);font-weight:600}
svg.chart .gridline{stroke:var(--grid);stroke-width:1}svg.chart .baseline{stroke:var(--axis);stroke-width:1}
.bar{fill:var(--series);outline:none}.bar:hover,.bar:focus-visible{fill-opacity:.75}
.bar:focus-visible{stroke:var(--ink);stroke-width:1.5}
ul.insights{margin:8px 0 0;padding-left:20px}ul.insights li{margin:4px 0}
details.tv{margin-top:8px}details.tv summary{cursor:pointer;color:var(--ink2);font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.status{white-space:nowrap}.status i{font-style:normal;font-weight:700;margin-right:4px}
.status.good i{color:var(--good)}.status.warning i{color:var(--warning)}.status.critical i{color:var(--critical)}
a{color:inherit}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);
border-radius:8px;padding:6px 10px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:10;max-width:280px}
#tip b{display:block;font-size:15px}
footer{margin-top:32px;color:var(--muted);font-size:12px}
@media (max-width:520px){.tile.hero .value{font-size:40px}.grid{grid-template-columns:1fr}}
"""

TOOLTIP_JS = """
(function(){var tip=document.getElementById('tip');
function show(el,x,y){tip.textContent='';var b=document.createElement('b');b.textContent=el.getAttribute('data-value');
var s=document.createElement('span');s.textContent=el.getAttribute('data-label');tip.appendChild(b);tip.appendChild(s);
tip.style.display='block';var w=tip.offsetWidth;tip.style.left=Math.min(x+14,window.innerWidth-w-8)+'px';tip.style.top=(y+14)+'px';}
function hide(){tip.style.display='none';}
document.querySelectorAll('[data-value]').forEach(function(el){
el.addEventListener('pointermove',function(e){show(el,e.clientX,e.clientY);});el.addEventListener('pointerleave',hide);
el.addEventListener('focus',function(){var r=el.getBoundingClientRect();show(el,r.right,r.top);});el.addEventListener('blur',hide);});})();
"""


def _e(value):
    return html.escape(str(value), quote=True)


def _nice_max(value):
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def _round_top_rect(x, y, w, h, r=4):
    """Column path: rounded corners at the top (data end), square at the baseline."""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}"
            f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def _round_end_rect(x, y, w, h, r=4):
    """Horizontal bar path: square at the baseline (left), rounded at the data end (right)."""
    r = min(r, h / 2, w)
    return (f"M{x:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h - r:.1f}"
            f"Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z")


def column_chart(points, aria):
    """points: [(label, value)] -> SVG columns with y-gridlines; only the tallest column is direct-labelled."""
    w, h, left, right, top, bottom = 400, 236, 34, 6, 20, 40
    pw, ph = w - left - right, h - top - bottom
    vmax = _nice_max(max((v for _, v in points), default=0))
    band = pw / max(len(points), 1)
    bar_w = min(24, band - 2)
    tallest = max(range(len(points)), key=lambda i: points[i][1]) if points else -1
    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(aria)}">']
    for k in range(5):
        value = vmax * k / 4
        y = top + ph - ph * k / 4
        parts.append(f'<line class="{"baseline" if k == 0 else "gridline"}" x1="{left}" x2="{w - right}" '
                     f'y1="{y:.1f}" y2="{y:.1f}"/><text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">'
                     f'{value:g}</text>')
    for i, (label, value) in enumerate(points):
        x = left + band * i + (band - bar_w) / 2
        bh = ph * value / vmax if vmax else 0
        y = top + ph - bh
        if value:
            parts.append(f'<path class="bar" tabindex="0" d="{_round_top_rect(x, y, bar_w, bh)}" '
                         f'data-value="{_e(value)}" data-label="{_e(label)}" aria-label="{_e(label)}: {_e(value)}"/>')
        parts.append(f'<text class="label" x="{x + bar_w / 2:.1f}" y="{h - bottom + 20}" text-anchor="middle">{_e(label)}</text>')
        if i == tallest and value:
            parts.append(f'<text class="value" x="{x + bar_w / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle">{_e(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(points, aria):
    """points: [(label, value)] -> ranked horizontal bars with the value at each bar's tip."""
    w, row, label_w, right = 400, 28, 128, 40
    h = row * len(points) + 8
    vmax = max((v for _, v in points), default=0) or 1
    pw = w - label_w - right
    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(aria)}">',
             f'<line class="baseline" x1="{label_w}" x2="{label_w}" y1="0" y2="{h - 4}"/>']
    for i, (label, value) in enumerate(points):
        y = 4 + i * row
        bw = max(pw * value / vmax, 2)
        parts.append(f'<text class="label" x="{label_w - 8}" y="{y + 18}" text-anchor="end">{_e(_short(label, 16))}</text>'
                     f'<path class="bar" tabindex="0" d="{_round_end_rect(label_w, y + 6, bw, 16)}" '
                     f'data-value="{_e(value)}" data-label="{_e(label)}" aria-label="{_e(label)}: {_e(value)}"/>'
                     f'<text class="value" x="{label_w + bw + 6:.1f}" y="{y + 18}">{_e(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(headers, rows, numeric=()):
    head = "".join(f'<th class="{"num" if i in numeric else ""}">{_e(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"num" if i in numeric else ""}">{cell}</td>'
                                    for i, cell in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _table_view(headers, rows, numeric=(1,)):
    return f'<details class="tv"><summary>Show as table</summary>{_table(headers, [[_e(c) for c in r] for r in rows], numeric)}</details>'


def _status(percent):
    if percent >= 95:
        return '<span class="status good"><i aria-hidden="true">✔</i>Good</span>'
    if percent >= 80:
        return '<span class="status warning"><i aria-hidden="true">▲</i>Check</span>'
    return '<span class="status critical"><i aria-hidden="true">✖</i>Poor</span>'


def _tile(label, value, note="", hero=False):
    return (f'<div class="card tile{" hero" if hero else ""}"><div class="label">{_e(label)}</div>'
            f'<div class="value">{_e(value)}</div>' + (f'<div class="note">{_e(note)}</div>' if note else "") + "</div>")


def _link(url, text=None):
    if not url or not str(url).startswith(("http://", "https://")):
        return _e(text or url or "—")
    return f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer nofollow">{_e(text or _short(url, 48))}</a>'


def _field_card(name, f, s, unit):
    title = analysis.humanize(name).capitalize()
    if f.type in ("number", "money", "count") and s.get("stats"):
        st = s["stats"]
        show = (lambda x: analysis.money(x, unit)) if f.type == "money" else (lambda x: f"{x:,}")
        points = [(_bin_label(lo, hi), c) for lo, hi, c in s["histogram"]]  # unit goes in the title, labels stay short
        stats = (f"min {show(st['min'])} · max {show(st['max'])} · mean {show(st['mean'])} · "
                 f"median {show(st['median'])}")
        unit_note = f" ({unit})" if f.type == "money" and unit else ""
        return (f'<div class="card"><h3>{_e(title)} distribution{_e(unit_note)}</h3><div class="stats">{_e(stats)}</div>'
                f'{column_chart(points, f"{title}: number of items per range")}'
                f'{_table_view(["Range", "Items"], points)}</div>')
    if f.type == "rating" and s.get("stats"):
        points = [(f"{stars}★", c) for stars, c in s["distribution"]]
        return (f'<div class="card"><h3>{_e(title)} distribution</h3><div class="stats">average '
                f'{_e(s["stats"]["mean"])} · {s["filled"]} rated</div>'
                f'{column_chart(points, f"{title}: items per star rating")}{_table_view(["Rating", "Items"], points)}</div>')
    if f.type in ("category", "list") and s.get("top"):
        points = s["top"][:10]
        what = "values" if f.type == "category" else "tags"
        return (f'<div class="card"><h3>Top {_e(analysis.humanize(name))}</h3><div class="stats">{s["distinct"]} different '
                f'{what}' + (f' · {s["average_per_item"]} per item' if f.type == "list" else "") + '</div>'
                f'{bar_chart(points, f"Most frequent {title}")}{_table_view([title, "Items"], points)}</div>')
    if f.type == "text" and s.get("top_words"):
        points = s["top_words"][:8]
        return (f'<div class="card"><h3>Frequent words in {_e(analysis.humanize(name))}</h3><div class="stats">average '
                f'{s["average_length"]} characters · longest {s["longest"]}</div>'
                f'{bar_chart(points, f"Most frequent words in {title}")}{_table_view(["Word", "Count"], points)}</div>')
    return ""


def render_html(run, previous=None, diff=None):
    p = run.profile
    summaries = analysis.summarize(run)
    q = analysis.quality(run)
    generated = datetime.now().strftime("%d %b %Y, %H:%M")
    body = [f'<header><h1>Web Scraping Dashboard<span class="badge">{_e(run.mode)}</span></h1>'
            f'<div class="sub">Run #{run.id} · {_e(p.name)} · {_e(run.started.replace("T", " "))} · '
            f'{_link(run.start_url, run.start_url)}</div>'
            + (f'<div class="sub">{_e(p.description)}</div>' if p.description else "") + '</header>']

    tiles = [_tile("Items collected", f"{len(run.items):,}", f"{run.status} — {run.stop_reason}", hero=True),
             _tile("Pages scraped", len(run.pages), f"{sum(1 for pg in run.pages if pg['from_cache'])} from cache"),
             _tile("Data completeness", f"{q['completeness']}%", f"{len(p.fields)} fields"),
             _tile("Duplicates removed", run.duplicates),
             _tile("Warnings", len(run.warnings), f"{len(run.errors)} error(s)"),
             _tile("Duration", f"{run.duration:.1f} s")]
    for name, f in p.fields.items():
        s = summaries[name]
        if f.type == "bool" and s["true"] + s["false"]:
            pct = 100 * s["true"] // (s["true"] + s["false"])
            tiles.append(_tile(analysis.humanize(name).capitalize(), f"{pct}%", f"{s['true']} yes · {s['false']} no"))
    body.append(f'<section aria-label="Summary"><div class="tiles">{"".join(tiles)}</div></section>')

    body.append('<section class="card"><h2>Insights</h2><ul class="insights">'
                + "".join(f"<li>{_e(line)}</li>" for line in analysis.insights(run, summaries)) + "</ul></section>")

    cards = [c for c in (_field_card(n, f, summaries[n], run.units.get(n, "")) for n, f in p.fields.items()) if c]
    if cards:
        body.append(f'<section><h2>Fields</h2><div class="grid">{"".join(cards)}</div></section>')

    rating = next((f for f in p.fields.values() if f.type == "rating"), None)
    money_field = next((f for f in p.fields.values() if f.type in ("money", "number")), None)
    if money_field and run.items:
        unit = run.units.get(money_field.name, "")
        blocks = []
        for title, highest in (("Highest", True), ("Lowest", False)):
            rows = [[_link(i.get("url") if "url" in p.fields else None, _short(i.get(p.label), 60)),
                     _e(fmt_value(i.get(money_field.name), money_field, unit))]
                    for i in analysis.top_items(run, money_field.name, 5, highest)]
            blocks.append(f'<div class="card"><h3>{title} {_e(analysis.humanize(money_field.name))}</h3>'
                          f'{_table([p.label.capitalize(), money_field.name.capitalize()], rows, numeric=(1,))}</div>')
        if rating:
            rows = [[f"{g}★", _e(analysis.money(avg, unit)), str(n)]
                    for g, avg, n in analysis.group_means(run.items, rating.name, money_field.name)]
            blocks.append(f'<div class="card"><h3>Average {_e(analysis.humanize(money_field.name))} by '
                          f'{_e(analysis.humanize(rating.name))}</h3>'
                          f'{_table(["Rating", "Average", "Items"], rows, numeric=(1, 2))}</div>')
        body.append(f'<section><h2>Rankings</h2><div class="grid">{"".join(blocks)}</div></section>')

    if previous is not None and diff is not None:
        ctiles = [_tile("New items", len(diff["added"])), _tile("Removed items", len(diff["removed"])),
                  _tile("Changed values", len(diff["changed"])), _tile("Unchanged items", diff["unchanged"])]
        for name, n in diff["numeric"].items():
            ctiles.append(_tile(f"{analysis.humanize(name).capitalize()} changes", f"{n['up']} ▲ · {n['down']} ▼",
                                f"average {n['average_change_pct']:+.1f}%"))
        rows = []
        for c in diff["changed"][:40]:
            f = p.fields[c["field"]]
            unit = run.units.get(c["field"], "")
            trend = ""
            if f.type in ("money", "number", "count") and c["old"] is not None and c["new"] is not None:
                trend = "▲ up" if c["new"] > c["old"] else "▼ down"  # neutral: whether up is good depends on the field
            rows.append([_e(_short(c["label"], 50)), _e(c["field"]), _e(fmt_value(c["old"], f, unit)),
                         _e(fmt_value(c["new"], f, unit)), trend])
        listing = "".join(f'<p class="sub"><b>{t}:</b> ' + _e("; ".join(_short(i.get(p.label), 40) for i in items[:12]))
                          + ("…" if len(items) > 12 else "") + "</p>"
                          for t, items in (("New", diff["added"]), ("Removed", diff["removed"])) if items)
        body.append(f'<section><h2>Changes since run #{previous.id} '
                    f'<span class="muted">({_e(previous.started.replace("T", " "))})</span></h2>'
                    f'<div class="tiles">{"".join(ctiles)}</div><div class="card" style="margin-top:12px">'
                    + (f'<div class="scroll">{_table(["Item", "Field", "Before", "After", ""], rows, numeric=(2, 3))}</div>'
                       if rows else '<p class="sub">No values changed.</p>') + listing + "</div></section>")

    qrows = [[_e(f["field"]), _e(f["type"]), str(f["filled"]), str(f["missing"]), f"{f['percent']}%", _status(f["percent"])]
             for f in q["fields"]]
    body.append(f'<section class="card"><h2>Data quality</h2><div class="sub">Completeness {q["completeness"]}% · '
                f'{q["skipped"]} item(s) skipped · {run.duplicates} duplicate(s) removed</div>'
                f'<div class="scroll">{_table(["Field", "Type", "Filled", "Missing", "Filled %", "Status"], qrows, numeric=(2, 3, 4))}</div></section>')

    cols = list(p.fields)
    item_rows = [[_link(i.get(c)) if p.fields[c].type == "url" else _e(fmt_value(i.get(c), p.fields[c], run.units.get(c, "")))
                  for c in cols] for i in run.items[:100]]
    numeric_cols = tuple(k for k, c in enumerate(cols) if p.fields[c].type in ("money", "number", "count", "rating"))
    body.append(f'<section class="card"><h2>Items</h2><div class="sub">Showing {min(100, len(run.items))} of '
                f'{len(run.items)} — export to CSV for the full data</div>'
                f'<div class="scroll">{_table([c.replace("_", " ") for c in cols], item_rows, numeric=numeric_cols)}</div></section>')

    prow = [[str(k), _link(pg["url"]), str(pg["status"]), str(pg["items"]), "yes" if pg["from_cache"] else "no",
             f'{pg["elapsed"]:.2f} s'] for k, pg in enumerate(run.pages, 1)]
    problems = "".join(f"<li><b>Error:</b> {_e(e)}</li>" for e in run.errors) + \
        "".join(f"<li>{_e(w)}</li>" for w in run.warnings[:50])
    body.append(f'<section class="card"><h2>Pages and problems</h2><div class="scroll">'
                f'{_table(["#", "Page", "HTTP", "Items", "Cached", "Time"], prow, numeric=(2, 3, 5))}</div>'
                + (f'<h3 style="margin-top:12px">Warnings and errors</h3><ul class="insights">{problems}</ul>'
                   if problems else '<p class="sub">No warnings or errors.</p>') + "</section>")

    body.append(f'<footer>Generated {generated} by Web Scraping Dashboard · scraped politely '
                f'(robots.txt respected, requests rate-limited) · developed by Sneha S</footer>')
    title = f"Scrape dashboard – {p.name} #{run.id}"
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(title)}</title><style>{CSS}</style></head><body class='dash'><main>"
            + "\n".join(body) + f"</main><div id='tip' role='status' aria-live='polite'></div><script>{TOOLTIP_JS}</script>"
            "</body></html>")


def save_html(run, path, previous=None, diff=None):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_html(run, previous, diff), encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not write {path}: {exc.strerror or exc}") from exc
    return path
