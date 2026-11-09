"""Role-aware portal homes, laid out like the IcePeople infographic home screens (pp. 8, 10, 11): HR admin, manager
and staff each get a greeting, figures and one tile per module. (Full dashboards and KPIs arrive in Phase 13.)"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, session, url_for
from flask_login import current_user
from sqlalchemy import func

from app.auth.decorators import roles_required
from app.auth.portals import PORTAL_LABELS, current_portal
from app.models import (Application, ApprovedPosition, BudgetLine, Employee, InterviewSlot, Job, Requisition,
                        ShortlistReview, WorkflowStep)
from app.models.user import FINANCE, GCOO, HR_ADMIN, HR_MANAGER, HR_ROLES, IT
from app.services import budget, interviews, positions, requisitions, settings, shortlisting, workflow
from app.services.dates import format_datetime, now, today

bp = Blueprint("dashboards", __name__)

BUDGET_ROLES = (FINANCE, HR_ADMIN, HR_MANAGER, GCOO)
COMING_SOON = "Coming soon"
IN_APPROVAL = ("Submitted", "In Approval")


def _greeting():
    hour = now().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


def _tile(icon, title, text, link=None, link_label=None, tone="", later=None):
    """One module tile, with an icon from _icons.html. `later` (a "Coming soon" line) marks a module that isn't
    built yet."""
    return {"icon": icon, "title": title, "text": text, "link": link, "link_label": link_label,
            "tone": "later" if later else tone, "later": later}


def _stat(value, label, link=None, alert=False):
    return {"value": value, "label": label, "link": link, "alert": alert and bool(value)}


def _due_label(due_at):
    """The pill on a manager's task: Overdue, Due today, N days, This week or a date."""
    if due_at is None:
        return "Open", ""
    days = (due_at.date() - today()).days
    if days < 0:
        return "Overdue", "urgent"
    if days == 0:
        return "Due today", "urgent"
    if days <= 2:
        return f"{days} day{'s' if days != 1 else ''}", ""
    if days <= 7:
        return "This week", ""
    return f"{due_at:%-d %b}", "soft"


def _budget_summary():
    fy = budget.financial_year_for(today())
    lines = BudgetLine.query.filter_by(financial_year=fy).all()
    amount = sum((Decimal(l.amount) for l in lines), Decimal(0))
    used = sum((Decimal(l.committed) + Decimal(l.consumed) for l in lines), Decimal(0))
    return {"fy": budget.fy_label(fy), "pct": (used * 100 / amount).quantize(Decimal("0.1")) if amount else 0,
            "hot": sum(1 for l in lines if l.utilisation >= 75)}


def _position_counts(user):
    if not user.has_role(*positions.VIEW_ROLES):
        return {}
    return dict(positions.visible_query(user).with_entities(ApprovedPosition.status, func.count())
                .group_by(ApprovedPosition.status).all())


def _admin_home(user, steps):
    from app.nav import sees_menu
    talent, money = sees_menu(user, "Talent"), sees_menu(user, "Budget")   # HR Admin sees neither (8 Nov 2026)
    reqs = requisitions.visible_query(user)
    awaiting = reqs.filter(Requisition.status.in_(IN_APPROVAL)).count()
    at_finance = (reqs.filter(Requisition.status.in_(IN_APPROVAL), Requisition.is_over_budget.is_(True)).count())
    pos = _position_counts(user)
    hr = user.has_role(*HR_ROLES)
    to_screen = Application.query.filter(Application.job_id.isnot(None), Application.status == "New").count() if hr else 0
    overdue = (workflow.pending_steps_query().filter(WorkflowStep.due_at < now()).count()
               if user.has_role(IT) else 0)
    stats = []
    if talent:
        stats += [
            _stat(awaiting, "Requisitions awaiting approval", url_for("requisitions.index")),
            _stat(pos.get("In recruitment", 0), "Vacancies in recruitment",
                  url_for("positions.dashboard") if pos else None),
            _stat(pos.get("Vacant", 0), "Vacant positions", url_for("positions.dashboard") if pos else None),
        ]
    stats.append(_stat(len(steps), "Waiting for you", url_for("approvals.inbox")))
    if user.has_role(IT):
        stats.append(_stat(overdue, "Items overdue", url_for("approvals.dashboard"), alert=True))
    elif talent or money:
        stats.append(_stat(at_finance, "Over budget in approval", url_for("requisitions.index"), alert=True))
    if hr and talent:
        stats.append(_stat(to_screen, "Applications to screen", url_for("recruitment.dashboard")))
    from app.services import onboarding
    if user.has_role(*onboarding.VIEW_ROLES) and not talent:          # HR Admin: onboarding figures instead
        from app.models import Offer, OnboardingCase
        stats += [
            _stat(len(onboarding.offers_to_make()), "Offers to make", url_for("onboarding.index")),
            _stat(Offer.query.filter_by(status="Sent").count(), "Offers waiting for an answer",
                  url_for("onboarding.index")),
            _stat(OnboardingCase.query.filter_by(status="Pre-boarding").count(), "New starters",
                  url_for("onboarding.index")),
        ]

    ta_text = f"{awaiting} requisition{'s' if awaiting != 1 else ''} awaiting approval"
    if pos:
        ta_text += f" · {pos.get('In recruitment', 0)} vacancies in recruitment"
    if hr:
        from app.services import adverts
        ta_text += f" · {adverts.ready_query().count()} ready to advertise · {to_screen} applications to screen"
    tiles = []
    if talent:
        tiles.append(_tile("briefcase", "Talent acquisition", ta_text,
                           url_for("recruitment.dashboard" if hr else "requisitions.index"),
                           "Open talent acquisition", tone="featured"))
    if pos and talent:
        adhoc = positions.visible_query(user).filter(ApprovedPosition.is_ad_hoc.is_(True),
                                                     ApprovedPosition.status == "Pending approval").count()
        tiles.append(_tile("briefcase", "Approved positions",
                           f"{pos.get('Filled', 0)} filled · {pos.get('Vacant', 0)} vacant · "
                           f"{pos.get('Frozen', 0)} frozen · {adhoc} ad-hoc requests pending",
                           url_for("positions.dashboard"), "Open vacancy dashboard"))
    if user.has_role(*BUDGET_ROLES) and money:
        b = _budget_summary()
        tiles.append(_tile("building", "Headcount budget",
                           f"{b['fy']} · {b['pct']}% committed or consumed · {b['hot']} cost centres above 75%",
                           url_for("budget.index"), "Open budget lines"))
    if user.has_role(*onboarding.VIEW_ROLES):
        from app.models import Offer, OnboardingCase
        to_make = len(onboarding.offers_to_make())
        out = Offer.query.filter_by(status="Sent").count()
        starters = OnboardingCase.query.filter_by(status="Pre-boarding").count()
        tiles.append(_tile("user-plus", "Onboarding", f"{to_make} offers to make · {out} offers out · "
                           f"{starters} new starters", url_for("onboarding.index"), "Open onboarding",
                           tone="featured" if to_make else ""))
    else:
        tiles.append(_tile("user-plus", "Onboarding", "New starters, documents to verify and IT access requests",
                           later=COMING_SOON))
    tiles += [
        _tile("logout", "Off-boarding", "Exits in progress, final pay holds and exit tasks", later=COMING_SOON),
        _tile("target", "Performance management", "FY2027/28 cycle: scorecard templates and deadlines",
              later=COMING_SOON),
        _tile("upload", "Post to Sage 300", "Approved records ready to post to Sage 300 People", later=COMING_SOON),
    ]
    if user.has_role(IT):
        tiles.append(_tile("dashboard", "Reports & dashboards", "Approvals ageing, budget impact and vacancies",
                           url_for("approvals.dashboard"), "Open reports"))
    elif user.has_role(*BUDGET_ROLES) and money:
        tiles.append(_tile("dashboard", "Reports & dashboards", "Budget and demand per department",
                           url_for("budget.report"), "Open reports"))
    if hr:
        employees = Employee.query.filter(Employee.end_date.is_(None)).count()
        tiles.append(_tile("users", "Org & reporting tree", f"{employees} employees on record",
                           url_for("admin.employees"), "Open employees"))
    tiles.append(_tile("award", "Skills audit: qualifications", "Qualifications captured and certificates to verify",
                       later=COMING_SOON))
    if user.has_role(IT):
        tiles.append(_tile("sparkles", "Settings", "Workflows, approval routing, templates, roles and notifications",
                           url_for("admin.settings_page"), "Open settings"))
    return {"intro": "Everything managers have started and staff have responded to, in one place",
            "stats": stats, "tiles": tiles}


def _recruitment_home(user, steps):
    """The Talent Acquisition Specialist's home: recruitment figures and tiles only (5 Nov 2026)."""
    from app.services import adverts
    ready = adverts.ready_query().count()
    open_adverts = Job.query.filter(Job.reference.isnot(None), Job.status == "Open").count()
    in_approval = Job.query.filter(Job.reference.isnot(None), Job.status == "In Approval").count()
    to_screen = Application.query.filter(Application.job_id.isnot(None), Application.status == "New").count()
    with_managers = ShortlistReview.query.filter_by(status="Pending").count()
    week = InterviewSlot.query.filter(InterviewSlot.starts_at >= now(),
                                      InterviewSlot.starts_at < now() + timedelta(days=7)).count()
    stats = [
        _stat(ready, "Ready to advertise", url_for("adverts.index")),
        _stat(open_adverts, "Open adverts", url_for("adverts.index")),
        _stat(to_screen, "Applications to screen", url_for("recruitment.dashboard")),
        _stat(with_managers, "Shortlists with Department Managers", url_for("recruitment.jobs")),
        _stat(week, "Interviews in the next 7 days", url_for("recruitment.jobs")),
    ]
    tiles = [
        _tile("external", "Job adverts",
              f"{ready} approved requisition{'s' if ready != 1 else ''} ready to advertise · {in_approval} with the "
              f"HR Manager · {open_adverts} open", url_for("adverts.index"), "Open job adverts", tone="featured"),
        _tile("briefcase", "Job openings", "Ranked applicants, shortlists, interview panels and candidate messages",
              url_for("recruitment.jobs"), "Open job openings"),
        _tile("trending", "Recruitment dashboard", f"Hiring pipeline and latest applications · {to_screen} to screen",
              url_for("recruitment.dashboard"), "Open dashboard"),
        _tile("database", "CV database", "Every CV, searchable and rankable", url_for("recruitment.candidates"),
              "Search CVs"),
        _tile("file", "JD library", "Standard job descriptions and ATS weights adverts start from",
              url_for("adverts.library"), "Open JD library"),
        _tile("star", "Interviews to score", "You sit on every interview panel: score each candidate's questions "
              "1 to 5", url_for("recruitment.interviews_to_score"),
              f"{sum(1 for r in interviews.to_score(user) if not r['scored'])} to score"),
        _tile("check", "My approvals", "Anything waiting for your decision", url_for("approvals.inbox"),
              f"{len(steps)} waiting"),
    ]
    return {"intro": "Adverts, applicants, shortlists and interviews, in one place", "stats": stats, "tiles": tiles}


def _manager_home(user, steps):
    tasks = []
    for s in steps:
        info = workflow.describe(s.instance)
        label, tone = _due_label(s.due_at)
        tasks.append({"label": label, "tone": tone, "text": f"{s.name}: {info['ref']} {info['title']}".strip(),
                      "link": info["link"]})
    to_score = [r for r in interviews.to_score(user) if not r["scored"]]
    for r in to_score:                                                    # interviews on the user's panels
        name, title = r["application"].candidate.full_name, r["job"].title
        text = (f"Score the interview: {name} for {title}" if r["open"]
                else f"Interview {name} for {title}, {format_datetime(r['slot'].starts_at)}")
        tasks.append({"label": "Interview", "tone": "urgent" if r["open"] else "info", "text": text,
                      "link": url_for("recruitment.scorecard", app_id=r["application"].id)})
    for review in shortlisting.reviews_for(user, pending_only=True):     # shortlists HR sent the Department Manager
        tasks.append({"label": "Shortlist", "tone": "urgent",
                      "text": f"Pick who goes to interview: {review.job.title} ({len(review.application_ids)})",
                      "link": url_for("recruitment.shortlist_review", review_id=review.id)})
    returned = (Requisition.query.filter_by(originator_id=user.id, status="Returned")
                .order_by(Requisition.updated_at.desc()).all())
    for r in returned:
        tasks.append({"label": "Returned", "tone": "urgent", "text": f"Fix and resubmit: {r.reference} {r.title}",
                      "link": url_for("requisitions.detail", req_id=r.id)})
    since = now() - timedelta(days=7)
    for r in (Requisition.query.filter(Requisition.originator_id == user.id, Requisition.status == "Approved",
                                       Requisition.updated_at >= since).order_by(Requisition.updated_at.desc())):
        tasks.append({"label": "Info", "tone": "info", "text": f"Approved: {r.reference} {r.title}",
                      "link": url_for("requisitions.detail", req_id=r.id)})

    pos = _position_counts(user)
    team = Employee.query.filter_by(manager_id=user.employee_id).filter(Employee.end_date.is_(None)).count() \
        if user.employee_id else 0
    open_mine = Requisition.query.filter(Requisition.originator_id == user.id,
                                         Requisition.status.in_(positions.OPEN_REQUISITION)).count()
    glance = [(team, "people report to you"), (pos.get("Vacant", 0), "vacant positions in your area"),
              (pos.get("In recruitment", 0), "vacancies in recruitment"), (open_mine, "open requisitions you raised")]
    if user.has_role(*requisitions.CREATE_ROLES):         # Department Managers raise requisitions
        requisition_tiles = [
            _tile("plus", "Raise a requisition",
                  "Pick an approved vacant position, or request an ad-hoc position first. "
                  "Approval: line manager, Finance, HR, GCOO.", url_for("requisitions.new"), "Start", tone="featured"),
            _tile("check", "Approvals", "Requests waiting for your decision", url_for("approvals.inbox"),
                  f"{len(steps)} waiting"),
            _tile("file", "My requisitions", "Track the requests you've raised through approval",
                  url_for("requisitions.index"), f"{open_mine} open"),
        ]
    else:                                                    # Line Managers approve their Department Managers' requests
        requisition_tiles = [
            _tile("check", "Approvals", "Requisitions and requests waiting for your decision", url_for("approvals.inbox"),
                  f"{len(steps)} waiting", tone="featured"),
            _tile("file", "Team requisitions", "Follow the requisitions your Department Managers have raised",
                  url_for("requisitions.index"), "View requisitions"),
        ]
    tiles = requisition_tiles + [
        _tile("trending", "Vacancy dashboard", "Your area's approved positions: filled, vacant and in recruitment",
              url_for("positions.dashboard"), "Open dashboard"),
        _tile("star", "Interviews", "Score candidates and recommend an appointment",
              url_for("recruitment.interviews_to_score"), f"{len(to_score)} to score"),
        _tile("user-plus", "Onboarding", "Induction checklists, buddy, 30/60/90-day check-ins, probation reviews",
              later=COMING_SOON),
        _tile("logout", "Start an exit", "Resignation, end of contract or other exit; handover and asset return",
              later=COMING_SOON),
        _tile("target", "Performance", "Create agreements and run appraisals for your team", later=COMING_SOON),
    ]
    return {"intro": "Start HR processes for your team and track them here",
            "tasks": tasks, "glance": glance, "tiles": tiles}


def _staff_home(user, steps, unread):
    banner = None
    if steps:
        banner = {"title": f"Action needed: {len(steps)} request{'s' if len(steps) != 1 else ''} waiting for you",
                  "text": "Review and respond in your approvals inbox.", "link": url_for("approvals.inbox"),
                  "link_label": "Review now"}
    tiles = [
        _tile("users", "My profile", "Your details, position and reporting line", url_for("portal.me"),
              "Open my profile", tone="featured"),
        _tile("mail", "Notifications", "Updates on requests and tasks that involve you",
              url_for("portal.notifications"), f"{unread} unread"),
        _tile("edit", "My performance agreement", "Agree and sign your balanced-scorecard agreement",
              later=COMING_SOON),
        _tile("target", "My appraisals", "Mid-year and year-end self-ratings against your signed agreement",
              later=COMING_SOON),
        _tile("award", "My qualifications", "Add or update your qualifications and upload certificates for HR to verify",
              later=COMING_SOON),
        _tile("calendar", "Leave and payslips", "Apply for leave, check balances and download payslips in Sage 300 "
                                          "self-service", settings.get("sage_self_service_url"), tone="dark",
              link_label="Open Sage 300 self-service"),
    ]
    return {"intro": "Your ICE People tasks. Leave, payslips and other self-service stay in Sage 300.",
            "banner": banner, "tiles": tiles}


@bp.route("/portal/<any(admin, manager, staff):name>")
@roles_required()
def switch_portal(name):
    """Move between the portals the user has (everyone has staff self-service)."""
    if name not in current_user.portals:
        abort(403)
    session["portal"] = name
    flash(f"You're in the {PORTAL_LABELS[name]}.", "info")
    return redirect(url_for("dashboards.home"))


@bp.route("/dashboard")
@roles_required()
def home():
    user = current_user
    steps = workflow.pending_for(user)
    portal = current_portal(user)
    if portal == "admin":
        page = _recruitment_home(user, steps) if user.recruitment_only else _admin_home(user, steps)
    elif portal == "manager":
        page = _manager_home(user, steps)
    else:
        from app.services.notifications import unread_count
        page = _staff_home(user, steps, unread_count(user))
    return render_template("dashboards/home.html", portal=portal, greeting=_greeting(),
                           date_label=f"{today():%A}, {today().day} {today():%B %Y}", **page)
