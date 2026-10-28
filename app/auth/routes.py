"""Sign-in, sign-out and account settings.

Sign-in will move to Microsoft SSO (Entra ID), which also provides MFA. Until then,
test users sign in with their username or email address and a password."""
from flask import (Blueprint, current_app, flash, redirect, render_template, request, session, url_for)
from flask_babel import gettext as _
from flask_login import current_user, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length

from app.auth.decorators import roles_required
from app.extensions import db, limiter
from app.models import User
from app.services import audit
from app.services.dates import now

bp = Blueprint("auth", __name__)


class LoginForm(FlaskForm):
    login = StringField(_("Username or email"), validators=[DataRequired()])
    password = PasswordField(_("Password"), validators=[DataRequired()])


class PasswordForm(FlaskForm):
    current = PasswordField(_("Current password"), validators=[DataRequired()])
    new = PasswordField(_("New password"), validators=[DataRequired(), Length(min=10, message=_(
        "Use at least 10 characters."))])
    confirm = PasswordField(_("Confirm new password"), validators=[EqualTo("new", message=_("Passwords don't match."))])


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


def find_user(login):
    """The account for a username or an email address (both case-insensitive).
    An email shared by more than one account matches none of them."""
    login = (login or "").strip().lower()
    if not login:
        return None
    user = User.query.filter(db.func.lower(User.username) == login).first()
    if user is None and "@" in login:
        matches = User.query.filter(db.func.lower(User.email) == login).limit(2).all()
        user = matches[0] if len(matches) == 1 else None
    return user


def _register_failure(user, login):
    audit.record("login.failed", "user", getattr(user, "id", None), user=user, detail=f"login={login[:60]}")
    db.session.commit()


# Each audience has a simple landing page that leads to its own sign-in page. Users sign in
# on their own page (User.landing); the work-account button will go to Microsoft SSO later.
LANDINGS = {
    "staff": (_("Staff self-service"), _("Sign your performance agreement, complete appraisals and update "
                                         "your qualifications.")),
    "manager": (_("Manager self-service"), _("Start and track HR processes for your team.")),
    "admin": (_("HR admin portal"), _("For authorised HR, Finance and system administrators only.")),
}


@bp.route("/login", defaults={"audience": "admin"})
@bp.route("/login/<any(staff, manager, admin):audience>")
def login(audience):
    if current_user.is_authenticated:
        return redirect(url_for("dashboards.home"))
    title, lead = LANDINGS[audience]
    return render_template("auth/landing.html", audience=audience, title=title, lead=lead,
                           next_url=_safe_next(request.args.get("next")))


@bp.route("/login/sign-in", defaults={"audience": "admin"}, methods=["GET", "POST"])
@bp.route("/login/<any(staff, manager, admin):audience>/sign-in", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"], methods=["POST"])
def login_form(audience):
    if current_user.is_authenticated:
        return redirect(url_for("dashboards.home"))
    next_url = _safe_next(request.args.get("next"))
    form = LoginForm()
    if form.validate_on_submit():
        entered = form.login.data.strip()
        user = find_user(entered)
        if user is None or not user.active or not user.check_password(form.password.data):
            _register_failure(user, entered)
            flash(_("Incorrect username, email or password."), "error")
        elif user.landing != audience:
            audit.record("login.wrong_page", "user", user.id, user=user, detail=f"page={audience}")
            db.session.commit()
            flash(_("Please sign in on %(page)s.", page=LANDINGS[user.landing][0]), "info")
            return redirect(url_for("auth.login_form", audience=user.landing, next=next_url))
        else:
            session.clear()
            login_user(user)
            user.last_login_at = now()
            audit.record("login.success", "user", user.id, user=user)
            db.session.commit()
            return redirect(next_url or url_for("dashboards.home"))
    return render_template("auth/login.html", audience=audience, title=LANDINGS[audience][0], form=form,
                           next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    audience = "admin"
    if current_user.is_authenticated:
        audience = current_user.landing
        audit.record("logout", "user", current_user.id)
        db.session.commit()
    logout_user()
    session.clear()
    flash(_("You have signed out."), "success")
    return redirect(url_for("auth.login", audience=audience))


@bp.route("/account", methods=["GET", "POST"])
@roles_required()
def account():
    form = PasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current.data):
            flash(_("Your current password is incorrect."), "error")
        else:
            current_user.set_password(form.new.data)
            audit.record("password.changed", "user", current_user.id)
            db.session.commit()
            flash(_("Password changed."), "success")
            return redirect(url_for("auth.account"))
    return render_template("auth/account.html", form=form)


@bp.route("/admin/login")
def legacy_login():
    return redirect(url_for("auth.login"))
