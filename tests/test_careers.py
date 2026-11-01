"""The original careers site and ATS, now inside the HR system."""
import io

from app.extensions import db
from app.models import Application, Candidate, Job
from app.services.dates import now
from tests.conftest import login


def make_job():
    job = Job(title="Data Analyst", department="Finance", location="Durban", job_type="Full-time",
              description="Build reports with SQL and Power BI.", required_skills="sql, power bi",
              min_experience=2, status="Open", created_at=now())
    db.session.add(job)
    db.session.commit()
    return job


def apply(client, job, email="thabo@example.test", consent=True):
    data = {"full_name": "Thabo Nkosi", "email": email, "years_experience": "3", "skills": "SQL, Power BI",
            "cv": (io.BytesIO(b"Thabo Nkosi\nSQL and Power BI analyst"), "cv.docx")}
    if consent:
        data["consent"] = "1"
    pass_check(client, job)
    return client.post(f"/jobs/{job.id}/apply", data=data, content_type="multipart/form-data")


def answers(*values):
    return {f"q{i}": v for i, v in enumerate(values)}


def pass_check(client, job):
    r = client.post(f"/jobs/{job.id}", data=answers(*["yes"] * 5))
    assert r.status_code == 302 and r.location.endswith(f"/jobs/{job.id}/apply")
    return r


def test_eligibility_questions_from_position(app):
    from app.services.careers import eligibility_questions
    from tests.conftest import make_requisition, user
    req = make_requisition(user("linemanager"), submit=False)
    req.approved_position.minimum_requirements = "- Honours (NQF 8) in Computer Systems\n\nValid driver's licence."
    job = make_job()
    job.requisition = req
    questions = eligibility_questions(job)
    assert len(questions) == 5
    assert questions[0]["text"] == "Do you have Honours (NQF 8) in Computer Systems?"
    assert questions[1]["reason"] == "This role requires Valid driver's licence."
    assert questions[2]["text"] == "Do you have at least 2 years' relevant work experience?"   # then the advert
    assert "sql, power bi" in questions[3]["text"]


def test_eligibility_questions_always_five(app):
    from app.services.careers import eligibility_questions
    bare = Job(title="Cleaner", description="Keep the office clean.", status="Open", created_at=now())
    assert len(eligibility_questions(bare)) == 5
    full = make_job()
    full.min_education = 4
    full.requisition = None
    assert [q["text"] for q in eligibility_questions(full)][:3] == [
        "Do you have at least a Bachelor's Degree qualification?",
        "Do you have at least 2 years' relevant work experience?",
        "Do you have working experience in sql, power bi?"]


def test_eligibility_problems(app):
    from app.services.careers import eligibility_problems
    job = make_job()
    assert eligibility_problems(job, answers(*["yes"] * 5)) == (False, [])
    assert eligibility_problems(job, answers("yes", "yes"))[0] is True
    unanswered, reasons = eligibility_problems(job, answers("no", "yes", "yes", "yes", "yes"))
    assert not unanswered and reasons == ["This role requires at least 2 years' relevant work experience."]


def test_failed_check_goes_to_talent_pool(client):
    job = make_job()
    r = client.post(f"/jobs/{job.id}", data=answers("no", "yes", "yes", "yes", "yes"))
    assert r.status_code == 302 and r.location.endswith("/talent-pool")
    page = client.get("/talent-pool").data
    assert b"apply for Data Analyst yet" in page and b"2 years" in page
    assert b"apply for Data Analyst yet" not in client.get("/talent-pool").data    # shown once
    assert client.get(f"/jobs/{job.id}/apply").status_code == 302                     # step 2 stays closed
    assert Candidate.query.count() == 0 and Application.query.count() == 0


def test_unanswered_check_stays_on_step_one(client):
    job = make_job()
    r = client.post(f"/jobs/{job.id}", data=answers("yes"))
    assert r.status_code == 200 and b"answer every question" in r.data


def test_apply_needs_the_check(client):
    job = make_job()
    r = client.get(f"/jobs/{job.id}/apply")
    assert r.status_code == 302 and r.location.endswith(f"/jobs/{job.id}#apply")
    pass_check(client, job)
    assert b"Submit application" in client.get(f"/jobs/{job.id}/apply").data


def test_careers_pages(client):
    job = make_job()
    assert client.get("/").status_code == 200
    assert b"Data Analyst" in client.get("/").data
    assert client.get(f"/jobs/{job.id}").status_code == 200
    assert client.get("/talent-pool").status_code == 200
    assert client.get("/status").status_code == 200


def test_application_needs_consent(client):
    job = make_job()
    r = apply(client, job, consent=False)
    assert r.status_code == 200 and Candidate.query.count() == 0


def test_apply_and_track(client, app):
    job = make_job()
    r = apply(client, job)
    assert r.status_code == 302
    cand = Candidate.query.one()
    assert cand.consent and cand.consent_at and cand.cv_file.entity_type == "candidate"
    app_row = Application.query.filter_by(job_id=job.id).one()
    assert Application.query.filter_by(job_id=None).count() == 1          # also in the talent pool
    r = client.post("/status", data={"reference": app_row.reference, "email": "thabo@example.test"})
    assert b"Data Analyst" in r.data


def test_ats_admin_pages(client):
    job = make_job()
    apply(client, job)
    login(client, "recruiter")
    cand = Candidate.query.one()
    for url in ["/recruitment/", "/recruitment/jobs", f"/recruitment/jobs/{job.id}",
                f"/recruitment/jobs/{job.id}?tab=pool", "/recruitment/candidates",
                f"/recruitment/candidates?job_id={job.id}", f"/recruitment/candidates/{cand.id}",
                f"/recruitment/candidates/{cand.id}/cv", f"/recruitment/jobs/{job.id}/export.csv"]:
        assert client.get(url).status_code == 200, url
    # New openings are adverts raised from approved requisitions.
    assert client.get("/recruitment/jobs/new").headers["Location"].endswith("/adverts/")
    app_row = Application.query.filter_by(job_id=job.id).one()
    client.post(f"/recruitment/applications/{app_row.id}/update", data={"status": "Shortlisted", "notes": "Strong"})
    assert db.session.get(Application, app_row.id).status == "Shortlisted"


def test_old_admin_urls_redirect(client):
    assert "/login" in client.get("/admin/login").headers["Location"]
    login(client, "recruiter")
    assert client.get("/admin/").headers["Location"].endswith("/dashboard")


def test_legacy_import(app, tmp_path):
    import sqlite3
    from werkzeug.security import generate_password_hash
    from app.cli import import_legacy_db
    path = tmp_path / "portal.db"
    src = sqlite3.connect(path)
    src.executescript("""
    CREATE TABLE admins (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
    CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, department TEXT, location TEXT, job_type TEXT,
      description TEXT, required_skills TEXT, preferred_skills TEXT, min_experience INT, min_education INT,
      closing_date TEXT, status TEXT, created_at TEXT, is_demo INT);
    CREATE TABLE candidates (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, phone TEXT, location TEXT,
      current_title TEXT, years_experience INT, education_level INT, skills TEXT, cv_filename TEXT,
      cv_mimetype TEXT, cv_data BLOB, cv_text TEXT, consent INT, created_at TEXT, updated_at TEXT, is_demo INT);
    CREATE TABLE applications (id INTEGER PRIMARY KEY, reference TEXT, candidate_id INT, job_id INT,
      cover_note TEXT, score REAL, breakdown TEXT, status TEXT, notes TEXT, source TEXT, created_at TEXT, updated_at TEXT);
    """)
    src.execute("INSERT INTO admins VALUES (1, 'oldadmin', ?)", (generate_password_hash("Old-pass-2026"),))
    src.execute("INSERT INTO jobs VALUES (5, 'Clerk', 'Ops', 'Durban', 'Full-time', 'Filing', 'filing', '', 0, 0,"
                " '', 'Open', '2026-01-02T10:00:00', 0)")
    src.execute("INSERT INTO candidates VALUES (7, 'Ann', 'ann@x.test', '', '', '', 1, 0, '', 'cv.txt', 'text/plain',"
                " ?, 'filing', 1, '2026-01-03T10:00:00', '2026-01-03T10:00:00', 0)", (b"filing",))
    src.execute("INSERT INTO applications VALUES (9, 'ICE-AAAA', 7, 5, '', 55.0, '{}', 'New', '', 'Applied',"
                " '2026-01-03T10:00:00', '2026-01-03T10:00:00')")
    src.commit()
    src.close()
    msg = import_legacy_db(str(path))
    assert "1 job(s), 1 candidate(s)" in msg and "1 login(s)" in msg
    assert "0 job(s)" in import_legacy_db(str(path))          # idempotent
    from app.models import User
    old = User.query.filter_by(username="oldadmin").one()
    assert {"HR Admin", "Recruiter"} <= old.role_names and old.check_password("Old-pass-2026")


def test_location_suggests_sa_places(client):
    from app.services.places import PROVINCE_PLACES, SA_PLACES
    assert len(PROVINCE_PLACES) == 9 and len(SA_PLACES) == len(set(SA_PLACES)) > 200
    assert all(p.rsplit(", ", 1)[1] in PROVINCE_PLACES for p in SA_PLACES)
    page = client.get("/talent-pool").get_data(as_text=True)
    assert 'list="sa-places"' in page and '<option value="Durban, KwaZulu-Natal">' in page
    assert '<option value="Gqeberha (Port Elizabeth), Eastern Cape">' in page
