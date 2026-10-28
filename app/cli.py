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
