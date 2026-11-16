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
    from app.adverts.routes import bp as adverts_bp
    from app.approvals.routes import bp as approvals_bp
    from app.auth.routes import bp as auth_bp
    from app.budget.routes import bp as budget_bp
    from app.dashboards.routes import bp as dashboards_bp
    from app.onboarding.routes import bp as onboarding_bp
    from app.portal.routes import bp as portal_bp
    from app.positions.routes import bp as positions_bp
    from app.recruitment.careers import bp as careers_bp
    from app.recruitment.routes import bp as recruitment_bp
    from app.requisitions.routes import bp as requisitions_bp
    from app.travel.routes import bp as travel_bp

    for bp in (careers_bp, auth_bp, dashboards_bp, portal_bp, requisitions_bp, positions_bp, approvals_bp, budget_bp,
               adverts_bp, recruitment_bp, onboarding_bp, travel_bp, admin_bp):
        app.register_blueprint(bp)


def _register_template_helpers(app):
    from app import filters
    from app.models.recruitment import APPLICATION_STATUSES, JOB_TYPES
    from app.nav import nav_for
    from app.services import ats
    from app.services.dates import today
    from app.services.places import SA_PLACES

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
            "sa_places": SA_PLACES,
        }
        if current_user.is_authenticated:
            from app.auth.portals import PORTAL_LABELS, current_portal
            from app.services.notifications import unread_count
            from app.services.workflow import pending_count
            ctx["nav"] = nav_for(current_user, request.endpoint)
            ctx["portal"], ctx["portal_labels"] = current_portal(), PORTAL_LABELS
            ctx["unread_notifications"] = unread_count(current_user)
            from app.models.user import THEMES
            ctx["ui_theme"] = current_user.theme if current_user.theme in THEMES else "light"
            ctx["THEMES"] = THEMES
            from app.services import starter_pack
            # Workflow steps plus new starter packs to approve (16 Nov 2026), so My Approvals shows everything waiting.
            ctx["pending_approvals"] = pending_count(current_user) + len(starter_pack.to_review(current_user))
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

    @app.route("/favicon.ico")
    def favicon():
        """Browsers ask for /favicon.ico directly (e.g. for a CV or PDF opened in a tab)."""
        return app.send_static_file("favicon.ico")

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
    from app.models.user import IT
    from app.services import files, requisitions

    def requisition_rule(user, entity_id):
        req = db.session.get(Requisition, entity_id)
        return req is not None and requisitions.can_view(user, req)

    def candidate_rule(user, _entity_id):
        return user.can_recruit

    def asset_rule(user, _entity_id):
        return user.has_role(IT)

    files.register_access("requisition", requisition_rule)
    files.register_access("candidate", candidate_rule)
    files.register_access("candidate_document", candidate_rule)       # documents attached when applying
    files.register_access("asset_allocation", asset_rule)

    def onboarding_rule(user, _entity_id):           # offer letters (8 Nov 2026)
        from app.services.onboarding import VIEW_ROLES
        return user.has_role(*VIEW_ROLES)

    def case_rule(user, case_id):                     # signed contracts and the candidate's documents (10 Nov 2026)
        from app.models import OnboardingCase
        from app.services import onboarding
        case = db.session.get(OnboardingCase, case_id or 0)
        return case is not None and onboarding.can_view_case(user, case)

    files.register_access("offer_letter", onboarding_rule)
    files.register_access("employment_contract", case_rule)
    files.register_access("onboarding_document", case_rule)

    def check_rule(user, check_id):                   # background check reports (16 Nov 2026)
        from app.models import BackgroundCheck
        from app.services import screening
        check = db.session.get(BackgroundCheck, check_id or 0)
        return check is not None and screening.can_view(user, check.screening.application)

    files.register_access("background_check", check_rule)

    def consent_rule(user, screening_id):             # the signed MIE form and POPIA consent (16 Nov 2026)
        from app.models import BackgroundScreening
        from app.services import screening
        record = db.session.get(BackgroundScreening, screening_id or 0)
        return record is not None and screening.can_view(user, record.application)

    def pack_rule(user, pack_id):                     # the new starter pack's uploads (16 Nov 2026)
        from app.models import NewStarterPack
        from app.services import onboarding
        pack = db.session.get(NewStarterPack, pack_id or 0)
        return pack is not None and onboarding.can_view_case(user, pack.case)

    def blank_form_rule(user, _entity_id):            # HR Admin's replacement blank forms
        from app.models.user import HRBP
        from app.services.onboarding import VIEW_ROLES
        return user.has_role(*VIEW_ROLES, HRBP)

    files.register_access("screening_consent", consent_rule)
    files.register_access("starter_pack", pack_rule)
    files.register_access("candidate_form", blank_form_rule)

    def signature_rule(user, _entity_id):            # the signature on letters: HR Admin only
        from app.models.user import HR_ADMIN
        return user.has_role(HR_ADMIN)

    files.register_access("document_signature", signature_rule)

    def travel_rule(user, tr_id):                     # travel request PDFs and i-Travel's invoices (14 Nov 2026)
        from app.models import TravelRequest
        from app.services import travel
        tr = db.session.get(TravelRequest, tr_id or 0)
        return tr is not None and travel.can_view(user, tr)

    files.register_access("travel_form", travel_rule)
    files.register_access("travel_invoice", travel_rule)
