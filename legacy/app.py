import csv
import io
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, date
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import ats

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PORTAL_DB", os.path.join(BASE_DIR, "portal.db"))
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}
STATUSES = ["New", "Screening", "Shortlisted", "Interview", "Offer", "Hired", "Rejected"]
JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Learnership"]


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE_DIR, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # 5 MB CV limit
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    TEMPLATES_AUTO_RELOAD=True,  # pick up template edits without a restart
)


# ----------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY,
    title            TEXT NOT NULL,
    department       TEXT,
    location         TEXT,
    job_type         TEXT,
    description      TEXT NOT NULL,
    required_skills  TEXT,
    preferred_skills TEXT,
    min_experience   INTEGER DEFAULT 0,
    min_education    INTEGER DEFAULT 0,
    closing_date     TEXT,
    status           TEXT NOT NULL DEFAULT 'Open',
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id               INTEGER PRIMARY KEY,
    full_name        TEXT NOT NULL,
    email            TEXT UNIQUE NOT NULL,
    phone            TEXT,
    location         TEXT,
    current_title    TEXT,
    years_experience INTEGER,
    education_level  INTEGER DEFAULT 0,
    skills           TEXT,
    cv_filename      TEXT NOT NULL,
    cv_mimetype      TEXT NOT NULL,
    cv_data          BLOB NOT NULL,
    cv_text          TEXT,
    consent          INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id           INTEGER PRIMARY KEY,
    reference    TEXT UNIQUE NOT NULL,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id       INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    cover_note   TEXT,
    score        REAL DEFAULT 0,
    breakdown    TEXT,
    status       TEXT NOT NULL DEFAULT 'New',
    notes        TEXT,
    source       TEXT NOT NULL DEFAULT 'Applied',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (candidate_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_app_job ON applications(job_id, score);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    # Migration: flag rows created by seed_dummy.py so they can be removed cleanly.
    for table in ("jobs", "candidates"):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        if "is_demo" not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
    if not db.execute("SELECT 1 FROM admins").fetchone():
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            raise SystemExit("[setup] Set ADMIN_PASSWORD to create the first admin account.")
        db.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                   (username, generate_password_hash(password)))
    db.commit()
    db.close()


def now():
    return datetime.now().isoformat(timespec="seconds")


def new_reference():
    return "ICE-" + secrets.token_hex(4).upper()


# ----------------------------------------------------------------- security

@app.before_request
def csrf_protect():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not secrets.compare_digest(token, session["csrf"]):
            abort(400, "Your session expired. Please go back, refresh and try again.")


@app.context_processor
def inject_globals():
    return {
        "csrf_token": session.get("csrf", ""),
        "education_levels": ats.EDUCATION_LEVELS,
        "education_labels": ats.EDUCATION_LABELS,
        "statuses": STATUSES,
        "job_types": JOB_TYPES,
        "current_year": date.today().year,
        "is_admin": "admin_id" in session,
        "now_label": date.today().strftime("%d %B %Y"),
        "asset": asset_url,
        "icon": app.jinja_env.get_template("_icons.html").module.icon,
    }


def asset_url(filename):
    """Static URL stamped with the file's modified time, so browsers never use a stale copy."""
    try:
        version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
    except OSError:
        version = 0
    return url_for("static", filename=filename, v=version)


@app.template_filter("initials")
def initials(name):
    parts = (name or "?").split()
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.template_filter("score_class")
def score_class(score):
    score = score or 0
    if score >= 75:
        return "high"
    if score >= 50:
        return "mid"
    return "low"


@app.template_filter("dt")
def format_dt(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y")
    except ValueError:
        return value


@app.template_filter("longdate")
def format_longdate(value):
    """'2026-10-27' -> 'Tuesday, 27 October 2026' (as on the hiring posters)."""
    try:
        d = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value or ""
    return f"{d:%A}, {d.day} {d:%B %Y}"


@app.template_filter("jobdesc")
def format_job_description(text):
    """Render a plain-text job ad as HTML: ALL-CAPS lines become headings,
    '•' / '-' lines become bullet lists, and a short line directly before a
    list becomes a sub-heading. Every line is escaped."""
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


@app.template_filter("ago")
def posted_ago(value):
    try:
        days = (date.today() - datetime.fromisoformat(value).date()).days
    except (TypeError, ValueError):
        return ""
    if days <= 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    if days < 30:
        return f"Posted {days} days ago"
    return "Posted " + format_dt(value)


@app.errorhandler(413)
def too_large(_e):
    flash("That file is too large. CVs must be 5 MB or smaller.", "error")
    return redirect(request.referrer or url_for("index"))


# --------------------------------------------------------- candidate saving

def save_candidate_from_form(db):
    """Validate the application form, create/update the candidate (CV stored
    in the database) and return their row, or None after flashing errors."""
    form = request.form
    errors = []
    full_name = form.get("full_name", "").strip()
    email = form.get("email", "").strip().lower()
    if not full_name:
        errors.append("Please enter your full name.")
    if "@" not in email or "." not in email.split("@")[-1]:
        errors.append("Please enter a valid email address.")
    if not form.get("consent"):
        errors.append("Please consent to us storing your information (POPIA).")

    upload = request.files.get("cv")
    ext = os.path.splitext(upload.filename)[1].lower() if upload and upload.filename else ""
    if not upload or not upload.filename:
        errors.append("Please upload your CV.")
    elif ext not in ALLOWED_EXTENSIONS:
        errors.append("CV must be a PDF, Word (.docx) or .txt file.")

    years = form.get("years_experience", "").strip()
    try:
        years = max(0, min(50, int(years))) if years else None
    except ValueError:
        errors.append("Years of experience must be a number.")
        years = None

    if errors:
        for e in errors:
            flash(e, "error")
        return None

    data = upload.read()
    filename = secure_filename(upload.filename) or f"cv{ext}"
    cv_text = ats.extract_text(filename, data)
    try:
        edu = int(form.get("education_level") or 0)
    except ValueError:
        edu = 0
    fields = {
        "full_name": full_name,
        "email": email,
        "phone": form.get("phone", "").strip(),
        "location": form.get("location", "").strip(),
        "current_title": form.get("current_title", "").strip(),
        "years_experience": years,
        "education_level": edu,
        "skills": form.get("skills", "").strip(),
        "cv_filename": filename,
        "cv_mimetype": MIME_TYPES[ext],
        "cv_data": data,
        "cv_text": cv_text,
        "consent": 1,
        "updated_at": now(),
    }
    existing = db.execute("SELECT id FROM candidates WHERE email = ?", (email,)).fetchone()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE candidates SET {sets} WHERE id = ?", (*fields.values(), existing["id"]))
        cand_id = existing["id"]
    else:
        fields["created_at"] = fields["updated_at"]
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cand_id = db.execute(f"INSERT INTO candidates ({cols}) VALUES ({marks})",
                             tuple(fields.values())).lastrowid
    return db.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone()


def upsert_application(db, candidate, job, cover_note="", source="Applied", status=None):
    """Create (or refresh) the candidate's application for a job / talent pool."""
    if job is not None:
        score, breakdown = ats.score_candidate(job, candidate)
        existing = db.execute("SELECT * FROM applications WHERE candidate_id = ? AND job_id = ?",
                              (candidate["id"], job["id"])).fetchone()
    else:
        score, breakdown = 0, {}
        existing = db.execute(
            "SELECT * FROM applications WHERE candidate_id = ? AND job_id IS NULL",
            (candidate["id"],)).fetchone()
    if existing:
        db.execute("""UPDATE applications SET score = ?, breakdown = ?, cover_note = COALESCE(NULLIF(?, ''), cover_note),
                      updated_at = ? WHERE id = ?""",
                   (score, json.dumps(breakdown), cover_note, now(), existing["id"]))
        return existing["reference"]
    ref = new_reference()
    db.execute("""INSERT INTO applications (reference, candidate_id, job_id, cover_note, score, breakdown,
                  status, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
               (ref, candidate["id"], job["id"] if job else None, cover_note, score,
                json.dumps(breakdown), status or "New", source, now(), now()))
    return ref


def rescore_job(db, job):
    rows = db.execute("""SELECT a.id, c.* FROM applications a JOIN candidates c ON c.id = a.candidate_id
                         WHERE a.job_id = ?""", (job["id"],)).fetchall()
    for row in rows:
        score, breakdown = ats.score_candidate(job, row)
        db.execute("UPDATE applications SET score = ?, breakdown = ? WHERE id = ?",
                   (score, json.dumps(breakdown), row[0]))


def paginate(items, per_page):
    """Slice a list for the current ?page= and return (page_items, pager)."""
    total = len(items)
    pages = max(1, -(-total // per_page))
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    start = (page - 1) * per_page
    args = {k: v for k, v in request.args.items() if k != "page"}
    return items[start:start + per_page], {
        "page": page, "pages": pages, "total": total, "start": start,
        "first": start + 1 if total else 0, "last": min(start + per_page, total),
        "url": lambda n: url_for(request.endpoint, **request.view_args, **args, page=n),
    }


# ------------------------------------------------------------ public pages

def open_jobs_query():
    return """SELECT * FROM jobs WHERE status = 'Open'
              AND (closing_date IS NULL OR closing_date = '' OR closing_date >= date('now'))"""


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    dept = request.args.get("department", "").strip()
    job_type = request.args.get("job_type", "").strip()
    sql, params = open_jobs_query(), []
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR required_skills LIKE ?)"
        params += [f"%{q}%"] * 3
    if location:
        sql += " AND location LIKE ?"
        params.append(f"%{location}%")
    if dept:
        sql += " AND department = ?"
        params.append(dept)
    if job_type:
        sql += " AND job_type = ?"
        params.append(job_type)
    db = get_db()
    jobs, pager = paginate(db.execute(sql + " ORDER BY created_at DESC", params).fetchall(), 12)

    # Filter sidebar counts are taken over all open jobs.
    def counts(column):
        return db.execute(f"""SELECT {column}, COUNT(*) FROM ({open_jobs_query()})
                              WHERE {column} IS NOT NULL AND {column} != ''
                              GROUP BY {column} ORDER BY {column}""").fetchall()
    total_open = db.execute(f"SELECT COUNT(*) FROM ({open_jobs_query()})").fetchone()[0]
    return render_template("public/index.html", jobs=jobs, q=q, location=location, dept=dept,
                           job_type=job_type, total_open=total_open,
                           departments=counts("department"), types=counts("job_type"),
                           locations=counts("location"),
                           filtered=any([q, location, dept, job_type]), pager=pager)


@app.route("/jobs/<int:job_id>", methods=["GET", "POST"])
def job_detail(job_id):
    db = get_db()
    job = db.execute(open_jobs_query() + " AND id = ?", (job_id,)).fetchone()
    if not job:
        flash("That position is no longer open. You can still submit your CV to our talent pool.", "info")
        return redirect(url_for("index"))
    if request.method == "POST":
        candidate = save_candidate_from_form(db)
        if candidate:
            ref = upsert_application(db, candidate, job, request.form.get("cover_note", "").strip())
            # Every CV also lives in the talent pool for future openings.
            upsert_application(db, candidate, None, source="Talent pool")
            db.commit()
            return redirect(url_for("application_done", ref=ref))
    return render_template("public/job.html", job=job, form=request.form)


@app.route("/talent-pool", methods=["GET", "POST"])
def talent_pool():
    db = get_db()
    if request.method == "POST":
        candidate = save_candidate_from_form(db)
        if candidate:
            ref = upsert_application(db, candidate, None, request.form.get("cover_note", "").strip(),
                                     source="Talent pool")
            db.commit()
            return redirect(url_for("application_done", ref=ref))
    return render_template("public/talent_pool.html", form=request.form)


@app.route("/thank-you/<ref>")
def application_done(ref):
    app_row = get_db().execute("""SELECT a.reference, j.title FROM applications a
                                  LEFT JOIN jobs j ON j.id = a.job_id WHERE a.reference = ?""",
                               (ref,)).fetchone()
    if not app_row:
        abort(404)
    return render_template("public/thanks.html", app_row=app_row)


@app.route("/status", methods=["GET", "POST"])
def check_status():
    result = None
    if request.method == "POST":
        ref = request.form.get("reference", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        result = get_db().execute(
            """SELECT a.reference, a.status, a.created_at, a.updated_at, j.title
               FROM applications a JOIN candidates c ON c.id = a.candidate_id
               LEFT JOIN jobs j ON j.id = a.job_id
               WHERE a.reference = ? AND c.email = ?""", (ref, email)).fetchone()
        if not result:
            flash("We couldn't find an application with that reference and email.", "error")
    return render_template("public/status.html", result=result)


# ------------------------------------------------------------- admin: auth

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM admins WHERE username = ?",
                                (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            csrf = session.get("csrf")
            session.clear()
            session["admin_id"] = user["id"]
            session["admin_name"] = user["username"]
            session["csrf"] = csrf or secrets.token_urlsafe(32)
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin_dashboard"))
        flash("Incorrect username or password.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# -------------------------------------------------------- admin: dashboard

@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "open_jobs": db.execute(open_jobs_query().replace("SELECT *", "SELECT COUNT(*)")).fetchone()[0],
        "candidates": db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
        "applications": db.execute("SELECT COUNT(*) FROM applications WHERE job_id IS NOT NULL").fetchone()[0],
        "new_this_week": db.execute(
            "SELECT COUNT(*) FROM candidates WHERE created_at >= datetime('now', '-7 days')").fetchone()[0],
    }
    jobs = db.execute("""SELECT j.*, COUNT(a.id) AS applicants, ROUND(AVG(a.score), 1) AS avg_score,
                                SUM(CASE WHEN a.score >= 75 THEN 1 ELSE 0 END) AS strong
                         FROM jobs j LEFT JOIN applications a ON a.job_id = j.id
                         WHERE j.status = 'Open' GROUP BY j.id ORDER BY j.created_at DESC""").fetchall()
    jobs, pager = paginate(jobs, 10)
    recent = db.execute("""SELECT a.*, c.full_name, j.title FROM applications a
                           JOIN candidates c ON c.id = a.candidate_id JOIN jobs j ON j.id = a.job_id
                           ORDER BY a.created_at DESC LIMIT 8""").fetchall()
    pipeline = dict(db.execute("""SELECT status, COUNT(*) FROM applications WHERE job_id IS NOT NULL
                                  GROUP BY status""").fetchall())
    return render_template("admin/dashboard.html", stats=stats, jobs=jobs, recent=recent, pipeline=pipeline,
                           pager=pager)


# ------------------------------------------------------------- admin: jobs

def job_form_values():
    f = request.form
    def to_int(v):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0
    return {
        "title": f.get("title", "").strip(),
        "department": f.get("department", "").strip(),
        "location": f.get("location", "").strip(),
        "job_type": f.get("job_type", "").strip(),
        "description": f.get("description", "").strip(),
        "required_skills": ", ".join(ats.split_skills(f.get("required_skills"))),
        "preferred_skills": ", ".join(ats.split_skills(f.get("preferred_skills"))),
        "min_experience": to_int(f.get("min_experience")),
        "min_education": to_int(f.get("min_education")),
        "closing_date": f.get("closing_date", "").strip() or None,
        "status": "Closed" if f.get("status") == "Closed" else "Open",
    }


@app.route("/admin/jobs")
@admin_required
def admin_jobs():
    jobs = get_db().execute("""SELECT j.*, COUNT(a.id) AS applicants FROM jobs j
                               LEFT JOIN applications a ON a.job_id = j.id
                               GROUP BY j.id ORDER BY j.status DESC, j.created_at DESC""").fetchall()
    jobs, pager = paginate(jobs, 20)
    return render_template("admin/jobs.html", jobs=jobs, pager=pager)


@app.route("/admin/jobs/new", methods=["GET", "POST"])
@app.route("/admin/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_job_form(job_id=None):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone() if job_id else None
    if job_id and not job:
        abort(404)
    if request.method == "POST":
        values = job_form_values()
        if not values["title"] or not values["description"]:
            flash("Title and description are required.", "error")
            return render_template("admin/job_form.html", job=values, job_id=job_id)
        if job:
            sets = ", ".join(f"{k} = ?" for k in values)
            db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*values.values(), job_id))
            rescore_job(db, db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
            flash("Job updated and applicants re-scored.", "success")
        else:
            values["created_at"] = now()
            cols, marks = ", ".join(values), ", ".join("?" for _ in values)
            job_id = db.execute(f"INSERT INTO jobs ({cols}) VALUES ({marks})", tuple(values.values())).lastrowid
            flash("Job published. Check the Talent Pool tab for existing CVs that match.", "success")
        db.commit()
        return redirect(url_for("admin_job_detail", job_id=job_id))
    return render_template("admin/job_form.html", job=job or {}, job_id=job_id)


@app.route("/admin/jobs/<int:job_id>/delete", methods=["POST"])
@admin_required
def admin_job_delete(job_id):
    db = get_db()
    db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    db.commit()
    flash("Job deleted. Candidate CVs remain in the talent pool.", "success")
    return redirect(url_for("admin_jobs"))


def ranked_applicants(db, job_id, args):
    sql = """SELECT a.*, c.full_name, c.email, c.phone, c.location, c.current_title,
                    c.years_experience, c.education_level
             FROM applications a JOIN candidates c ON c.id = a.candidate_id WHERE a.job_id = ?"""
    params = [job_id]
    min_score = args.get("min_score", type=float, default=0)
    if min_score:
        sql += " AND a.score >= ?"
        params.append(min_score)
    if args.get("status"):
        sql += " AND a.status = ?"
        params.append(args["status"])
    if args.get("q"):
        sql += " AND (c.full_name LIKE ? OR c.email LIKE ? OR c.cv_text LIKE ? OR c.skills LIKE ?)"
        params += [f"%{args['q']}%"] * 4
    order = {"score": "a.score DESC", "date": "a.created_at DESC", "name": "c.full_name"}
    sql += " ORDER BY " + order.get(args.get("sort"), "a.score DESC")
    rows = db.execute(sql, params).fetchall()
    return [dict(r, breakdown=json.loads(r["breakdown"] or "{}")) for r in rows]


@app.route("/admin/jobs/<int:job_id>")
@admin_required
def admin_job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        abort(404)
    tab = request.args.get("tab", "applicants")
    applicants = ranked_applicants(db, job_id, request.args) if tab == "applicants" else []
    matches = []
    if tab == "pool":
        # Score every CV in the database that hasn't applied for this job.
        min_score = request.args.get("min_score", type=float, default=50)
        rows = db.execute("""SELECT * FROM candidates WHERE id NOT IN
                             (SELECT candidate_id FROM applications WHERE job_id = ?)""", (job_id,)).fetchall()
        for c in rows:
            score, breakdown = ats.score_candidate(job, c)
            if score >= min_score:
                matches.append({"c": c, "score": score, "breakdown": breakdown})
        matches.sort(key=lambda m: -m["score"])
    applicants, pager = paginate(applicants if tab == "applicants" else matches, 25)
    if tab == "pool":
        matches, applicants = applicants, []
    total = db.execute("SELECT COUNT(*) FROM applications WHERE job_id = ?", (job_id,)).fetchone()[0]
    return render_template("admin/job_detail.html", job=job, tab=tab, applicants=applicants,
                           matches=matches, total=total, args=request.args, pager=pager)


@app.route("/admin/jobs/<int:job_id>/shortlist/<int:cand_id>", methods=["POST"])
@admin_required
def admin_shortlist_from_pool(job_id, cand_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    cand = db.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone()
    if not job or not cand:
        abort(404)
    upsert_application(db, cand, job, source="Talent pool", status="Shortlisted")
    db.commit()
    flash(f"{cand['full_name']} added to this job's shortlist.", "success")
    return redirect(request.referrer or url_for("admin_job_detail", job_id=job_id))


@app.route("/admin/jobs/<int:job_id>/export.csv")
@admin_required
def admin_job_export(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        abort(404)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rank", "Reference", "Name", "Email", "Phone", "Location", "Score %", "Status",
                "Missing required skills", "Applied"])
    for i, a in enumerate(ranked_applicants(db, job_id, request.args), 1):
        missing = a["breakdown"].get("components", {}).get("required", {}).get("missing", [])
        w.writerow([i, a["reference"], a["full_name"], a["email"], a["phone"], a["location"],
                    a["score"], a["status"], "; ".join(missing), a["created_at"][:10]])
    name = secure_filename(job["title"]) or "job"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}_applicants.csv"})


# ------------------------------------------------------- admin: candidates

@app.route("/admin/candidates")
@admin_required
def admin_candidates():
    db = get_db()
    args = request.args
    sql, params = "SELECT * FROM candidates WHERE 1=1", []
    if args.get("q"):
        for term in args["q"].split():
            sql += " AND (full_name LIKE ? OR email LIKE ? OR skills LIKE ? OR cv_text LIKE ? OR current_title LIKE ?)"
            params += [f"%{term}%"] * 5
    if args.get("location"):
        sql += " AND location LIKE ?"
        params.append(f"%{args['location']}%")
    min_exp = args.get("min_exp", type=int, default=0)
    if min_exp:
        sql += " AND COALESCE(years_experience, 0) >= ?"
        params.append(min_exp)
    rows = db.execute(sql + " ORDER BY updated_at DESC", params).fetchall()

    job = None
    job_id = args.get("job_id", type=int)
    min_score = args.get("min_score", type=float, default=0)
    results = []
    if job_id:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    for c in rows:
        item = {"c": c, "score": None, "breakdown": None}
        if job:
            item["score"], item["breakdown"] = ats.score_candidate(job, c)
            if item["score"] < min_score:
                continue
        results.append(item)
    if job:
        results.sort(key=lambda r: -r["score"])
    results, pager = paginate(results, 50)
    jobs = db.execute("SELECT id, title, status FROM jobs ORDER BY status DESC, title").fetchall()
    return render_template("admin/candidates.html", results=results, jobs=jobs, job=job, args=args, pager=pager)


@app.route("/admin/candidates/<int:cand_id>")
@admin_required
def admin_candidate(cand_id):
    db = get_db()
    cand = db.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone()
    if not cand:
        abort(404)
    apps = db.execute("""SELECT a.*, j.title FROM applications a LEFT JOIN jobs j ON j.id = a.job_id
                         WHERE a.candidate_id = ? ORDER BY a.created_at DESC""", (cand_id,)).fetchall()
    apps = [dict(a, breakdown=json.loads(a["breakdown"] or "{}")) for a in apps]
    return render_template("admin/candidate.html", cand=cand, apps=apps)


@app.route("/admin/candidates/<int:cand_id>/cv")
@admin_required
def admin_candidate_cv(cand_id):
    cand = get_db().execute("SELECT cv_filename, cv_mimetype, cv_data FROM candidates WHERE id = ?",
                            (cand_id,)).fetchone()
    if not cand:
        abort(404)
    disposition = "inline" if cand["cv_mimetype"] == "application/pdf" and not request.args.get("download") \
        else "attachment"
    return Response(cand["cv_data"], mimetype=cand["cv_mimetype"],
                    headers={"Content-Disposition": f'{disposition}; filename="{cand["cv_filename"]}"',
                             "X-Content-Type-Options": "nosniff"})


@app.route("/admin/candidates/<int:cand_id>/delete", methods=["POST"])
@admin_required
def admin_candidate_delete(cand_id):
    db = get_db()
    db.execute("DELETE FROM candidates WHERE id = ?", (cand_id,))
    db.commit()
    flash("Candidate and their CV permanently deleted.", "success")
    return redirect(url_for("admin_candidates"))


@app.route("/admin/applications/<int:app_id>/update", methods=["POST"])
@admin_required
def admin_application_update(app_id):
    db = get_db()
    status = request.form.get("status")
    if status and status not in STATUSES:
        abort(400)
    db.execute("""UPDATE applications SET status = COALESCE(?, status), notes = COALESCE(?, notes),
                  updated_at = ? WHERE id = ?""",
               (status, request.form.get("notes"), now(), app_id))
    db.commit()
    flash("Application updated.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/applications/bulk", methods=["POST"])
@admin_required
def admin_application_bulk():
    ids = request.form.getlist("app_ids", type=int)
    status = request.form.get("status")
    if ids and status in STATUSES:
        db = get_db()
        db.executemany("UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
                       [(status, now(), i) for i in ids])
        db.commit()
        flash(f"{len(ids)} application(s) moved to {status}.", "success")
    else:
        flash("Select at least one applicant and a status.", "error")
    return redirect(request.referrer or url_for("admin_dashboard"))


# ---------------------------------------------------------------------- CLI

DEMO_JOBS = [
    {
        "title": "HR Business Partner", "department": "Human Resources", "location": "Durban, KZN",
        "job_type": "Full-time",
        "description": "Partner with business leaders to deliver HR strategy, employee relations, "
                       "performance management and talent development across Icebolethu Group. "
                       "Drive recruitment, onboarding, labour relations and compliance with the BCEA and LRA.",
        "required_skills": "employee relations, labour relations, performance management, recruitment, ms excel",
        "preferred_skills": "sage, payroll, coaching, ccma",
        "min_experience": 5, "min_education": 4,
    },
    {
        "title": "Funeral Policy Sales Consultant", "department": "Sales", "location": "Pietermaritzburg, KZN",
        "job_type": "Full-time",
        "description": "Sell and service funeral policies to new and existing clients, meet monthly sales "
                       "targets, build community relationships and deliver excellent customer service. "
                       "Must be FAIS compliant.",
        "required_skills": "sales, customer service, fais, communication",
        "preferred_skills": "re5, isizulu, drivers licence, crm",
        "min_experience": 2, "min_education": 1,
    },
    {
        "title": "Data Analyst", "department": "Finance", "location": "Johannesburg, GP",
        "job_type": "Contract",
        "description": "Build reports and dashboards, analyse policy and claims data, and support "
                       "management with insights. Work with finance and actuarial teams.",
        "required_skills": "sql, power bi, ms excel, data analysis",
        "preferred_skills": "python, actuarial, insurance",
        "min_experience": 3, "min_education": 4,
    },
]


def seed_demo():
    init_db()
    db = sqlite3.connect(DB_PATH)
    for job in DEMO_JOBS:
        if not db.execute("SELECT 1 FROM jobs WHERE title = ?", (job["title"],)).fetchone():
            db.execute("""INSERT INTO jobs (title, department, location, job_type, description, required_skills,
                          preferred_skills, min_experience, min_education, status, created_at)
                          VALUES (:title, :department, :location, :job_type, :description, :required_skills,
                          :preferred_skills, :min_experience, :min_education, 'Open', :created_at)""",
                       {**job, "created_at": now()})
    db.commit()
    db.close()
    print("Demo jobs added.")


def require_cv_libraries():
    """Stop with a clear message if this Python can't read PDF/Word CVs."""
    missing = ats.missing_packages()
    if missing:
        sys.exit(
            "\n  The ATS cannot read CVs: missing " + ", ".join(missing) + f" in this Python ({sys.executable}).\n"
            "  Install the portal's requirements into the environment you run it with:\n\n"
            f"      {sys.executable} -m pip install -r requirements.txt\n")


def reprocess_cvs():
    """Re-extract text from every stored CV and re-score every application."""
    require_cv_libraries()
    init_db()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    fixed = 0
    for c in db.execute("SELECT id, cv_filename, cv_data, cv_text FROM candidates").fetchall():
        text = ats.extract_text(c["cv_filename"], c["cv_data"])
        if text != (c["cv_text"] or ""):
            db.execute("UPDATE candidates SET cv_text = ? WHERE id = ?", (text, c["id"]))
            fixed += 1
    jobs = db.execute("SELECT * FROM jobs WHERE id IN (SELECT DISTINCT job_id FROM applications)").fetchall()
    for job in jobs:
        rescore_job(db, job)
    db.commit()
    unreadable = db.execute("SELECT COUNT(*) FROM candidates WHERE TRIM(COALESCE(cv_text, '')) = ''").fetchone()[0]
    db.close()
    print(f"Updated text for {fixed} CV(s) and re-scored applications for {len(jobs)} job(s).")
    if unreadable:
        print(f"{unreadable} CV(s) still have no text. These are likely scanned images.")


def set_password():
    import getpass
    init_db()
    username = input("Admin username [admin]: ").strip() or "admin"
    password = getpass.getpass("New password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")
    db = sqlite3.connect(DB_PATH)
    db.execute("""INSERT INTO admins (username, password_hash) VALUES (?, ?)
                  ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash""",
               (username, generate_password_hash(password)))
    db.commit()
    db.close()
    print(f"Password set for '{username}'.")


init_db()

def prepare_port(port):
    """Make `python app.py` always start. If an older copy of this portal is
    still running on the port it is stopped; if another program holds the
    port, the next free port is used instead."""
    import signal
    import socket
    import subprocess
    import time

    def busy(p):
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", p)) == 0

    def run(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True).stdout
        except FileNotFoundError:
            return ""

    if not busy(port):
        return port
    for pid in run("lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN").split():
        command_line = run("ps", "-o", "command=", "-p", pid)
        cwd = next((l[1:] for l in run("lsof", "-a", "-p", pid, "-d", "cwd", "-Fn").splitlines()
                    if l.startswith("n")), "")
        if "app.py" in command_line and os.path.realpath(cwd) == os.path.realpath(BASE_DIR):
            print(f" * Stopping an older copy of the portal on port {port} (PID {pid})")
            os.kill(int(pid), signal.SIGTERM)
    for _ in range(50):
        if not busy(port):
            return port
        time.sleep(0.1)
    for p in range(port + 1, port + 50):
        if not busy(p):
            print(f" * Port {port} is used by another program, so using port {p} instead")
            return p
    sys.exit(f"No free port found near {port}. Start with PORT=8000 python app.py")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "seed-demo":
        seed_demo()
    elif command == "set-password":
        set_password()
    elif command == "reprocess-cvs":
        reprocess_cvs()
    else:
        require_cv_libraries()
        port = int(os.environ.get("PORT", 5000))
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":  # not inside the reloader's child process
            port = prepare_port(port)
            os.environ["PORT"] = str(port)  # the reloader's child process inherits this
        # The reloader restarts the server automatically whenever a .py file changes,
        # so code updates show up without a manual restart. Set FLASK_RELOAD=0 to turn it off.
        app.run(debug=os.environ.get("FLASK_DEBUG") == "1",
                use_reloader=os.environ.get("FLASK_RELOAD", "1") == "1",
                port=port)
