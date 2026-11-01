"""Job adverts (REQ-JA-001–008, spec §4.4): drafted from a fully approved requisition and the JD library, versioned,
approved by the HR Manager through the workflow engine, then published to the careers site and the job portals.
Adverts close after their closing date (`flask close-expired-adverts`) and can be re-advertised in a new cycle."""
from datetime import date, timedelta

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.integrations.job_portals import CHANNELS as PORTAL_CHANNELS
from app.models import AdvertPosting, AdvertVersion, Job, JobDescriptionTemplate, Requisition
from app.models.user import HR_ADMIN, RECRUITER
from app.services import audit, positions, requisitions, settings, workflow
from app.services.ats import EDUCATION_LABELS
from app.services.dates import now, today
from app.services.errors import DomainError, StateMachine
from app.services.notifications import notify, users_with_role
from app.services.refs import next_reference

FLOW = StateMachine("advert", {
    "Draft": {"In Approval", "Cancelled"},
    "Returned": {"In Approval", "Cancelled"},
    "In Approval": {"Open", "Returned", "Rejected", "Cancelled"},
    "Open": {"Closed"},
    "Closed": {"Draft"},
    "Rejected": set(), "Cancelled": set(),
})
EDITABLE = {"Draft", "Returned"}
ACTIVE = ("Draft", "Returned", "In Approval", "Open", "Closed")   # a requisition has at most one of these
CAREERS_SITE = "Careers site"                                     # always on; the only place to apply (§15.4)
CHANNELS = PORTAL_CHANNELS
DEFAULT_CHANNELS = ["Internal", "Intranet"]
JOB_TYPE_FOR = {"Permanent": "Full-time", "Contract": "Contract", "Casual": "Part-time"}
FIELDS = ["title", "department", "location", "job_type", "description", "required_skills", "preferred_skills",
          "min_experience", "min_education", "ats_weights", "closing_date", "ee_statement", "channels"]
JD_FIELDS = ["title", "job_family_id", "description", "required_skills", "preferred_skills", "min_experience",
             "min_education", "ats_weights", "review_date", "active"]
JD_REMIND_DAYS = 30


def data_snapshot(job):
    return {f: (v.isoformat() if isinstance(v, date) else v) for f in FIELDS for v in [getattr(job, f)]}


def set_status(job, new, detail=None):
    FLOW.check(job.status, new)
    old = job.status
    job.status = new
    audit.record("status_change", "advert", job.id, before={"status": old}, after={"status": new}, detail=detail)


# ------------------------------------------------------------- JD library

def match_template(position):
    """The JD to start from: same title first, then same job family."""
    q = JobDescriptionTemplate.query.filter_by(active=True)
    found = q.filter(db.func.lower(JobDescriptionTemplate.title) == position.title.lower()).first()
    if found is None and position.job_family_id:
        found = q.filter_by(job_family_id=position.job_family_id).order_by(JobDescriptionTemplate.title).first()
    return found


def save_template(template, values, user):
    errors = []
    if not values.get("title"):
        errors.append("Enter the job title.")
    if not values.get("description"):
        errors.append("Enter the job description.")
    if not values.get("review_date"):
        errors.append("Enter the next review date.")
    if errors:
        raise DomainError(" ".join(errors))
    before = {f: str(getattr(template, f)) for f in JD_FIELDS} if template.id else {}
    if template.review_date != values["review_date"]:
        template.reminded_at = None
    for f in JD_FIELDS:
        setattr(template, f, values.get(f, getattr(template, f)))
    template.updated_by_id = user.id
    if template.id is None:
        db.session.add(template)
        db.session.flush()
        audit.record("create", "jd_template", template.id, after={"title": template.title})
    else:
        b, a = audit.changes(before, {f: str(getattr(template, f)) for f in JD_FIELDS})
        audit.record("update", "jd_template", template.id, before=b, after=a)
    return template


def remind_jd_reviews(on=None):
    """Tell recruiters and HR Admin about JDs due for their annual review within JD_REMIND_DAYS. Once per date."""
    on = on or today()
    due = (JobDescriptionTemplate.query.filter(JobDescriptionTemplate.active.is_(True),
                                               JobDescriptionTemplate.review_date <= on + timedelta(days=JD_REMIND_DAYS),
                                               JobDescriptionTemplate.reminded_at.is_(None))
           .order_by(JobDescriptionTemplate.review_date).all())
    people = users_with_role(RECRUITER) + users_with_role(HR_ADMIN)
    for t in due:
        notify(people, "jd_review_due", link=f"/adverts/library/{t.id}/edit", title=t.title,
               due=f"{t.review_date:%-d %B %Y}")
        t.reminded_at = now()
    return len(due)


# ---------------------------------------------------------------- drafting

def advert_for(req):
    """The requisition's current advert (not rejected or cancelled), if any."""
    return (Job.query.filter(Job.requisition_id == req.id, Job.status.in_(ACTIVE))
            .order_by(Job.id.desc()).first())


def ready_query():
    """Fully approved requisitions that don't have an advert yet."""
    taken = db.select(Job.requisition_id).where(Job.requisition_id.isnot(None), Job.status.in_(ACTIVE))
    return Requisition.query.filter(Requisition.status == "Approved", Requisition.id.notin_(taken))


def _location(position):
    if position is None or position.branch is None:
        return ""
    region = position.region
    return f"{position.branch.name}, {region.name}" if region is not None else position.branch.name


def _description(req, template):
    intro = template.description if template else (
        f"Icebolethu Group is looking for a {req.title} to join the "
        f"{req.department.name if req.department else 'team'}.\n\nKEY RESPONSIBILITIES\n- ")
    lines = []
    position = req.approved_position
    if position is not None and position.minimum_requirements:
        lines = [l.strip().lstrip("-•*").strip() for l in position.minimum_requirements.splitlines() if l.strip()]
    if lines and "MINIMUM REQUIREMENTS" not in intro.upper():
        intro = intro.rstrip() + "\n\nMINIMUM REQUIREMENTS\n" + "\n".join(f"- {l}" for l in lines)
    if req.employment_type == "Contract" and req.contract_end_date:
        intro = intro.rstrip() + f"\n\nThis is a fixed-term contract until {req.contract_end_date:%-d %B %Y}."
    return intro


def draft_from_requisition(req, user, template=None, use_library=True):
    """Create a draft advert from a fully approved requisition (JA-001), starting from the JD library: the given
    template, or the best match unless use_library is False."""
    if req.status != "Approved":
        raise DomainError("Only fully approved requisitions can be advertised.")
    existing = advert_for(req)
    if existing is not None:
        raise DomainError(f"{req.reference} already has an advert ({existing.reference}).")
    position = req.approved_position
    if template is None and use_library and position is not None:
        template = match_template(position)
    job = Job(reference=next_reference("ADV"), requisition_id=req.id, jd_template_id=template.id if template else None,
              title=req.title, department=req.department.name if req.department else "",
              location=_location(position), job_type=JOB_TYPE_FOR.get(req.employment_type, "Full-time"),
              description=_description(req, template),
              required_skills=template.required_skills if template else "",
              preferred_skills=template.preferred_skills if template else "",
              min_experience=template.min_experience if template else 0,
              min_education=template.min_education if template else 0,
              ats_weights=template.ats_weights if template else None,
              closing_date=today() + timedelta(days=settings.get("advert_closing_days", int)),
              ee_statement=settings.get("advert_ee_statement"), channels=list(DEFAULT_CHANNELS),
              status="Draft", cycle=1, created_by_id=user.id, created_at=now())
    db.session.add(job)
    db.session.flush()
    audit.record("create", "advert", job.id, after={"reference": job.reference, "requisition": req.reference,
                                                    "jd_template_id": job.jd_template_id})
    _save_version(job, user)
    return job


def _save_version(job, user):
    job.version = (job.version or 0) + 1
    db.session.add(AdvertVersion(job_id=job.id, version=job.version, cycle=job.cycle, data=data_snapshot(job),
                                 created_by_id=user.id if user else None, created_at=now()))


def problems(job):
    """Mandatory advert content (JA-004). Empty list when the advert can go for approval."""
    errors = []
    if not (job.title or "").strip():
        errors.append("Enter the job title.")
    if not (job.description or "").strip():
        errors.append("Enter the job description.")
    if not (job.job_type or "").strip():
        errors.append("Choose the employment type.")
    if not (job.location or "").strip():
        errors.append("Enter the location.")
    if not job.closing_date:
        errors.append("Enter the closing date.")
    elif job.closing_date <= today():
        errors.append("The closing date must be in the future.")
    if not job.min_education:
        errors.append("Choose the minimum qualification.")
    if job.min_experience is None:
        errors.append("Enter the years of experience needed (0 if none).")
    if not (job.ee_statement or "").strip():
        errors.append("Enter the employment equity and equal opportunity statement.")
    if any(c not in CHANNELS for c in job.channels or []):
        errors.append("Choose channels from the list.")
    return errors


def save(job, values, user):
    """Apply a recruiter's edits to a draft or returned advert and keep a version (JA-003)."""
    if job.status not in EDITABLE:
        raise DomainError("Only draft or returned adverts can be edited.")
    before = data_snapshot(job)
    for f in FIELDS:
        if f in values:
            setattr(job, f, values[f])
    after = data_snapshot(job)
    b, a = audit.changes(before, after)
    if a:
        audit.record("update", "advert", job.id, before=b, after=a)
        _save_version(job, user)
    return job


def submit(job, user):
    """Send the advert to the HR Manager for approval (JA-005)."""
    if job.status not in EDITABLE:
        raise DomainError(f"A {job.status.lower()} advert can't be sent for approval.")
    req = job.requisition
    if req is None or req.status not in ("Approved", "Advertised", "Interviewing"):
        raise DomainError("The requisition is no longer open, so this advert can't be published.")
    errors = problems(job)
    if errors:
        raise DomainError(" ".join(errors))
    set_status(job, "In Approval")
    return workflow.start("advert", "advert", job.id, user, workflow_context(job), department=req.department)


def workflow_context(job):
    req = job.requisition
    return {"department_id": req.department_id if req else None,
            "grade": req.job_grade.grade if req and req.job_grade else 0,
            "employment_type": req.employment_type if req else "", "cycle": job.cycle}


# ------------------------------------------------------- publish and close

def _posting(job, channel):
    return next((p for p in job.postings if p.cycle == job.cycle and p.channel == channel), None)


def publish(job):
    """Put an approved advert live: careers site first, then each chosen job portal (mock adapters)."""
    set_status(job, "Open", detail=f"Cycle {job.cycle}")
    job.published_at, job.closed_at, job.close_reason = now(), None, None
    db.session.add(AdvertPosting(job=job, cycle=job.cycle, channel=CAREERS_SITE, status="Live", published_at=now()))
    portal = get_adapter("job_portals")
    failed = []
    for channel in job.channels or []:
        posting = AdvertPosting(job=job, cycle=job.cycle, channel=channel)
        try:
            result = portal.publish_advert(channel, job)
            posting.external_id, posting.status, posting.published_at = result["external_id"], "Live", now()
        except IntegrationError as exc:
            posting.status, posting.error = "Failed", str(exc)[:255]
            failed.append(channel)
        db.session.add(posting)
    req = job.requisition
    if req is not None:
        if req.status in ("Approved", "Interviewing"):
            requisitions.set_status(req, "Advertised", comment=f"Advert {job.reference} published")
        positions.start_recruitment(req.approved_position, req)
    if job.created_by:
        notify(job.created_by, "advert_published", link=f"/adverts/{job.id}", ref=job.reference, title=job.title,
               channels=", ".join([CAREERS_SITE] + [c for c in job.channels or [] if c not in failed]),
               failed=", ".join(failed), closing=f"{job.closing_date:%-d %B %Y}")


def close(job, reason, user=None):
    if job.status != "Open":
        raise DomainError("Only live adverts can be closed.")
    portal = get_adapter("job_portals")
    for posting in job.postings:
        if posting.cycle != job.cycle or posting.status != "Live":
            continue
        if posting.channel != CAREERS_SITE:
            try:
                portal.close_advert(posting.channel, posting.external_id)
            except IntegrationError as exc:
                audit.record("advert.channel_close_failed", "advert", job.id, detail=f"{posting.channel}: {exc}",
                             user=user)
        posting.status, posting.closed_at = "Closed", now()
    set_status(job, "Closed", detail=reason)
    job.closed_at, job.close_reason = now(), reason
    if job.created_by:
        notify(job.created_by, "advert_closed", link=f"/adverts/{job.id}", ref=job.reference, title=job.title,
               reason=reason, applications=len(job.applications))


def close_expired(on=None):
    """Close every live advert whose closing date has passed (JA-007). Returns how many were closed."""
    on = on or today()
    expired = Job.query.filter(Job.status == "Open", Job.closing_date < on).all()
    for job in expired:
        if job.is_advert:
            close(job, f"Closing date {job.closing_date:%-d %B %Y} passed")
        else:  # imported from the old portal: no channels to close
            job.status, job.closed_at = "Closed", now()
    return len(expired)


def readvertise(job, user):
    """Start a new cycle (JA-008): back to draft with a new closing date, for approval again."""
    if job.status != "Closed":
        raise DomainError("Only closed adverts can be re-advertised.")
    req = job.requisition
    if req is None or req.status not in ("Advertised", "Interviewing"):
        raise DomainError("The requisition is no longer open, so it can't be re-advertised.")
    set_status(job, "Draft", detail=f"Re-advertised: cycle {job.cycle + 1}")
    job.cycle += 1
    job.closing_date = today() + timedelta(days=settings.get("advert_closing_days", int))
    _save_version(job, user)
    return job


def withdraw_for_requisition(req, reason):
    """The requisition closed unfilled: cancel or close its advert."""
    job = advert_for(req)
    if job is None:
        return
    if job.status == "Open":
        close(job, reason)
    elif job.status in ("Draft", "Returned", "In Approval"):
        workflow.cancel(workflow.latest_instance("advert", job.id))
        set_status(job, "Cancelled", detail=reason)


# ---------------------------------------------------------------- tracking

def channel_for(source):
    """Normalise a ?src= tag on a careers link to one of our channels."""
    for c in CHANNELS:
        if (source or "").strip().lower() == c.lower():
            return c
    return CAREERS_SITE


def record(job, channel, field):
    """Count a view or an application against the channel it came from (JA-006)."""
    if not job.is_advert:
        return
    posting = _posting(job, channel) or _posting(job, CAREERS_SITE)
    if posting is not None:
        setattr(posting, field, (getattr(posting, field) or 0) + 1)


def stats(job):
    """Views and applications per channel for each cycle, newest first, plus source of hire."""
    cycles = {}
    for p in job.postings:
        cycles.setdefault(p.cycle, []).append(p)
    hires = {}
    for a in job.applications:
        if a.status == "Hired":
            hires[a.source] = hires.get(a.source, 0) + 1
    return {"cycles": sorted(cycles.items(), reverse=True), "hires": hires}


def education_label(level):
    return EDUCATION_LABELS.get(level or 0, "")


# ------------------------------------------------------- workflow handlers

def _job(instance):
    return db.session.get(Job, instance.entity_id)


def _on_approved(instance):
    publish(_job(instance))


def _on_returned(instance):
    set_status(_job(instance), "Returned")


def _on_rejected(instance):
    set_status(_job(instance), "Rejected")


def _describe(instance):
    job = _job(instance)
    return {"ref": job.reference, "title": job.title, "link": f"/adverts/{job.id}"}


workflow.register("advert", describe=_describe, on_approved=_on_approved, on_returned=_on_returned,
                  on_rejected=_on_rejected,
                  sample_context={"department_id": 1, "grade": 5, "employment_type": "Permanent", "cycle": 1})
