"""Interview panels and scorecards (1 Nov 2026): one panel per advert (the Department Manager plus managers HR
invites), HR sends the invitations, every panellist scores independently, scores are combined and ranked."""
from datetime import datetime

import pytest

from app.extensions import db
from app.models import CandidateMessage, Notification
from app.services import interviews
from app.services.errors import DomainError
from tests.conftest import login, user
from tests.test_adverts import published_advert
from tests.test_shortlisting import applicants

SLOT = datetime(2026, 11, 10, 10, 0)


def interview_ready(n=2, slots=True):
    """A Sales advert with n applicants picked for interview and a panel (Department Manager hod + linemanager);
    with slots=False only the first applicant gets an interview slot."""
    job = published_advert()
    apps = applicants(job, n)
    for a in apps:
        a.status = "Interview"
    panel = interviews.panel_for(job, create=True)
    interviews.add_member(panel, user("linemanager"), user("recruiter"))
    for i, a in enumerate(apps if slots else apps[:1]):
        interviews.set_slot(a, SLOT.replace(hour=10 + i), "Head office boardroom")
    db.session.flush()
    return job, panel, apps


def scores(panel, value):
    return {c["name"]: value for c in panel.criteria}


def test_panel_starts_with_the_department_manager_and_takes_managers_only(app):
    job = published_advert()
    panel = interviews.panel_for(job, create=True)
    assert [(m.user.username, m.role) for m in panel.members] == [("hod", "Department Manager")]
    assert sum(c["weight"] for c in panel.criteria) == 100
    with pytest.raises(DomainError, match="Only managers"):
        interviews.add_member(panel, user("employee"), user("recruiter"))
    interviews.add_member(panel, user("linemanager"), user("recruiter"))
    added = Notification.query.filter_by(user_id=user("linemanager").id).filter(
        Notification.title.contains("You're on the interview panel")).one()       # told straight away
    assert job.title in added.body and "interview dates" in added.body
    assert [p.job_id for p in interviews.waiting_panels(user("linemanager"))] == [job.id]
    with pytest.raises(DomainError, match="already on the panel"):
        interviews.add_member(panel, user("linemanager"), user("recruiter"))
    assert user("employee") not in interviews.eligible_members(panel)
    with pytest.raises(DomainError, match="stays on the panel"):
        interviews.remove_member(panel, panel.members[0], user("recruiter"))


def test_criteria_must_total_100(app):
    job, panel, _apps = interview_ready()
    with pytest.raises(DomainError, match="add up to 100"):
        interviews.save_criteria(panel, [("Skills", "60"), ("Attitude", "30")])
    interviews.save_criteria(panel, [("Skills", "60"), ("Attitude", "40"), ("", "")])
    assert panel.criteria == [{"name": "Skills", "weight": 60}, {"name": "Attitude", "weight": 40}]


def test_hr_sends_invitations_to_panel_and_candidates(app):
    job, panel, apps = interview_ready(slots=False)
    with pytest.raises(DomainError, match="interview slot first"):
        interviews.send_invitations(job, user("recruiter"))
    interviews.set_slot(apps[1], SLOT.replace(hour=14), "Teams")
    assert interviews.send_invitations(job, user("recruiter")) == (2, 2)
    note = Notification.query.filter_by(user_id=user("linemanager").id).filter(
        Notification.title.startswith("Interview panel:")).one()                 # the full invitation
    assert "Head office boardroom" in note.body and "Teams" in note.body
    invite = CandidateMessage.query.filter_by(application_id=apps[0].id, kind="invitation").one()
    assert "10 November 2026" in invite.body and "10:00" in invite.body
    assert apps[0].slot.ics.startswith("BEGIN:VCALENDAR")


def test_panellists_score_independently_and_results_are_ranked(app):
    job, panel, (first, second) = interview_ready()
    with pytest.raises(DomainError, match="Only the interview panel"):
        interviews.submit_scorecard(first, user("hod"), scores(panel, 3), "", "Appoint")   # not invited yet
    interviews.send_invitations(job, user("recruiter"))
    with pytest.raises(DomainError, match="Only the interview panel"):
        interviews.submit_scorecard(first, user("finance"), scores(panel, 3), "", "Appoint")
    with pytest.raises(DomainError, match="Score every criterion"):
        interviews.submit_scorecard(first, user("hod"), {}, "", "Appoint")
    interviews.submit_scorecard(first, user("hod"), scores(panel, 5), "Excellent", "Appoint")
    assert interviews.can_see_scores(user("hod"), first)
    assert not interviews.can_see_scores(user("linemanager"), first)          # hasn't scored yet: hidden
    with pytest.raises(DomainError, match="already scored"):
        interviews.submit_scorecard(first, user("hod"), scores(panel, 1), "", "Appoint")
    interviews.submit_scorecard(first, user("linemanager"), scores(panel, 4), "", "Possible")
    interviews.submit_scorecard(second, user("hod"), scores(panel, 2), "", "Don't appoint")
    ranking = interviews.ranking(job)
    assert [r["application"] for r in ranking] == [first, second]
    assert ranking[0]["average"] == 90.0 and ranking[0]["tally"]["Appoint"] == 1 and ranking[1]["scored"] == 1
    done = Notification.query.filter_by(user_id=user("recruiter").id).filter(Notification.title.contains("Panel scores")).all()
    assert len(done) == 1 and "90.0%" in done[0].body                       # only the fully scored candidate


def test_panel_pages_and_access(app, client):
    job, panel, (first, second) = interview_ready()
    interviews.send_invitations(job, user("recruiter"))
    db.session.commit()
    login(client, "linemanager")                                            # an invited manager
    assert first.candidate.full_name.encode() in client.get("/recruitment/interviews").data
    page = client.get(f"/recruitment/interviews/{first.id}").get_data(as_text=True)
    assert "Your scorecard" in page and "Hidden until you submit" in page
    form = {f"score_{i}": "4" for i in range(len(panel.criteria))}
    r = client.post(f"/recruitment/interviews/{first.id}", data=dict(form, recommendation="Appoint", comment="Good"))
    assert r.status_code == 302 and interviews.my_scorecard(user("linemanager"), first).total == 80.0
    assert client.get(f"/recruitment/interviews/{first.id}/invite.ics").status_code == 200


def test_people_off_the_panel_are_kept_out(app, client):
    job, panel, (first, _second) = interview_ready()
    interviews.send_invitations(job, user("recruiter"))
    db.session.commit()
    login(client, "otherhod")                                               # a manager not on this panel
    assert client.get(f"/recruitment/interviews/{first.id}").status_code == 403
    assert client.get(f"/recruitment/interviews/{first.id}/cv").status_code == 403


def test_hr_panel_page(app, client):
    job, panel, _apps = interview_ready()
    db.session.commit()
    login(client, "recruiter")
    page = client.get(f"/recruitment/jobs/{job.id}/panel").get_data(as_text=True)
    assert "Interview panel" in page and "Send invitations" in page and "Invite a manager" in page
