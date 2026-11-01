"""Shortlist review (1 Nov 2026): HR shortlists → the Department Manager picks who goes to interview → HR is notified
and emails interview invitations and regrets."""
import pytest

from app.extensions import db
from app.models import Application, Candidate, CandidateMessage, Notification
from app.services import careers, shortlisting
from app.services.errors import DomainError
from tests.conftest import login, user
from tests.test_adverts import published_advert


def applicants(job, n=3):
    apps = []
    for i in range(n):
        cand = Candidate(full_name=f"Applicant {i}", email=f"applicant{i}@example.test", consent=True)
        db.session.add(cand)
        db.session.flush()
        ref = careers.upsert_application(cand, job, status="Shortlisted")
        db.session.flush()
        apps.append(Application.query.filter_by(reference=ref).one())
    return apps


def test_shortlist_goes_to_the_department_manager_and_back_to_hr(app):
    job = published_advert()                                            # a Sales advert: Department Manager is hod
    first, second, third = applicants(job)
    with pytest.raises(DomainError, match="Shortlist at least one"):
        shortlisting.send_to_department_manager(published_advert(), user("recruiter"))
    review = shortlisting.send_to_department_manager(job, user("recruiter"))
    assert review.reviewer.username == "hod" and set(review.application_ids) == {first.id, second.id, third.id}
    assert Notification.query.filter_by(user_id=user("hod").id).filter(Notification.title.contains("Shortlist")).count()
    with pytest.raises(DomainError, match="still reviewing"):
        shortlisting.send_to_department_manager(job, user("recruiter"))

    with pytest.raises(DomainError, match="Only the Department Manager"):
        shortlisting.complete_review(review, user("linemanager"), [first.id])
    with pytest.raises(DomainError, match="at least one"):
        shortlisting.complete_review(review, user("hod"), [])
    shortlisting.complete_review(review, user("hod"), [first.id, second.id], "Both look strong")
    assert (first.status, second.status, third.status) == ("Interview", "Interview", "Not selected")
    assert review.status == "Completed" and review.selected_ids == sorted([first.id, second.id])
    hr_note = Notification.query.filter_by(user_id=user("recruiter").id).filter(
        Notification.title.contains("Shortlist reviewed")).one()
    assert "picked 2" in hr_note.body and "Both look strong" in hr_note.body


def test_hr_sends_invitations_and_regrets(app):
    job = published_advert()
    first, second, third = applicants(job)
    review = shortlisting.send_to_department_manager(job, user("recruiter"))
    shortlisting.complete_review(review, user("hod"), [first.id, second.id])
    with pytest.raises(DomainError, match="date, time, venue"):
        shortlisting.send_messages(job, user("recruiter"), "invitation", [first.id], {})
    sent = shortlisting.send_messages(job, user("recruiter"), "invitation", [first.id, second.id, third.id],
                                      {"date": "2026-11-10", "time": "10:00", "venue": "Head office"})
    assert sent == 2                                                    # third wasn't picked: no invitation
    invite = CandidateMessage.query.filter_by(application_id=first.id).one()
    assert invite.kind == "invitation" and "2026-11-10" in invite.body and "Head office" in invite.body
    assert first.status == "Interview"
    assert shortlisting.send_messages(job, user("recruiter"), "regret", [third.id]) == 1
    assert third.status == "Rejected" and "not successful" in third.messages[0].body


def test_pages_for_hr_and_the_department_manager(app, client):
    job = published_advert()
    first, second = applicants(job, 2)
    db.session.commit()
    login(client, "recruiter")
    page = client.get(f"/recruitment/jobs/{job.id}").get_data(as_text=True)
    assert "Shortlist and interviews" in page and "Send shortlist to" in page
    assert client.post(f"/recruitment/jobs/{job.id}/shortlist/send").status_code == 302
    review = shortlisting.pending_review(job)
    assert review is not None and client.get(f"/recruitment/jobs/{job.id}/messages?kind=regret").status_code == 200


def test_department_manager_reviews_on_their_page(app, client):
    job = published_advert()
    first, second = applicants(job, 2)
    review = shortlisting.send_to_department_manager(job, user("recruiter"))
    db.session.commit()
    login(client, "hod")
    assert job.title.encode() in client.get("/recruitment/shortlists").data
    assert b"Pick who goes to interview" in client.get("/dashboard").data           # task on their home page
    assert client.get(f"/recruitment/shortlists/{review.id}/cv/{first.id}").status_code == 404   # no CV uploaded
    assert shortlisting.reviewer_can_see(user("hod"), review, first)
    assert not shortlisting.reviewer_can_see(user("otherhod"), review, first)      # another Department Manager
    r = client.post(f"/recruitment/shortlists/{review.id}", data={"app_ids": [str(second.id)], "comment": "Only one"})
    assert r.status_code == 302
    assert db.session.get(Application, second.id).status == "Interview"
    assert db.session.get(Application, first.id).status == "Not selected"
