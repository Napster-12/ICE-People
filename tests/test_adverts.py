"""Phase 5: job adverts, the JD library and publishing (REQ-JA-001–008, spec §4.4)."""
import io
from datetime import timedelta

import pytest

from app.extensions import db
from app.integrations import get_adapter
from app.models import (AdvertPosting, Application, Branch, IntegrationLog, Job, JobDescriptionTemplate, JobFamily,
                        Notification, Requisition)
from app.services import adverts, requisitions, workflow
from app.services.dates import today
from app.services.errors import DomainError
from tests.conftest import login, make_requisition, user


def approve_all(entity_type, entity_id, action="approve"):
    """Have whoever holds each step act until the instance is finished."""
    inst = workflow.latest_instance(entity_type, entity_id)
    while inst.status == "Pending":
        step = inst.current_step
        workflow.act(step, step.assignee, action, f"{action} from {step.assignee.username}")
    return inst


def approved_requisition(**position_fields):
    req = make_requisition(user("linemanager"))
    position = req.approved_position
    position.branch_id = position_fields.pop("branch_id", None)
    position.minimum_requirements = position_fields.pop("minimum_requirements", "Matric\n- 2 years' sales experience")
    for k, v in position_fields.items():
        setattr(position, k, v)
    approve_all("requisition", req.id)
    assert req.status == "Approved"
    return req


def ready_advert(req=None):
    """A drafted advert with every mandatory field filled in."""
    req = req or approved_requisition()
    job = adverts.draft_from_requisition(req, user("recruiter"))
    adverts.save(job, {"location": "Durban", "min_education": 1, "min_experience": 2}, user("recruiter"))
    return job


def published_advert(**kwargs):
    job = ready_advert(**kwargs)
    adverts.submit(job, user("recruiter"))
    approve_all("advert", job.id)
    return job


# ------------------------------------------------------------------ drafting

def test_only_fully_approved_requisitions_can_be_advertised(app):
    req = make_requisition(user("linemanager"))
    assert req.status == "In Approval"
    with pytest.raises(DomainError, match="fully approved"):
        adverts.draft_from_requisition(req, user("recruiter"))
    assert req not in adverts.ready_query().all()
    approve_all("requisition", req.id)
    assert req in adverts.ready_query().all()


def test_draft_is_filled_from_requisition_and_position(app):
    db.session.add(Branch(code="DBN", name="Durban"))
    db.session.flush()
    req = approved_requisition(branch_id=Branch.query.one().id)
    job = adverts.draft_from_requisition(req, user("recruiter"))
    assert job.reference.startswith("ADV-") and job.status == "Draft" and job.requisition is req
    assert (job.title, job.department, job.location, job.job_type) == ("Sales Consultant", "Sales", "Durban", "Full-time")
    assert "MINIMUM REQUIREMENTS\n- Matric\n- 2 years' sales experience" in job.description
    assert "Employment Equity Act" in job.ee_statement
    assert job.closing_date == today() + timedelta(days=21)
    assert job.channels == ["Internal", "Intranet"]
    assert job.version == 1 and job.versions[0].data["title"] == "Sales Consultant"
    assert req not in adverts.ready_query().all()
    with pytest.raises(DomainError, match="already has an advert"):
        adverts.draft_from_requisition(req, user("recruiter"))


def test_draft_starts_from_matching_jd_template(app):
    family = JobFamily(code="SAL", name="Sales")
    db.session.add(family)
    db.session.flush()
    by_family = JobDescriptionTemplate(title="Sales Agent", job_family_id=family.id, description="SELLING\n- Sell",
                                       min_education=1, min_experience=1, review_date=today(), active=True)
    by_title = JobDescriptionTemplate(title="sales consultant", description="ABOUT THE ROLE\nConsult.",
                                      required_skills="sales, crm", min_education=2, min_experience=3,
                                      review_date=today(), active=True)
    db.session.add_all([by_family, by_title])
    req = approved_requisition(job_family_id=family.id)
    assert adverts.match_template(req.approved_position) is by_title
    job = adverts.draft_from_requisition(req, user("recruiter"))
    assert job.jd_template is by_title
    assert job.description.startswith("ABOUT THE ROLE\nConsult.") and "MINIMUM REQUIREMENTS" in job.description
    assert (job.required_skills, job.min_education, job.min_experience) == ("sales, crm", 2, 3)
    by_title.active = False
    assert adverts.match_template(req.approved_position) is by_family

    other = approved_requisition(job_family_id=family.id)
    blank = adverts.draft_from_requisition(other, user("recruiter"), use_library=False)
    assert blank.jd_template is None and blank.min_education == 0


def test_mandatory_content_before_approval(app):
    req = approved_requisition()
    job = adverts.draft_from_requisition(req, user("recruiter"))
    problems = adverts.problems(job)
    assert "Enter the location." in problems and "Choose the minimum qualification." in problems
    adverts.save(job, {"ee_statement": "", "closing_date": today()}, user("recruiter"))
    with pytest.raises(DomainError) as exc:
        adverts.submit(job, user("recruiter"))
    for text in ("location", "closing date must be in the future", "minimum qualification", "equal opportunity"):
        assert text in str(exc.value)
    assert job.status == "Draft"


def test_edits_are_versioned_and_only_while_editable(app):
    job = ready_advert()
    assert job.version == 2
    adverts.save(job, {"location": "Durban"}, user("recruiter"))   # nothing changed: no new version
    assert job.version == 2
    adverts.submit(job, user("recruiter"))
    with pytest.raises(DomainError, match="Only draft or returned"):
        adverts.save(job, {"title": "Changed"}, user("recruiter"))


# ---------------------------------------------------------- approve and publish

def test_hr_manager_approval_publishes_everywhere(app):
    job = ready_advert()
    req = job.requisition
    inst = adverts.submit(job, user("recruiter"))
    assert job.status == "In Approval" and job not in Job.query.filter_by(status="Open").all()
    assert [s.approver.username for s in inst.steps] == ["hrmanager"]
    approve_all("advert", job.id)

    assert job.status == "Open" and job.published_at is not None
    assert req.status == "Advertised" and req.approved_position.status == "In recruitment"
    postings = {p.channel: p for p in job.postings}
    assert set(postings) == {"Careers site", "Internal", "Intranet"}
    assert all(p.status == "Live" for p in postings.values())
    assert postings["Internal"].external_id.startswith("INT-")
    assert IntegrationLog.query.filter_by(system="job_portals", method="publish_advert", success=True).count() == 2
    note = Notification.query.filter_by(user_id=user("recruiter").id).filter(Notification.title.like("Advert live%")).one()
    assert "Careers site, Internal, Intranet" in note.body
    from app.services.careers import open_jobs_query
    assert job in open_jobs_query().all()


def test_returned_advert_is_fixed_and_resubmitted(app):
    job = ready_advert()
    adverts.submit(job, user("recruiter"))
    approve_all("advert", job.id, action="return")
    assert job.status == "Returned"
    adverts.save(job, {"title": "Senior Sales Consultant"}, user("recruiter"))
    inst = adverts.submit(job, user("recruiter"))
    assert inst.round == 2
    approve_all("advert", job.id)
    assert job.status == "Open" and job.title == "Senior Sales Consultant"


def test_rejected_advert_frees_the_requisition(app):
    job = ready_advert()
    adverts.submit(job, user("recruiter"))
    approve_all("advert", job.id, action="reject")
    assert job.status == "Rejected" and job.requisition.status == "Approved"
    assert job.requisition in adverts.ready_query().all()
    assert adverts.draft_from_requisition(job.requisition, user("recruiter")).id != job.id


def test_hr_manager_cant_approve_their_own_advert(app):
    req = approved_requisition()
    job = adverts.draft_from_requisition(req, user("hrmanager"))
    adverts.save(job, {"location": "Durban", "min_education": 1, "min_experience": 0}, user("hrmanager"))
    inst = adverts.submit(job, user("hrmanager"))
    assert inst.steps[0].approver.username == "grouphr"


def test_failed_channel_doesnt_stop_publishing(app):
    portal = get_adapter("job_portals")
    portal.forced_failures["publish_advert"] = 3   # Internal fails all three attempts
    try:
        job = published_advert()
    finally:
        portal.forced_failures.clear()
    postings = {p.channel: p for p in job.postings}
    assert job.status == "Open"
    assert postings["Internal"].status == "Failed" and postings["Intranet"].status == "Live"
    assert "Couldn't publish to: Internal" in Notification.query.filter(Notification.title.like("Advert live%")).one().body


# ---------------------------------------------------------- close and re-advertise

def test_expired_adverts_close_and_can_be_readvertised(app):
    job = published_advert()
    job.closing_date = today() - timedelta(days=1)
    assert adverts.close_expired() == 1
    assert job.status == "Closed" and "passed" in job.close_reason
    assert all(p.status == "Closed" for p in job.postings)
    assert IntegrationLog.query.filter_by(method="close_advert").count() == 2
    assert Notification.query.filter(Notification.title.like("Advert closed%")).count() == 1
    assert adverts.close_expired() == 0

    adverts.readvertise(job, user("recruiter"))
    assert (job.status, job.cycle) == ("Draft", 2) and job.closing_date > today()
    adverts.submit(job, user("recruiter"))
    approve_all("advert", job.id)
    assert job.status == "Open" and job.requisition.status == "Advertised"
    assert {p.cycle for p in job.postings} == {1, 2}
    assert [c for c, _ in adverts.stats(job)["cycles"]] == [2, 1]
    with pytest.raises(DomainError):
        adverts.readvertise(job, user("recruiter"))


def test_closing_old_portal_jobs(app):
    old = Job(title="Imported", description="x", status="Open", closing_date=today() - timedelta(days=2),
              created_at=today())
    db.session.add(old)
    assert adverts.close_expired() == 1 and old.status == "Closed"


def test_closing_requisition_unfilled_withdraws_the_advert(app):
    live = published_advert()
    requisitions.close_unfilled(live.requisition, user("hradmin"), "Budget cut")
    assert live.status == "Closed" and "closed unfilled" in live.close_reason

    pending = ready_advert()
    adverts.submit(pending, user("recruiter"))
    requisitions.close_unfilled(pending.requisition, user("hradmin"), "No longer needed")
    assert pending.status == "Cancelled"
    assert workflow.latest_instance("advert", pending.id).status == "Cancelled"


# ------------------------------------------------------------------- tracking

def test_views_and_applications_counted_per_channel(app, client):
    job = ready_advert()
    adverts.save(job, {"channels": ["LinkedIn"]}, user("recruiter"))
    adverts.submit(job, user("recruiter"))
    approve_all("advert", job.id)
    db.session.commit()

    assert client.get(f"/jobs/{job.id}?src=linkedin").status_code == 200
    client.post(f"/jobs/{job.id}", data={f"q{i}": "yes" for i in range(5)})
    r = client.post(f"/jobs/{job.id}/apply", content_type="multipart/form-data",
                    data={"full_name": "Thabo Nkosi", "email": "thabo@example.test", "consent": "1",
                          "cv": (io.BytesIO(b"Thabo Nkosi sales"), "cv.docx")})
    assert r.status_code == 302
    client.get(f"/jobs/{job.id}?src=unknown-site")
    postings = {p.channel: p for p in AdvertPosting.query.filter_by(job_id=job.id)}
    assert (postings["LinkedIn"].views, postings["LinkedIn"].applications) == (1, 1)
    assert postings["Careers site"].views == 1
    application = Application.query.filter_by(job_id=job.id).one()
    assert application.source == "LinkedIn"
    application.status = "Hired"
    assert adverts.stats(job)["hires"] == {"LinkedIn": 1}


# ------------------------------------------------------------------ JD library

def test_jd_review_reminders_once(app):
    soon = JobDescriptionTemplate(title="Cashier", description="x", review_date=today() + timedelta(days=10),
                                  active=True, min_education=0, min_experience=0)
    later = JobDescriptionTemplate(title="Driver", description="x", review_date=today() + timedelta(days=90),
                                   active=True, min_education=0, min_experience=0)
    db.session.add_all([soon, later])
    assert adverts.remind_jd_reviews() == 1
    assert adverts.remind_jd_reviews() == 0
    assert Notification.query.filter(Notification.title == "JD review due: Cashier").count() == 2  # recruiter, hradmin
    adverts.save_template(soon, {"title": "Cashier", "job_family_id": None, "description": "x", "required_skills": "",
                                 "preferred_skills": "", "min_experience": 0, "min_education": 0,
                                 "review_date": today() + timedelta(days=5), "active": True}, user("recruiter"))
    assert soon.reminded_at is None


# --------------------------------------------------------------------- pages

def test_hr_walks_through_the_pages(app, client):
    req = approved_requisition()
    db.session.commit()
    login(client, "recruiter")
    assert b"Create advert" in client.get(f"/requisitions/{req.id}").data
    page = client.get("/adverts/")
    assert page.status_code == 200 and req.reference.encode() in page.data
    assert client.get(f"/adverts/new/{req.id}").status_code == 200
    r = client.post(f"/adverts/new/{req.id}", data={"template_id": "0"})
    job = Job.query.filter_by(requisition_id=req.id).one()
    assert r.location.endswith(f"/adverts/{job.id}/edit")
    assert client.get(f"/adverts/{job.id}/edit").status_code == 200

    form = {"title": "Sales Consultant", "location": "Durban", "job_type": "Full-time", "description": "Sell things.",
            "min_experience": "2", "min_education": "1", "closing_date": (today() + timedelta(days=14)).isoformat(),
            "ee_statement": "We are an equal opportunity employer.", "channels": ["PNet", "LinkedIn"],
            "action": "submit"}
    r = client.post(f"/adverts/{job.id}/edit", data=form)
    assert r.location.endswith(f"/adverts/{job.id}")
    assert job.status == "In Approval" and job.channels == ["PNet", "LinkedIn"]
    assert b"Advert " + job.reference.encode() in client.get(f"/requisitions/{req.id}").data

    client.post("/logout")
    login(client, "hrmanager")
    assert b"Your decision" in client.get(f"/adverts/{job.id}").data
    step = workflow.latest_instance("advert", job.id).current_step
    client.post(f"/approvals/steps/{step.id}/act", data={"action": "approve", "comment": "Looks good"})
    assert db.session.get(Job, job.id).status == "Open"
    assert db.session.get(Requisition, req.id).status == "Advertised"
    assert b"Close advert" in client.get(f"/adverts/{job.id}").data
    r = client.post(f"/adverts/{job.id}/close", data={"reason": "Enough applicants"})
    assert db.session.get(Job, job.id).status == "Closed"
    r = client.post(f"/adverts/{job.id}/readvertise")
    assert r.location.endswith(f"/adverts/{job.id}/edit") and db.session.get(Job, job.id).cycle == 2


def test_jd_library_pages(app, client):
    login(client, "recruiter")
    assert client.get("/adverts/library").status_code == 200
    assert client.get("/adverts/library/new").status_code == 200
    r = client.post("/adverts/library/new", data={"title": "Cashier", "description": "TILLS\n- Count cash",
                                                  "min_education": "1", "min_experience": "1",
                                                  "review_date": (today() + timedelta(days=365)).isoformat(),
                                                  "active": "1"})
    assert r.location.endswith("/adverts/library")
    t = JobDescriptionTemplate.query.one()
    assert (t.title, t.updated_by.username, t.active) == ("Cashier", "recruiter", True)
    r = client.post(f"/adverts/library/{t.id}/edit", data={"title": "", "description": "x", "review_date": ""})
    assert r.status_code == 200 and b"Enter the job title" in r.data


def test_jd_ats_weights_are_validated_and_saved(app, client):
    from app.services import ats
    assert ats.parse_weights({k: str(v) for k, v in ats.WEIGHTS.items()}) == (None, [])     # standard
    assert ats.parse_weights({}) == (None, [])
    own = {"required": "30", "preferred": "0", "experience": "50", "education": "10", "keywords": "10"}
    assert ats.parse_weights(own) == ({"required": 30, "preferred": 0, "experience": 50, "education": 10,
                                       "keywords": 10}, [])
    assert "add up to 100" in ats.parse_weights(dict(own, keywords="20"))[1][0]
    assert "whole number" in ats.parse_weights(dict(own, required="lots"))[1][0]

    login(client, "recruiter")
    data = {"title": "Driver", "description": "ROUTES\n- Drive", "review_date": (today() + timedelta(days=365)).isoformat(),
            "active": "1", **{f"w_{k}": v for k, v in own.items()}}
    r = client.post("/adverts/library/new", data=dict(data, w_keywords="20"))
    assert r.status_code == 200 and b"add up to 100" in r.data and JobDescriptionTemplate.query.count() == 0
    client.post("/adverts/library/new", data=data)
    t = JobDescriptionTemplate.query.one()
    assert t.ats_weights["experience"] == 50 and b"Own" in client.get("/adverts/library").data


def test_advert_copies_jd_weights_and_scores_with_them(app):
    from app.services import ats
    jd = JobDescriptionTemplate(title="Sales Consultant", description="SELLING\n- Sell", required_skills="sales",
                                min_experience=4, review_date=today(), active=True,
                                ats_weights={"required": 0, "preferred": 0, "experience": 100, "education": 0,
                                             "keywords": 0})
    db.session.add(jd)
    job = adverts.draft_from_requisition(approved_requisition(), user("recruiter"))
    assert job.ats_weights == jd.ats_weights
    from collections import defaultdict
    candidate = defaultdict(str, cv_text="Two years of sales.", skills="sales", years_experience=2, education_level=0)
    score, breakdown = ats.score_candidate(job, candidate)
    assert list(breakdown["components"]) == ["experience"] and score == 50.0     # only experience counts: 2 of 4 years
    job.ats_weights = None
    assert set(ats.score_candidate(job, candidate)[1]["components"]) > {"experience"}   # standard weights again


def test_adverts_are_hr_only(app, client):
    login(client, "linemanager")
    assert client.get("/adverts/").status_code == 403
    assert client.get("/adverts/library").status_code == 403


def test_ee_statement_setting_is_text(app, client):
    login(client, "it")
    from app.models import Setting
    data = {s.key: s.value for s in Setting.query.all()}
    data["advert_ee_statement"] = "Icebolethu is an equal opportunity employer."
    client.post("/admin/settings", data=data)
    assert db.session.get(Setting, "advert_ee_statement").value == "Icebolethu is an equal opportunity employer."
