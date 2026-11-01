"""Interview panels and scorecards (1 Nov 2026, at the user's request; Phase 6, spec §4.5 IN-004 to IN-007).

One panel per advert: the Department Manager who picked the candidates, plus managers HR invites (managers only).
HR gives each candidate an interview slot, sets the scoring criteria and sends the invitations (panel and candidates,
with calendar invites). Every panellist scores every candidate on their own; they see the others' scores only once
they've submitted theirs. Scores are combined into a weighted percentage and the candidates are ranked.
"""
from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Application, InterviewPanel, InterviewSlot, PanelMember, Role, Scorecard, User
from app.models.recruitment import RECOMMENDATIONS
from app.models.user import EXCO, GCOO, GROUP_HR, HOD, HR_ADMIN, HR_MANAGER, LINE_MANAGER
from app.services import audit, shortlisting
from app.services.dates import format_datetime, now
from app.services.errors import DomainError
from app.services.notifications import notify, users_with_role

# Who HR can invite (the user's choice: managers only).
PANEL_ROLES = (LINE_MANAGER, HOD, HR_MANAGER, GROUP_HR, GCOO, EXCO)
SCORES = range(1, 6)


def default_criteria(job):
    skills = ", ".join(s.strip() for s in (job.required_skills or "").split(",")[:3] if s.strip())
    return [{"name": f"Technical skills ({skills})" if skills else "Technical skills", "weight": 30},
            {"name": "Relevant experience", "weight": 20},
            {"name": "Communication", "weight": 20},
            {"name": "Problem-solving", "weight": 15},
            {"name": "Culture fit and values", "weight": 15}]


def panel_for(job, create=False):
    """The advert's panel. Created with the Department Manager on it and the standard criteria."""
    panel = InterviewPanel.query.filter_by(job_id=job.id).first()
    if panel is None and create:
        panel = InterviewPanel(job_id=job.id, criteria=default_criteria(job))
        db.session.add(panel)
        db.session.flush()
        manager = shortlisting.department_manager_for(job)
        if manager is not None:
            panel.members.append(PanelMember(user_id=manager.id, role="Department Manager"))
            db.session.flush()
    return panel


def eligible_members(panel):
    """Managers HR may invite, not already on the panel."""
    taken = {m.user_id for m in panel.members}
    users = (User.query.filter(User.active.is_(True), User.roles.any(Role.name.in_(PANEL_ROLES)))
             .order_by(User.full_name).all())
    return [u for u in users if u.id not in taken]


def add_member(panel, user, by):
    if user is None or not user.active or not user.has_role(*PANEL_ROLES):
        raise DomainError("Only managers can be invited to an interview panel.")
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
    if member.role == "Department Manager":
        raise DomainError("The Department Manager stays on the panel.")
    if Scorecard.query.join(Application).filter(Application.job_id == panel.job_id,
                                                 Scorecard.panellist_id == member.user_id).first():
        raise DomainError(f"{member.user.full_name} has already scored a candidate and stays on the panel.")
    audit.record("panel.member_removed", "job", panel.job_id, after={"user": member.user.username, "by": by.username})
    panel.members.remove(member)                           # delete-orphan removes the row


def save_criteria(panel, rows):
    """rows: [(name, weight text)]. 1–8 criteria, weights are whole numbers that total 100."""
    if Scorecard.query.join(Application).filter(Application.job_id == panel.job_id).first():
        raise DomainError("Scoring has started, so the criteria can't change any more.")
    criteria, errors = [], []
    for name, weight in rows:
        name = (name or "").strip()
        if not name:
            continue
        try:
            w = int(str(weight).strip())
        except ValueError:
            errors.append(f"{name}: enter the weight as a whole number.")
            continue
        if w <= 0:
            errors.append(f"{name}: the weight must be more than 0.")
        criteria.append({"name": name, "weight": w})
    if not 1 <= len(criteria) <= 8:
        errors.append("Enter between 1 and 8 criteria.")
    elif len({c["name"].lower() for c in criteria}) != len(criteria):
        errors.append("Each criterion needs a different name.")
    elif not errors and sum(c["weight"] for c in criteria) != 100:
        errors.append(f"The weights must add up to 100 (they add up to {sum(c['weight'] for c in criteria)}).")
    if errors:
        raise DomainError(" ".join(errors))
    panel.criteria = criteria
    audit.record("panel.criteria", "job", panel.job_id, after={"criteria": criteria})


def candidates(job):
    """Applications going to interview (Interview status), best ATS score first."""
    return (Application.query.filter_by(job_id=job.id, status="Interview")
            .order_by(Application.score.desc()).all())


def set_slot(application, starts_at, venue, duration_minutes=60):
    if application.status != "Interview":
        raise DomainError("Only applicants picked for interview get an interview slot.")
    venue = (venue or "").strip()
    if starts_at is None or not venue:
        raise DomainError(f"{application.candidate.full_name}: enter the date, time and venue.")
    if application.slot is None:
        application.slot = InterviewSlot()
    slot = application.slot
    slot.starts_at, slot.venue, slot.duration_minutes = starts_at, venue, duration_minutes
    return slot


def _attendees(panel):
    return [m.user.email for m in panel.members if m.user.email]


def _slots_text(panel):
    lines = []
    for app in candidates(panel.job):
        if app.slot:
            lines.append(f"- {format_datetime(app.slot.starts_at)}: {app.candidate.full_name} ({app.slot.venue})")
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
                                   {"date": app.slot.starts_at.strftime("%d %B %Y"),
                                    "time": app.slot.starts_at.strftime("%H:%M"), "venue": app.slot.venue})
    audit.record("panel.invited", "job", job.id, after={"panel": [m.user.username for m in panel.members],
                                                         "candidates": len(apps)})
    return len(panel.members), len(to_invite)


# ------------------------------------------------------------------ scoring

def membership(user, job):
    panel = panel_for(job)
    if panel is None or user is None:
        return None
    return next((m for m in panel.members if m.user_id == user.id), None)


def can_score(user, application):
    """Panel members score candidates going to interview, once HR has sent the invitations."""
    panel = panel_for(application.job)
    return (panel is not None and panel.invited_at is not None and application.status == "Interview"
            and membership(user, application.job) is not None)


def my_scorecard(user, application):
    return Scorecard.query.filter_by(application_id=application.id, panellist_id=user.id).first()


def weighted_total(criteria, scores):
    return round(sum(c["weight"] * scores[c["name"]] / 5 for c in criteria), 1)


def submit_scorecard(application, user, scores, comment, recommendation):
    if not can_score(user, application):
        raise DomainError("Only the interview panel can score this candidate.")
    if my_scorecard(user, application):
        raise DomainError("You've already scored this candidate.")
    panel = panel_for(application.job)
    clean = {}
    for c in panel.criteria:
        try:
            value = int(scores.get(c["name"]))
        except (TypeError, ValueError):
            value = 0
        if value not in SCORES:
            raise DomainError(f"Score every criterion from 1 to 5 (missing: {c['name']}).")
        clean[c["name"]] = value
    if recommendation not in RECOMMENDATIONS:
        raise DomainError("Choose your recommendation.")
    card = Scorecard(panellist_id=user.id, scores=clean, total=weighted_total(panel.criteria, clean),
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
    """HR always; a panellist once they've submitted their own scorecard for this candidate."""
    return user.is_hr or my_scorecard(user, application) is not None


def result(application, panel):
    cards = application.scorecards
    tally = {r: sum(1 for c in cards if c.recommendation == r) for r in RECOMMENDATIONS}
    return {"application": application, "cards": cards, "scored": len(cards), "panel": len(panel.members),
            "average": round(sum(c.total for c in cards) / len(cards), 1) if cards else None, "tally": tally}


def ranking(job):
    """Candidates going to interview with their combined score, best first (unscored last)."""
    panel = panel_for(job)
    if panel is None:
        return []
    rows = [result(a, panel) for a in candidates(job)]
    return sorted(rows, key=lambda r: (r["average"] is None, -(r["average"] or 0)))


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
            rows.append({"application": app, "job": panel.job, "slot": app.slot,
                         "scored": my_scorecard(user, app) is not None})
    return sorted(rows, key=lambda r: (r["scored"], r["slot"].starts_at if r["slot"] else now()))
