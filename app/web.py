"""Small view helpers shared by every blueprint."""
from flask import flash, redirect, request, url_for


def paginate(items, per_page=25):
    """Paginate a SQLAlchemy query or a list for the current ?page=.
    Returns (page_items, pager) where pager matches templates/_pager.html."""
    is_query = hasattr(items, "limit")
    total = items.order_by(None).count() if is_query else len(items)
    pages = max(1, -(-total // per_page))
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    start = (page - 1) * per_page
    rows = items.limit(per_page).offset(start).all() if is_query else items[start:start + per_page]
    args = {k: v for k, v in request.args.items() if k != "page"}
    endpoint, view_args = request.endpoint, dict(request.view_args or {})
    return rows, {
        "page": page, "pages": pages, "total": total, "start": start,
        "first": start + 1 if total else 0, "last": min(start + per_page, total),
        "url": lambda n: url_for(endpoint, **view_args, **args, page=n),
    }


def back(default_endpoint, **kwargs):
    target = request.referrer
    if not target or not target.startswith(request.host_url):
        target = url_for(default_endpoint, **kwargs)
    return redirect(target)


def flash_errors(errors):
    for e in errors:
        flash(e, "error")
