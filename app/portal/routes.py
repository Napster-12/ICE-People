"""Employee self-service: my profile, my notifications, and permission-checked file downloads."""
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import Notification, StoredFile
from app.services import audit, files
from app.services.dates import now
from app.web import paginate

bp = Blueprint("portal", __name__)


@bp.route("/me")
@roles_required()
def me():
    return render_template("portal/me.html", emp=current_user.employee)


@bp.route("/me/theme", methods=["POST"])
@roles_required()
def theme():
    """Settings > Appearance (16 Nov 2026, from IGSP): light or dark, saved on the account. JSON for the page's
    instant switch; a redirect without JavaScript."""
    from flask import jsonify
    from app.models.user import THEMES
    choice = request.form.get("theme", "")
    wants_json = "application/json" in request.headers.get("Accept", "")
    if choice not in THEMES:
        if wants_json:
            return jsonify(ok=False, error="Unknown theme."), 400
        flash("Choose light or dark.", "error")
        return redirect(url_for("portal.me"))
    current_user.theme = choice
    db.session.commit()
    if wants_json:
        return jsonify(ok=True, theme=choice)
    flash(f"{THEMES[choice]} mode is on.", "success")
    return redirect(url_for("portal.me"))


@bp.route("/notifications")
@roles_required()
def notifications():
    q = Notification.query.filter_by(user_id=current_user.id)
    if request.args.get("unread"):
        q = q.filter(Notification.read_at.is_(None))
    rows, pager = paginate(q.order_by(Notification.created_at.desc()), 25)
    return render_template("portal/notifications.html", rows=rows, pager=pager, args=request.args)


@bp.route("/notifications/<int:note_id>")
@roles_required()
def open_notification(note_id):
    note = db.session.get(Notification, note_id) or abort(404)
    if note.user_id != current_user.id:
        abort(403)
    if note.read_at is None:
        note.read_at = now()
        db.session.commit()
    link = note.link or ""
    return redirect(link if link.startswith("/") and not link.startswith("//") else url_for("portal.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@roles_required()
def read_all():
    Notification.query.filter_by(user_id=current_user.id, read_at=None).update({"read_at": now()})
    db.session.commit()
    return redirect(url_for("portal.notifications"))


@bp.route("/files/<int:file_id>")
@roles_required()
def download(file_id):
    stored = db.session.get(StoredFile, file_id) or abort(404)
    if not files.can_download(current_user, stored):
        audit.record("file.download_denied", stored.entity_type, stored.entity_id, after={"file_id": stored.id})
        db.session.commit()
        abort(403)
    audit.record("file.download", stored.entity_type, stored.entity_id, after={"file_id": stored.id})
    db.session.commit()
    inline = stored.content_type in ("application/pdf", "image/png", "image/jpeg") and not request.args.get("download")
    return Response(files.read(stored), mimetype=stored.content_type,
                    headers={"Content-Disposition": f'{"inline" if inline else "attachment"}; '
                                                    f'filename="{stored.original_name}"',
                             "X-Content-Type-Options": "nosniff"})
