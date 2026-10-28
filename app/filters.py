"""Jinja filters (most carried over from the original portal)."""
import re
from datetime import datetime

from markupsafe import Markup, escape

from app.services.dates import _as_datetime, format_date, format_datetime, format_money, today


def initials(name):
    parts = (name or "?").split()
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def score_class(score):
    score = score or 0
    if score >= 75:
        return "high"
    if score >= 50:
        return "mid"
    return "low"


def longdate(value):
    """2026-10-27 -> Tuesday, 27 October 2026 (as on the hiring posters)."""
    d = _as_datetime(value)
    return f"{d:%A}, {d.day} {d:%B %Y}" if d else (value or "")


def jobdesc(text):
    """Plain-text job ad as HTML: ALL-CAPS lines become headings, '•' / '-' lines
    become bullets, and a short line before a list becomes a sub-heading."""
    lines = [l.strip() for l in (text or "").splitlines()]
    html, bullets = [], []

    def flush():
        if bullets:
            html.append("<ul>" + "".join(f"<li>{escape(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for i, line in enumerate(lines):
        nxt = next((l for l in lines[i + 1:] if l), "")
        if line[:1] in ("•", "-", "*") and len(line) > 1:
            bullets.append(line[1:].strip())
            continue
        flush()
        if not line:
            continue
        if line.isupper() and len(line) < 60:
            html.append(f"<h3>{escape(line.title())}</h3>")
        elif nxt[:1] in ("•", "-", "*") and len(line) < 70 and not line.endswith((".", ":")):
            html.append(f"<h4>{escape(line)}</h4>")
        else:
            html.append(f"<p>{escape(line)}</p>")
    flush()
    return Markup("".join(html))


def ago(value):
    d = _as_datetime(value)
    if d is None:
        return ""
    days = (today() - d.date()).days
    if days <= 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    if days < 30:
        return f"Posted {days} days ago"
    return "Posted " + format_date(d)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def isodate(value):
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat() if value else ""


def register(app):
    app.add_template_filter(initials)
    app.add_template_filter(score_class)
    app.add_template_filter(format_date, "dt")
    app.add_template_filter(format_datetime, "dtt")
    app.add_template_filter(longdate)
    app.add_template_filter(jobdesc)
    app.add_template_filter(ago)
    app.add_template_filter(format_money, "money")
    app.add_template_filter(slug)
    app.add_template_filter(isodate)
