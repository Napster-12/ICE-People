"""Shortlist review (1 Nov 2026, at the user's request; the start of Phase 6, spec §4.5):

1. HR shortlists applicants and sends the shortlist to the Department Manager of the advert's department.
2. The Department Manager picks who goes to interview: picked → Interview, the rest → Not selected. HR is notified.
   They also type the interview questions the panel scores (8 Nov 2026).
3. HR emails the applicants: an interview invitation (date, time, venue) or a regret (→ Rejected).
"""
from datetime import datetime

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Application, CandidateMessage, ShortlistReview, User
from app.models.recruitment import INTERVIEW_PLATFORMS, MESSAGE_KINDS
from app.models.user import HR_ADMIN
from app.services import audit
from app.services.dates import now
from app.services.emails import designed
from app.services.errors import DomainError
from app.services.notifications import notify, render, users_with_role
from app.services.workflow import hod_user

# Which applications each message goes to, and the status they move to once it is sent.
MESSAGE_FOR = {"invitation": ("Interview", "Interview"), "regret": ("Not selected", "Rejected")}


def department_manager_for(job):
    """The Department Manager of the advert's department (through its requisition)."""
    req = job.requisition
    return hod_user(req.department) if req is not None else None


def pending_review(job):
    return ShortlistReview.query.filter_by(job_id=job.id, status="Pending").first()


def latest_review(job):
    return ShortlistReview.query.filter_by(job_id=job.id).order_by(ShortlistReview.id.desc()).first()


def shortlisted(job):
    return (Application.query.filter_by(job_id=job.id, status="Shortlisted")
            .order_by(Application.score.desc()).all())


def send_to_department_manager(job, user):
    """Step 1: HR sends the advert's shortlisted applicants to the Department Manager."""
    if pending_review(job) is not None:
        raise DomainError("The Department Manager is still reviewing this advert's shortlist.")
    apps = shortlisted(job)
    if not apps:
        raise DomainError("Shortlist at least one applicant first.")
    manager = department_manager_for(job)
    if manager is None:
        raise DomainError("This advert's department has no Department Manager with an account. "
                          "Set one on the Departments page first.")
    review = ShortlistReview(job_id=job.id, reviewer_id=manager.id, sent_by_id=user.id,
                             application_ids=[a.id for a in apps], status="Pending")
    db.session.add(review)
    db.session.flush()
    audit.record("shortlist.sent", "job", job.id, after={"review": review.id, "reviewer": manager.username,
                                                          "applications": len(apps)})
    notify(manager, "shortlist_review", link=f"/recruitment/shortlists/{review.id}", title=job.title,
           ref=job.reference or f"Job {job.id}", count=len(apps), sender=user.full_name)
    return review


def can_review(user, review):
    return review.status == "Pending" and user is not None and user.id == review.reviewer_id


def complete_review(review, user, selected_ids, comment="", questions=None):
    """Step 2: the Department Manager picks who goes to interview and types the interview questions (8 Nov 2026).
    HR is notified."""
    from app.services import interviews
    if not can_review(user, review):
        raise DomainError("Only the Department Manager it was sent to can review this shortlist.")
    selected = {int(i) for i in selected_ids} & set(review.application_ids)
    if not selected:
        raise DomainError("Pick at least one applicant for interview.")
    panel = interviews.panel_for(review.job, create=True)
    interviews.save_questions(panel, questions or [], user)
    for app in review.applications:
        if app.status != "Shortlisted":
            continue                                      # HR moved it meanwhile; leave it alone
        new = "Interview" if app.id in selected else "Not selected"
        audit.record("status_change", "application", app.id, before={"status": app.status}, after={"status": new},
                     detail=f"Shortlist review by {user.full_name}")
        app.status = new
    review.selected_ids = sorted(selected)
    review.comment = (comment or "").strip() or None
    review.status, review.completed_at = "Completed", now()
    audit.record("shortlist.reviewed", "job", review.job_id,
                 after={"review": review.id, "selected": len(selected),
                        "not_selected": len(review.application_ids) - len(selected)})
    hr = [review.sent_by] + users_with_role(HR_ADMIN)
    notify(hr, "shortlist_reviewed", link=f"/recruitment/jobs/{review.job_id}", title=review.job.title,
           ref=review.job.reference or f"Job {review.job_id}", reviewer=user.full_name, selected=len(selected),
           not_selected=len(review.application_ids) - len(selected), comment=review.comment or "",
           questions=len(panel.questions))
    return review


def recipients(job, kind):
    """Applications a message kind goes to: invitations to Interview, regrets to Not selected."""
    status = MESSAGE_FOR[kind][0]
    return (Application.query.filter_by(job_id=job.id, status=status)
            .order_by(Application.score.desc()).all())


def _duration(minutes):
    if not minutes:
        return ""
    hours, mins = divmod(int(minutes), 60)
    parts = ([f"{hours} hour{'s' if hours != 1 else ''}"] if hours else []) + ([f"{mins} minutes"] if mins else [])
    return " ".join(parts)


def interview_details(details):
    """Check an invitation's details and turn them into the email's values (8 Nov 2026): the date as "Tuesday,
    17 November 2026", the platform, and the venue (in person) or the joining link, meeting ID and passcode (online)."""
    platform = details.get("platform") or "In person"
    if platform not in INTERVIEW_PLATFORMS:
        raise DomainError("Choose how the interview takes place.")
    online = platform != "In person"
    venue = details.get("venue", "")
    missing = [label for key, label in (("date", "date"), ("time", "time")) if not details.get(key)]
    if not venue:
        missing.append(f"{platform} joining link" if online else "venue")
    if missing:
        raise DomainError(f"Enter the interview {', '.join(missing)}.")
    if online and not venue.lower().startswith(("https://", "http://")):
        raise DomainError(f"The {platform} joining link must start with https://.")
    try:
        when = datetime.strptime(f"{details['date']} {details['time']}", "%Y-%m-%d %H:%M")
        date, time = f"{when:%A}, {when.day} {when:%B %Y}", f"{when:%H:%M}"
    except ValueError:
        date, time = details["date"], details["time"]          # already written out
    return {"date": date, "time": time, "duration": _duration(details.get("duration")), "platform": platform,
            "online": online, "venue": "" if online else venue, "meeting_link": venue if online else "",
            "meeting_id": details.get("meeting_id", "") if online else "",
            "passcode": details.get("passcode", "") if online else ""}


def send_messages(job, user, kind, application_ids, details=None):
    """Step 3: HR emails the chosen applicants. An invitation needs the date, time and venue; a regret moves the
    application to Rejected. Returns the number of messages sent."""
    if kind not in MESSAGE_FOR:
        raise DomainError("Choose an interview invitation or a regret.")
    details = {k: (v or "").strip() if isinstance(v, str) or v is None else v for k, v in (details or {}).items()}
    invite = interview_details(details) if kind == "invitation" else {}
    eligible = {a.id: a for a in recipients(job, kind)}
    chosen = [eligible[i] for i in {int(i) for i in application_ids} if i in eligible]
    if not chosen:
        raise DomainError("Pick at least one applicant to send to.")
    key = "candidate_interview_invite" if kind == "invitation" else "candidate_regret"
    sent = 0
    for app in chosen:
        cand = app.candidate
        subject, body = render(key, {"name": cand.full_name, "title": job.title, "ref": app.reference,
                                     "note": details.get("note", ""), **invite})
        join = invite.get("meeting_link") or None          # online interviews get a "Join the meeting" button
        try:
            get_adapter("email").send_email(cand.email, subject, body,
                                            html=designed(key, subject, body, join, context={"title": job.title}))
        except IntegrationError as exc:
            raise DomainError(f"The email to {cand.email} couldn't be sent: {exc}") from exc
        db.session.add(CandidateMessage(application_id=app.id, kind=kind, subject=subject, body=body,
                                        sent_by_id=user.id, sent_at=now()))
        new_status = MESSAGE_FOR[kind][1]
        if app.status != new_status:
            audit.record("status_change", "application", app.id, before={"status": app.status},
                         after={"status": new_status}, detail=f"{MESSAGE_KINDS[kind]} sent")
            app.status = new_status
        audit.record("candidate.message", "application", app.id, after={"kind": kind, "to": cand.email})
        sent += 1
    return sent


def reviews_for(user, pending_only=False):
    q = ShortlistReview.query.filter_by(reviewer_id=user.id)
    if pending_only:
        q = q.filter_by(status="Pending")
    return q.order_by(ShortlistReview.status.desc(), ShortlistReview.created_at.desc()).all()


def reviewer_can_see(user, review, application):
    """The reviewing Department Manager may open the CVs of the applications they were sent."""
    return isinstance(user, User) and review.reviewer_id == user.id and application.id in (review.application_ids or [])
