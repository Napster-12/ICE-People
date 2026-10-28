"""Append-only audit trail."""
from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def _clean(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: (v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v))
                for k, v in value.items()}
    return {"value": str(value)}


def record(action, entity=None, entity_id=None, before=None, after=None, detail=None, user=None):
    """Add an audit entry to the current session (committed with the caller's work)."""
    if user is None and has_request_context() and current_user and current_user.is_authenticated:
        user = current_user
    ip = None
    if has_request_context():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip() or None
    entry = AuditLog(
        user_id=getattr(user, "id", None), username=getattr(user, "username", None), ip=ip,
        action=action, entity=entity, entity_id=str(entity_id) if entity_id is not None else None,
        before=_clean(before), after=_clean(after), detail=(detail or "")[:500] or None,
    )
    db.session.add(entry)
    return entry


def changes(before, after):
    """Only the fields that changed, as (before, after) dicts."""
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}
