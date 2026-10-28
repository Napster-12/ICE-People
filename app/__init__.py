"""ICE People Administration System (Icebolethu Group): application factory."""
import logging
import os

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app.config import CONFIGS, INSTANCE_DIR
from app.extensions import babel, csrf, db, limiter, login_manager, migrate


def create_app(config_name=None, overrides=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__, instance_path=INSTANCE_DIR)
    app.config.from_object(CONFIGS[config_name])
    app.config.update(overrides or {})
    if not app.config.get("SECRET_KEY") or not app.config.get("FERNET_KEY"):
        raise RuntimeError("SECRET_KEY and FERNET_KEY must be set. Copy .env.example to .env and fill them in "
                           "(see README.md).")
    os.makedirs(app.instance_path, exist_ok=True)
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)
    babel.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = _("Please sign in to continue.")
    login_manager.login_message_category = "info"

    from app import models  # noqa: F401  (register every table)
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        return user if user and user.is_active else None

    _register_blueprints(app)
    _register_template_helpers(app)
    _register_handlers(app)
    _register_file_access()

    from app.cli import register_cli
    register_cli(app)
    return app


def _register_blueprints(app):
    from app.admin.routes import bp as admin_bp
    from app.approvals.routes import bp as approvals_bp
    from app.auth.routes import bp as auth_bp
    from app.budget.routes import bp as budget_bp
    from app.dashboards.routes import bp as dashboards_bp
    from app.portal.routes import bp as portal_bp
    from app.positions.routes import bp as positions_bp
    from app.recruitment.careers import bp as careers_bp
    from app.recruitment.routes import bp as recruitment_bp
    from app.requisitions.routes import bp as requisitions_bp

    for bp in (careers_bp, auth_bp, dashboards_bp, portal_bp, requisitions_bp, positions_bp, approvals_bp, budget_bp,
               recruitment_bp, admin_bp):
        app.register_blueprint(bp)


def _register_template_helpers(app):
    from app import filters
    from app.models.recruitment import APPLICATION_STATUSES, JOB_TYPES
    from app.nav import nav_for
    from app.services import ats
    from app.services.dates import today

    filters.register(app)

    def asset_url(filename):
        """Static URL stamped with the file's modified time, so browsers never use a stale copy."""
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    @app.context_processor
    def inject_globals():
        ctx = {
            "education_levels": ats.EDUCATION_LEVELS,
            "education_labels": ats.EDUCATION_LABELS,
            "statuses": APPLICATION_STATUSES,
            "job_types": JOB_TYPES,
            "current_year": today().year,
            "now_label": f"{today().day} {today():%B %Y}",
            "asset": asset_url,
            "icon": app.jinja_env.get_template("_icons.html").module.icon,
            "is_admin": current_user.is_authenticated,
            "system_name": "ICE People Administration System",
        }
        if current_user.is_authenticated:
            from app.services.notifications import unread_count
            from app.services.workflow import pending_count
            ctx["nav"] = nav_for(current_user, request.endpoint)
            ctx["unread_notifications"] = unread_count(current_user)
            ctx["pending_approvals"] = pending_count(current_user)
        return ctx


def _register_handlers(app):
    from app.services.errors import DomainError

    @app.before_request
    def make_session_permanent():
        from flask import session
        session.permanent = True  # PERMANENT_SESSION_LIFETIME = 30-minute idle timeout

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.errorhandler(DomainError)
    def domain_error(exc):
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("dashboards.home"))

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/error.html", code=403, title=_("Access denied"),
                               message=_("You don't have permission to view this page.")), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/error.html", code=404, title=_("Page not found"),
                               message=_("We couldn't find that page.")), 404

    @app.errorhandler(413)
    def too_large(_e):
        flash(_("That upload is too large. Files must be 10 MB or smaller."), "error")
        return redirect(request.referrer or url_for("careers.index"))

    @app.errorhandler(429)
    def rate_limited(_e):
        flash(_("Too many attempts. Please wait a minute and try again."), "error")
        return redirect(url_for("auth.login"))


def _register_file_access():
    from app.models import Requisition
    from app.services import files, requisitions

    def requisition_rule(user, entity_id):
        req = db.session.get(Requisition, entity_id)
        return req is not None and requisitions.can_view(user, req)

    def candidate_rule(user, _entity_id):
        return user.is_hr

    files.register_access("requisition", requisition_rule)
    files.register_access("candidate", candidate_rule)
