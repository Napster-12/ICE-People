"""Interview panels and scorecards (1 Nov 2026, at the user's request; Phase 6, spec §4.5 IN-004 to IN-007).

One panel per advert: the Department Manager who picked the candidates, plus managers HR invites (managers only).
The panel scores the interview, not the CV, so a scorecard opens only once the candidate's interview has started.
The Department Manager types the interview questions when returning the shortlist and the Talent Acquisition
Specialist can edit them (8 Nov 2026). HR gives each candidate an interview slot and sends the invitations (panel and
candidates, with calendar invites; the panel's lists each candidate's scorecard link). Every panellist scores every
question 1–5 with a comment, on their own; they see the others' scores only once they've submitted theirs. Each
scorecard's average is a percentage, and the candidates are ranked by the panel's average.
"""
from datetime import timedelta
from urllib.parse import quote, urlencode

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Application, InterviewPanel, InterviewSlot, PanelMember, Role, Scorecard, User
from app.models.recruitment import INTERVIEW_PLATFORMS, RECOMMENDATIONS
from app.models.user import EXCO, GCOO, GROUP_HR, HOD, HR_ADMIN, HR_MANAGER, LINE_MANAGER, RECRUITER
from app.services import audit, shortlisting
from app.services.dates import format_datetime, now
from app.services.errors import DomainError
from app.services.notifications import notify, users_with_role

# Who HR can invite: managers, and (8 Nov 2026, at the user's request) the Talent Acquisition Specialist, who also scores.
PANEL_ROLES = (LINE_MANAGER, HOD, HR_MANAGER, GROUP_HR, GCOO, EXCO, RECRUITER)
FIXED_ROLES = ("Department Manager", "Talent Acquisition Specialist")     # on every panel; can't be removed
MAX_QUESTIONS = 15
MAX_QUESTION_LENGTH = 300
# Each question is scored out of 5 (8 Nov 2026, at the user's request; replaces the criteria and rating scales).
SCORES = [(1, "Poor"), (2, "Below expectations"), (3, "Meets expectations"), (4, "Exceeds"), (5, "Outstanding")]
TOP_SCORE = 5

# The questions (8 Nov 2026, at the user's request): the Department Manager types them when returning the shortlist
# (shortlisting.complete_review); the Talent Acquisition Specialist can edit them until scoring starts.


def parse_questions(rows):
    """rows: question texts. Returns (questions, errors): 1–15 different questions, blanks dropped."""
    questions, errors = [], []
    for text in rows:
        text = " ".join((text or "").split())
        if not text:
            continue
        if len(text) > MAX_QUESTION_LENGTH:
            errors.append(f"Keep each question under {MAX_QUESTION_LENGTH} characters (\"{text[:40]}…\").")
        questions.append(text)
    if not 1 <= len(questions) <= MAX_QUESTIONS:
        errors.append(f"Type between 1 and {MAX_QUESTIONS} interview questions.")
    elif len({q.lower() for q in questions}) != len(questions):
        errors.append("Each question must be different.")
    return questions, errors


def talent_specialist_for(job):
    """The Talent Acquisition Specialist who scores on this advert's panel (8 Nov 2026): the one who sent the shortlist
    or drafted the advert, else the first active one."""
    from app.models import ShortlistReview
    review = (ShortlistReview.query.filter_by(job_id=job.id).order_by(ShortlistReview.id.desc()).first())
    for candidate in (review.sent_by if review else None, job.created_by):
        if candidate is not None and candidate.active and candidate.has_role(RECRUITER):
            return candidate
    return (User.query.filter(User.active.is_(True), User.roles.any(Role.name == RECRUITER))
            .order_by(User.id).first())


def ensure_talent_specialist(panel):
    """Put the Talent Acquisition Specialist on the panel if nobody in that role is on it yet."""
    if any(m.user.has_role(RECRUITER) for m in panel.members):
        return None
    specialist = talent_specialist_for(panel.job)
    if specialist is None:
        return None
    member = PanelMember(user_id=specialist.id, role="Talent Acquisition Specialist")
    panel.members.append(member)
    db.session.flush()
    return member


def panel_for(job, create=False):
    """The advert's panel, created with the Department Manager and the Talent Acquisition Specialist on it and no
    questions yet."""
    panel = InterviewPanel.query.filter_by(job_id=job.id).first()
    if panel is None and create:
        panel = InterviewPanel(job_id=job.id, questions=[])
        db.session.add(panel)
        db.session.flush()
        manager = shortlisting.department_manager_for(job)
        if manager is not None:
            panel.members.append(PanelMember(user_id=manager.id, role="Department Manager"))
            db.session.flush()
        ensure_talent_specialist(panel)
    return panel


def eligible_members(panel):
    """Managers HR may invite, not already on the panel."""
    taken = {m.user_id for m in panel.members}
    users = (User.query.filter(User.active.is_(True), User.roles.any(Role.name.in_(PANEL_ROLES)))
             .order_by(User.full_name).all())
    return [u for u in users if u.id not in taken]


def add_member(panel, user, by):
    if user is None or not user.active or not user.has_role(*PANEL_ROLES):
        raise DomainError("Only managers and Talent Acquisition Specialists can be invited to an interview panel.")
    if any(m.user_id == user.id for m in panel.members):
        raise DomainError(f"{user.full_name} is already on the panel.")
    member = PanelMember(user_id=user.id, role="Panel member")
    panel.members.append(member)
    db.session.flush()
    audit.record("panel.member_added", "job", panel.job_id, after={"user": user.username, "by": by.username})
    if panel.invited_at:                               # invitations already went out: invite this person now
        _invite_member(panel, member)
    else:                                              # tell them now; the dates and calendar invites follow
        notify(user, "panel_added", link="/recruitment/interviews", title=panel.job.title,
               ref=panel.job.reference or f"Job {panel.job_id}", sender=by.full_name)
    return member


def remove_member(panel, member, by):
    if member.role in FIXED_ROLES:
        raise DomainError(f"The {member.role} stays on the panel.")
    if Scorecard.query.join(Application).filter(Application.job_id == panel.job_id,
                                                 Scorecard.panellist_id == member.user_id).first():
        raise DomainError(f"{member.user.full_name} has already scored a candidate and stays on the panel.")
    audit.record("panel.member_removed", "job", panel.job_id, after={"user": member.user.username, "by": by.username})
    panel.members.remove(member)                           # delete-orphan removes the row


def scoring_started(panel):
    return Scorecard.query.join(Application).filter(Application.job_id == panel.job_id).first() is not None


def save_questions(panel, rows, by):
    """The Department Manager (with the shortlist) or the Talent Acquisition Specialist sets the questions. They
    lock once anyone has scored, so the whole panel scores the same questions."""
    if scoring_started(panel):
        raise DomainError("Scoring has started, so the interview questions can't change any more.")
    questions, errors = parse_questions(rows)
    if errors:
        raise DomainError(" ".join(errors))
    if questions != list(panel.questions or []):
        audit.record("panel.questions", "job", panel.job_id, before={"questions": panel.questions},
                     after={"questions": questions, "by": by.username})
        panel.questions = questions
    return questions


def candidates(job):
    """Applications going to interview (Interview status), best ATS score first."""
    return (Application.query.filter_by(job_id=job.id, status="Interview")
            .order_by(Application.score.desc()).all())


def set_slot(application, starts_at, venue, duration_minutes=60, platform="In person", meeting_id="", passcode=""):
    """venue is the address in person, or the joining link online (with the meeting ID and passcode, if any)."""
    if application.status != "Interview":
        raise DomainError("Only applicants picked for interview get an interview slot.")
    name = application.candidate.full_name
    venue, platform = (venue or "").strip(), platform or "In person"
    if platform not in INTERVIEW_PLATFORMS:
        raise DomainError(f"{name}: choose how the interview takes place.")
    online = platform != "In person"
    if starts_at is None or not venue:
        raise DomainError(f"{name}: enter the date, time and {'joining link' if online else 'venue'}.")
    if online and not venue.lower().startswith(("https://", "http://")):
        raise DomainError(f"{name}: the {platform} joining link must start with https://.")
    if application.slot is None:
        application.slot = InterviewSlot()
    slot = application.slot
    slot.starts_at, slot.venue, slot.duration_minutes, slot.platform = starts_at, venue, duration_minutes, platform
    slot.meeting_id = (meeting_id or "").strip() or None if online else None
    slot.passcode = (passcode or "").strip() or None if online else None
    return slot


def _attendees(panel):
    return [m.user.email for m in panel.members if m.user.email]


def teams_link(application):
    """A Microsoft Teams link that opens a new meeting for this interview, filled in (title, time, venue), for the
    user's own calendar only: no attendees, so saving it sends no invitations. Times are SAST."""
    slot, job = application.slot, application.job
    end = slot.starts_at + timedelta(minutes=slot.duration_minutes)
    params = {"subject": f"Interview: {job.title} - {application.candidate.full_name}",
              "startTime": slot.starts_at.strftime("%Y-%m-%dT%H:%M:%S+02:00"),
              "endTime": end.strftime("%Y-%m-%dT%H:%M:%S+02:00"),
              "content": f"Venue: {slot.venue}"}
    return "https://teams.microsoft.com/l/meeting/new?" + urlencode(params, quote_via=quote)


def scorecard_url(application):
    """The full link to a candidate's scorecard, for the panel invitation (it opens when the interview starts)."""
    from app.services.emails import _absolute
    return _absolute(f"/recruitment/interviews/{application.id}")


def _slots_text(panel):
    """One line per candidate: when, who, where and the link to their scorecard (8 Nov 2026)."""
    lines = []
    for app in candidates(panel.job):
        if app.slot:
            where = app.slot.venue if app.slot.platform == "In person" else app.slot.platform
            lines.append(f"- {format_datetime(app.slot.starts_at)}: {app.candidate.full_name} ({where}). "
                         f"Scorecard: {scorecard_url(app)}")
    return "\n".join(lines) or "- (slots to follow)"


def _invite_member(panel, member):
    member.invited_at = now()
    notify(member.user, "panel_invite", link="/recruitment/interviews", title=panel.job.title,
           ref=panel.job.reference or f"Job {panel.job_id}", sender=(panel.invited_by.full_name if panel.invited_by
                                                                     else "HR"),
           role=member.role, slots=_slots_text(panel))


def send_invitations(job, by):
    """HR sends the invitations: every panellist (notification, email and a calendar invite per interview) and every
    candidate who hasn't been invited yet (the "Applicant: interview invitation" email, filled in from their slot)."""
    panel = panel_for(job)
    if panel is None or not panel.members:
        raise DomainError("Add the panel first.")
    ensure_talent_specialist(panel)                     # panels made before 8 Nov 2026 get theirs now
    if not panel.questions:
        raise DomainError("Add the interview questions first.")
    apps = candidates(job)
    if not apps:
        raise DomainError("Nobody has been picked for interview yet.")
    missing = [a.candidate.full_name for a in apps if a.slot is None]
    if missing:
        raise DomainError(f"Give every candidate an interview slot first (missing: {', '.join(missing)}).")
    panel.invited_at, panel.invited_by_id = now(), by.id
    calendar = get_adapter("email")
    for app in apps:
        try:
            event = calendar.create_event(f"Interview: {job.title} - {app.candidate.full_name}", app.slot.starts_at,
                                          app.slot.duration_minutes, _attendees(panel) + [app.candidate.email],
                                          app.slot.venue)
            app.slot.ics = event.get("ics")
        except IntegrationError:
            app.slot.ics = None                         # the email still goes out without the calendar file
    for member in panel.members:
        _invite_member(panel, member)
    to_invite = [a for a in apps if not any(m.kind == "invitation" for m in a.messages)]
    for app in to_invite:
        shortlisting.send_messages(job, by, "invitation", [app.id],
                                   {"date": app.slot.starts_at.strftime("%Y-%m-%d"),
                                    "time": app.slot.starts_at.strftime("%H:%M"), "venue": app.slot.venue,
                                    "platform": app.slot.platform, "meeting_id": app.slot.meeting_id,
                                    "passcode": app.slot.passcode, "duration": app.slot.duration_minutes})
    audit.record("panel.invited", "job", job.id, after={"panel": [m.user.username for m in panel.members],
                                                         "candidates": len(apps)})
    return len(panel.members), len(to_invite)


# ------------------------------------------------------------------ scoring

def membership(user, job):
    panel = panel_for(job)
    if panel is None or user is None:
        return None
    return next((m for m in panel.members if m.user_id == user.id), None)


def on_panel_for(user, application):
    """The user sits on this candidate's panel, HR has sent the invitations and the candidate is going to interview."""
    panel = panel_for(application.job)
    return (panel is not None and panel.invited_at is not None and application.status == "Interview"
            and membership(user, application.job) is not None)


def interview_started(application):
    """The panel scores the interview, so scoring opens when it starts (and stays open to finish afterwards)."""
    return application.slot is not None and now() >= application.slot.starts_at


def can_score(user, application):
    return on_panel_for(user, application) and interview_started(application)


def my_scorecard(user, application):
    return Scorecard.query.filter_by(application_id=application.id, panellist_id=user.id).first()


def average_total(answers):
    """0–100: the average score out of 5, as a percentage."""
    return round(sum(a["score"] for a in answers) * 100 / (TOP_SCORE * len(answers)), 1) if answers else 0.0


def submit_scorecard(application, user, scores, comments, recommendation, comment=""):
    """scores and comments: lists in question order (a 1–5 score each, an optional comment each)."""
    if not on_panel_for(user, application):
        raise DomainError("Only the interview panel can score this candidate.")
    if not interview_started(application):
        raise DomainError(f"Scoring opens when the interview starts, at {format_datetime(application.slot.starts_at)}. "
                          "The panel scores the interview, not the CV.")
    if my_scorecard(user, application):
        raise DomainError("You've already scored this candidate.")
    panel = panel_for(application.job)
    if not panel.questions:
        raise DomainError("There are no interview questions to score yet.")
    answers, missing = [], []
    for i, question in enumerate(panel.questions):
        try:
            value = int(scores[i])
        except (IndexError, TypeError, ValueError):
            value = None
        if value not in range(1, TOP_SCORE + 1):
            missing.append(str(i + 1))
            continue
        note = (comments[i] if i < len(comments) else "") or ""
        answers.append({"question": question, "score": value, "comment": note.strip()[:2000] or None})
    if missing:
        raise DomainError(f"Score every question from 1 to 5 (missing: question {', '.join(missing)}).")
    if recommendation not in RECOMMENDATIONS:
        raise DomainError("Choose your recommendation.")
    card = Scorecard(panellist_id=user.id, answers=answers, total=average_total(answers),
                     comment=(comment or "").strip() or None, recommendation=recommendation, submitted_at=now())
    application.scorecards.append(card)
    db.session.flush()
    audit.record("interview.scored", "application", application.id,
                 after={"panellist": user.username, "total": card.total, "recommendation": recommendation})
    if len(application.scorecards) == len(panel.members):           # the whole panel has scored this candidate
        hr = [u for u in [panel.invited_by] + users_with_role(HR_ADMIN) if u is not None]
        notify(hr, "panel_scored", link=f"/recruitment/jobs/{application.job_id}/panel", title=application.job.title,
               name=application.candidate.full_name, average=result(application, panel)["average"])
    return card


def can_see_scores(user, application):
    """A panellist (the Talent Acquisition Specialist included) once they've submitted their own scorecard for this
    candidate, so every panellist scores independently; other HR people always."""
    if my_scorecard(user, application) is not None:
        return True
    return user.can_recruit and membership(user, application.job) is None


def result(application, panel):
    cards = application.scorecards
    tally = {r: sum(1 for c in cards if c.recommendation == r) for r in RECOMMENDATIONS}
    return {"application": application, "cards": cards, "scored": len(cards), "panel": len(panel.members),
            "average": round(sum(c.total for c in cards) / len(cards), 1) if cards else None, "tally": tally}


INTERVIEWED = ("Interview", "Offer", "Hired")


def ranking(job):
    """Candidates going to interview (and those since marked successful or hired) with their combined score, best
    first (unscored last)."""
    panel = panel_for(job)
    if panel is None:
        return []
    apps = (Application.query.filter(Application.job_id == job.id, Application.status.in_(INTERVIEWED))
            .order_by(Application.score.desc()).all())
    rows = [result(a, panel) for a in apps]
    return sorted(rows, key=lambda r: (r["average"] is None, -(r["average"] or 0)))


def mark_successful(application, user, comment=""):
    """The interview decision (8 Nov 2026, at the user's request): HR marks a candidate the whole panel has scored
    as successful. The application moves to Offer, the requisition to Offer, and HR Admin is told to make the offer."""
    from app.services import requisitions
    panel = panel_for(application.job)
    if application.status != "Interview" or panel is None:
        raise DomainError("Only a candidate who went to interview can be marked successful.")
    row = result(application, panel)
    if row["scored"] < row["panel"] or not row["cards"]:
        raise DomainError(f"Wait until the whole panel has scored {application.candidate.full_name} "
                          f"({row['scored']} of {row['panel']} so far).")
    application.status, application.successful_at, application.successful_by_id = "Offer", now(), user.id
    application.decision_comment = (comment or "").strip() or None
    audit.record("status_change", "application", application.id, before={"status": "Interview"},
                 after={"status": "Offer"}, detail=f"Passed the interview ({row['average']}%)"
                 + (f": {application.decision_comment}" if application.decision_comment else ""), user=user)
    req = application.job.requisition
    if req is not None:
        for step in ("Interviewing", "Offer"):                    # Advertised → Interviewing → Offer
            if req.status != step and step in requisitions.FLOW.transitions.get(req.status, ()):
                requisitions.set_status(req, step, comment=f"{application.candidate.full_name} passed the interview",
                                        notify_originator=False)
    notify(users_with_role(HR_ADMIN), "interview_passed", link=f"/onboarding/offers/new/{application.id}",
           name=application.candidate.full_name, title=application.job.title, ref=application.reference,
           average=row["average"], decided_by=user.full_name,
           comment=application.decision_comment)
    return application


def waiting_panels(user):
    """Panels the user is on whose invitations HR hasn't sent yet (no dates to score)."""
    return (InterviewPanel.query.join(PanelMember).filter(PanelMember.user_id == user.id,
                                                           InterviewPanel.invited_at.is_(None)).all())


def to_score(user):
    """Candidates on panels the user sits on (invitations sent), with whether they've scored them yet."""
    panels = (InterviewPanel.query.join(PanelMember).filter(PanelMember.user_id == user.id,
                                                             InterviewPanel.invited_at.isnot(None)).all())
    rows = []
    for panel in panels:
        for app in candidates(panel.job):
            rows.append({"application": app, "job": panel.job, "slot": app.slot, "open": interview_started(app),
                         "scored": my_scorecard(user, app) is not None})
    return sorted(rows, key=lambda r: (r["scored"], r["slot"].starts_at if r["slot"] else now()))
