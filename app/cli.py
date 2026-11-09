"""Flask CLI commands. Scheduled jobs (`flask run-sla-checks`) can be run by
Windows Task Scheduler or cron."""
import getpass
import json
import os
import sqlite3
import sys
from datetime import date, datetime

import click

from app.extensions import db


def register_cli(app):
    @app.cli.command("run-sla-checks")
    def run_sla_checks():
        """Send approval reminders and escalate steps past their SLA."""
        from app.services.workflow import run_sla_checks as run
        result = run()
        db.session.commit()
        click.echo(f"Reminders sent: {result['reminded']}. Escalations: {result['escalated']}.")

    @app.cli.command("close-expired-adverts")
    def close_expired_adverts():
        """Close adverts past their closing date and tell the recruiter (run daily)."""
        from app.services import adverts
        closed = adverts.close_expired()
        db.session.commit()
        click.echo(f"Adverts closed: {closed}.")

    @app.cli.command("remind-jd-reviews")
    def remind_jd_reviews():
        """Remind HR about job descriptions due for their annual review (run daily)."""
        from app.services import adverts
        due = adverts.remind_jd_reviews()
        db.session.commit()
        click.echo(f"Job descriptions due for review: {due}.")

    @app.cli.command("send-test-email")
    @click.option("--to", "to", required=True, help="Who gets the test email")
    def send_test_email(to):
        """Send a test email with the configured mail settings (MAIL_PROVIDER, SMTP_*, EMAIL_COPY_TO)."""
        from app.integrations import IntegrationError, get_adapter
        from app.services.dates import format_datetime, now
        cfg = app.config
        cfg["EMAIL_ASYNC"] = False                             # wait for the server, to report the result
        copies = cfg.get("EMAIL_COPY_TO") or "nobody"
        body = (f"This is a test email from the {cfg.get('SMTP_FROM_NAME') or 'ICE People Administration System'}.\n\n"
                f"Sent: {format_datetime(now())}\nMail provider: {cfg['MAIL_PROVIDER']}\n"
                f"Server: {cfg['SMTP_HOST']}:{cfg['SMTP_PORT']}\nFrom: {cfg['SMTP_FROM'] or '-'}\n"
                f"Copy of every email to: {copies}\n\nIf you can read this, email is working.")
        from app.services.emails import designed
        subject = "ICE People: test email"
        try:
            get_adapter("email").send_email(to, subject, body, html=designed("test", subject, body, "/dashboard"))
        except IntegrationError as exc:
            db.session.commit()                                # keep the integration log of the failure
            sys.exit(f"The test email failed: {exc}")
        db.session.commit()
        if cfg["MAIL_PROVIDER"] != "smtp":
            click.echo("MAIL_PROVIDER isn't smtp, so the email was only printed above (mock).")
        else:
            others = [c.strip() for c in (cfg.get("EMAIL_COPY_TO") or "").split(",")
                      if c.strip() and c.strip().lower() != to.lower()]
            click.echo(f"Test email sent to {to}" + (f", copy to {', '.join(others)}." if others else "."))

    @app.cli.command("send-email-samples")
    @click.option("--to", "to", required=True, help="Who gets the samples")
    @click.option("--key", "keys", multiple=True, help="Only these template keys (default: every template)")
    def send_email_samples(to, keys):
        """Email one designed sample of every notification template, filled in with example values, for review."""
        from app.integrations import IntegrationError, get_adapter
        from app.models import NotificationTemplate
        from app.services import emails
        from app.services.notifications import ensure_templates
        app.config["EMAIL_ASYNC"] = False                      # wait for the server, to report each result
        ensure_templates()
        q = NotificationTemplate.query.order_by(NotificationTemplate.name)
        templates = [t for t in q if not keys or t.key in keys]
        sent = 0
        for tpl in templates:
            subject, body, link, context = emails.sample(tpl.key, tpl.subject, tpl.body)
            subject = f"[Sample] {subject}"
            try:
                get_adapter("email").send_email(to, subject, body,
                                                html=emails.designed(tpl.key, subject, body, link, context))
                sent += 1
            except IntegrationError as exc:
                click.echo(f"{tpl.key}: failed ({exc})")
        db.session.commit()
        click.echo(f"Sent {sent} of {len(templates)} samples to {to}.")

    @app.cli.command("expire-offers")
    def expire_offers():
        """Daily: offers the candidate didn't answer by their expiry date lapse (HR Admin is told)."""
        from app.services import onboarding
        count = onboarding.expire_all()
        db.session.commit()
        click.echo(f"{count} offer(s) expired.")

    @app.cli.command("set-password")
    @click.argument("username")
    def set_password(username):
        """Set a user's password."""
        from app.models import User
        from app.services import audit
        user = User.query.filter_by(username=username).first()
        if user is None:
            sys.exit(f"No user called {username}.")
        password = getpass.getpass("New password: ")
        if len(password) < 10:
            sys.exit("Password must be at least 10 characters.")
        user.set_password(password)
        audit.record("password.reset", "user", user.id, detail="flask set-password")
        db.session.commit()
        click.echo(f"Password set for {username}.")

    @app.cli.command("reprocess-cvs")
    def reprocess_cvs():
        """Re-extract text from every stored CV and re-score every application."""
        from app.models import Candidate, Job
        from app.services import ats, careers, files
        missing = ats.missing_packages()
        if missing:
            sys.exit("Missing CV libraries: " + ", ".join(missing) + ". Run: pip install -r requirements.txt")
        fixed = 0
        for c in Candidate.query.filter(Candidate.cv_file_id.isnot(None)).all():
            text = ats.extract_text(c.cv_file.original_name, files.read(c.cv_file))
            if text != (c.cv_text or ""):
                c.cv_text, fixed = text, fixed + 1
        jobs = Job.query.all()
        for job in jobs:
            careers.rescore_job(job)
        db.session.commit()
        click.echo(f"Updated text for {fixed} CV(s) and re-scored applications for {len(jobs)} job(s).")

    @app.cli.command("import-legacy")
    @click.option("--path", default=None, help="Path to the old portal.db (default: LEGACY_DB / ./portal.db)")
    def import_legacy(path):
        """Copy jobs, candidates (with CVs), applications and admin logins from the original portal."""
        click.echo(import_legacy_db(path or app.config["LEGACY_DB"]))


def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _d(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def import_legacy_db(path):
    """Idempotent: rows already imported (same id / username) are skipped."""
    from app.models import Application, Candidate, Job, Role, User
    from app.models.user import HR_ADMIN, RECRUITER
    from app.services import audit, files
    from app.services.dates import now

    if not os.path.exists(path):
        return f"No legacy database at {path}."
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    cols = {t: {r[1] for r in src.execute(f"PRAGMA table_info({t})")} for t in ("jobs", "candidates")}
    counts = {"jobs": 0, "candidates": 0, "applications": 0, "users": 0}

    for r in src.execute("SELECT * FROM jobs"):
        if db.session.get(Job, r["id"]):
            continue
        db.session.add(Job(id=r["id"], title=r["title"], department=r["department"], location=r["location"],
                           job_type=r["job_type"], description=r["description"],
                           required_skills=r["required_skills"], preferred_skills=r["preferred_skills"],
                           min_experience=r["min_experience"] or 0, min_education=r["min_education"] or 0,
                           closing_date=_d(r["closing_date"]), status=r["status"] or "Open",
                           is_demo=bool(r["is_demo"]) if "is_demo" in cols["jobs"] else False,
                           created_at=_dt(r["created_at"]) or now()))
        counts["jobs"] += 1
    db.session.flush()

    for r in src.execute("SELECT * FROM candidates"):
        if db.session.get(Candidate, r["id"]):
            continue
        stored = files.store_bytes(r["cv_data"] or b"", r["cv_filename"] or "cv.pdf", "candidate", r["id"],
                                   check=False)
        db.session.add(Candidate(
            id=r["id"], full_name=r["full_name"], email=r["email"], phone=r["phone"], location=r["location"],
            current_title=r["current_title"], years_experience=r["years_experience"],
            education_level=r["education_level"] or 0, skills=r["skills"], cv_file_id=stored.id,
            cv_text=r["cv_text"], consent=bool(r["consent"]), consent_at=_dt(r["created_at"]),
            is_demo=bool(r["is_demo"]) if "is_demo" in cols["candidates"] else False,
            created_at=_dt(r["created_at"]) or now(), updated_at=_dt(r["updated_at"]) or now()))
        counts["candidates"] += 1
    db.session.flush()

    for r in src.execute("SELECT * FROM applications"):
        if db.session.get(Application, r["id"]) or Application.query.filter_by(reference=r["reference"]).first():
            continue
        try:
            breakdown = json.loads(r["breakdown"] or "{}")
        except ValueError:
            breakdown = {}
        db.session.add(Application(
            id=r["id"], reference=r["reference"], candidate_id=r["candidate_id"], job_id=r["job_id"],
            cover_note=r["cover_note"], score=r["score"] or 0, breakdown=breakdown, status=r["status"] or "New",
            notes=r["notes"], source=r["source"] or "Applied",
            created_at=_dt(r["created_at"]) or now(), updated_at=_dt(r["updated_at"]) or now()))
        counts["applications"] += 1

    roles = Role.query.filter(Role.name.in_([HR_ADMIN, RECRUITER])).all()
    for r in src.execute("SELECT * FROM admins"):
        if User.query.filter_by(username=r["username"]).first():
            continue
        # The werkzeug hash is kept and upgraded to argon2 at first sign-in.
        db.session.add(User(username=r["username"], full_name=r["username"].title(),
                            password_hash=r["password_hash"], roles=list(roles)))
        counts["users"] += 1
    src.close()
    audit.record("legacy.import", "system", None, after=counts)
    db.session.commit()
    return (f"Imported {counts['jobs']} job(s), {counts['candidates']} candidate(s) with CVs, "
            f"{counts['applications']} application(s) and {counts['users']} login(s) from {path}.")
