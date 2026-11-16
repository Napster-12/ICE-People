"""Onboarding, run by HR Admin (8 Nov 2026, at the user's request): offers to make, offers, onboarding cases with the
employee number, the candidate's documents and the signed contract (attached by the department's HR Business
Partner, who sees their departments' cases), the offer letter template and the required documents list. Business rules are in services/onboarding.py."""
from datetime import date

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import Application, DocumentTemplate, Offer, OnboardingCase
from app.models.onboarding import OFFER_EDITABLE, OFFER_OPEN, SALUTATIONS
from app.models.org import EMPLOYMENT_TYPES
from app.models.user import FINANCE, HRBP
from app.services import (audit, candidate_forms, careers, documents, files, onboarding, screening, settings, starter_pack,
                          workflow)
from app.services.dates import today
from app.services.errors import DomainError

bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")
EDIT = onboarding.EDIT_ROLES
VIEW = onboarding.VIEW_ROLES
CASE_VIEW = (*VIEW, HRBP)                               # an HR BP sees their departments' new starters


def _base_url():
    return current_app.config.get("PUBLIC_BASE_URL") or request.host_url


def _pdf(data, name, download=False):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"',
                             "X-Content-Type-Options": "nosniff"})


@bp.route("")
@roles_required(*CASE_VIEW)
def index():
    sees_offers = current_user.has_role(*VIEW)
    offers = Offer.query.order_by(Offer.created_at.desc()).limit(100).all() if sees_offers else []
    return render_template("onboarding/index.html", to_make=onboarding.offers_to_make() if sees_offers else [],
                           open_offers=[o for o in offers if o.status in OFFER_OPEN],
                           closed_offers=[o for o in offers if o.status not in OFFER_OPEN][:20],
                           sees_offers=sees_offers, cases=onboarding.cases(current_user), today=today(),
                           can_edit=onboarding.can_edit(current_user), checks=screening.waiting(current_user),
                           packs_to_review=starter_pack.to_review(current_user),
                           check_status=screening.status_of)


@bp.route("/offers/new/<int:app_id>", methods=["GET", "POST"])
@roles_required(*VIEW)
def new_offer(app_id):
    application = db.session.get(Application, app_id) or abort(404)
    existing = onboarding.current_offer(application)
    if existing:
        return redirect(url_for("onboarding.offer", offer_id=existing.id))
    if request.method == "POST":
        if not onboarding.can_edit(current_user):
            abort(403)
        offer = onboarding.draft(application, current_user)
        db.session.commit()
        flash("Offer drafted from the requisition. Check the details, then send it.", "success")
        return redirect(url_for("onboarding.offer", offer_id=offer.id))
    return render_template("onboarding/new_offer.html", application=application,
                           can_edit=onboarding.can_edit(current_user))


@bp.route("/offers/<int:offer_id>", methods=["GET", "POST"])
@roles_required(*VIEW, FINANCE)
def offer(offer_id):
    offer = db.session.get(Offer, offer_id) or abort(404)
    if not onboarding.can_view(current_user, offer):
        abort(403)
    if onboarding.expire_if_due(offer):
        db.session.commit()
    form = request.form
    if request.method == "POST":
        if not onboarding.can_edit(current_user):
            abort(403)
        action = form.get("action")
        try:
            if action == "save":
                onboarding.save(offer, form, current_user)
                message = "Offer saved."
            elif action == "send":
                if offer.status in OFFER_EDITABLE:
                    onboarding.save(offer, form, current_user)
                outcome = onboarding.send(offer, current_user, _base_url())
                message = {"sent": f"Offer sent to {offer.candidate.email}.",
                           "approval": "The offer is above the requisition's costed CTC, so it has gone to Finance "
                                       "for approval. Send it once it's approved and the background checks are clear.",
                           "approved": "The offer is approved. Send it once the background checks are clear."}[outcome]
            elif action == "withdraw":
                onboarding.withdraw(offer, current_user, form.get("reason", ""))
                message = "Offer withdrawn."
            else:
                abort(400)
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("onboarding.offer", offer_id=offer.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            offer = db.session.get(Offer, offer_id)
    instance = workflow.latest_instance("offer", offer.id)
    my_step = None
    if instance and instance.status == "Pending":
        step = instance.current_step
        if step and workflow.can_act(step, current_user):
            my_step = step
    return render_template("onboarding/offer.html", offer=offer, form=form, types=EMPLOYMENT_TYPES, my_step=my_step,
                           salutations=SALUTATIONS,
                           costed=onboarding.costed_ctc(offer.application), instance=instance,
                           history=workflow.history("offer", offer.id),
                           editable=offer.status in OFFER_EDITABLE and onboarding.can_edit(current_user),
                           can_edit=onboarding.can_edit(current_user), case=offer.onboarding_case,
                           screening=offer.application.screening,
                           check_problem=screening.problem(offer.application))


@bp.route("/checks/<int:app_id>", methods=["GET", "POST"])
@roles_required(*CASE_VIEW)
def checks(app_id):
    """Background checks before the offer (16 Nov 2026): HR Admin or the department's HR Business Partner."""
    application = db.session.get(Application, app_id) or abort(404)
    if not screening.can_view(current_user, application):
        abort(403)
    if request.method == "POST":
        if not screening.can_manage(current_user, application):
            abort(403)
        action = request.form.get("action")
        try:
            if action == "start":
                screening.start(application, current_user, _base_url())
                message = f"Background checks started. {application.candidate.email} has been emailed to consent."
            elif action == "resend":
                screening.resend(application.screening or abort(400), current_user, _base_url())
                message = f"The consent request was emailed to {application.candidate.email} again."
            elif action == "record":
                check = next((c for c in (application.screening.checks if application.screening else [])
                              if str(c.id) == request.form.get("check_id")), None) or abort(400)
                raw = request.form.get("completed_on", "")
                try:
                    completed_on = date.fromisoformat(raw) if raw else None
                except ValueError:
                    completed_on = None
                values = {"status": request.form.get("status"), "completed_on": completed_on,
                          "provider_reference": request.form.get("provider_reference"),
                          "notes": request.form.get("notes")}
                screening.record(check, values, request.files.get("report"), current_user)
                message = f"{check.name}: {check.status.lower()} recorded."
            elif action == "reject":
                screening.reject(application, current_user, request.form.get("reason", ""))
                message = f"{application.candidate.full_name} marked unsuccessful. Send the regret from the job's messages page."
            else:
                abort(400)
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("onboarding.checks", app_id=application.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            application = db.session.get(Application, app_id)
    record = application.screening
    return render_template("onboarding/checks.html", application=application, screening=record,
                           can_manage=screening.can_manage(current_user, application),
                           can_record=record is not None and screening.can_record(current_user, record),
                           reports={c.id: screening.reports(c) for c in (record.checks if record else [])},
                           hrbp=screening.hrbp_for(application), offer=onboarding.current_offer(application),
                           sees_offers=current_user.has_role(*VIEW), today=today(),
                           config_checks=screening.checklist(),
                           consent_files=screening.consent_files(record) if record else [],
                           problem=screening.problem(application), locked=screening.locked(application))


@bp.route("/offers/<int:offer_id>/letter.pdf")
@roles_required(*VIEW, FINANCE)
def offer_letter(offer_id):
    offer = db.session.get(Offer, offer_id) or abort(404)
    if not onboarding.can_view(current_user, offer):
        abort(403)
    audit.record("offer.letter_viewed", "offer", offer.id)
    db.session.commit()
    return _pdf(onboarding.letter_pdf(offer), f"{offer.reference} offer letter.pdf")


@bp.route("/cases/<int:case_id>", methods=["GET", "POST"])
@roles_required(*CASE_VIEW)
def case(case_id):
    case = db.session.get(OnboardingCase, case_id) or abort(404)
    if not onboarding.can_view_case(current_user, case):
        abort(403)
    if request.method == "POST":
        action = request.form.get("action")
        if action in ("pack_approve", "pack_return"):
            allowed = case.pack is not None and starter_pack.can_review(current_user, case.pack)
        elif action == "employee_number":
            allowed = onboarding.can_edit(current_user)
        else:
            allowed = onboarding.can_attach_contract(current_user, case)
        if not allowed:
            abort(403)
        try:
            if action == "pack_approve":
                starter_pack.approve(case.pack, current_user)
                message = "New starter pack approved. The employee record has been updated."
            elif action == "pack_return":
                starter_pack.return_pack(case.pack, current_user, request.form.get("comment"), _base_url())
                message = f"Returned to {case.employee.full_name} to correct."
            elif action == "employee_number":
                onboarding.set_employee_number(case.employee, request.form.get("employee_number"), current_user)
                message = "Employee number saved."
            elif action == "signed":
                raw = request.form.get("signed_on", "")
                try:
                    signed_on = date.fromisoformat(raw) if raw else None
                except ValueError:
                    signed_on = None
                onboarding.upload_signed(case, request.files.get("contract"), signed_on, current_user)
                message = "Signed contract uploaded."
            else:
                abort(400)
            db.session.commit()
            flash(message, "success")
            back = request.form.get("next") or ""                   # from My Approvals (16 Nov 2026)
            if back.startswith("/") and not back.startswith("//"):
                return redirect(back)
            return redirect(url_for("onboarding.case", case_id=case.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            case = db.session.get(OnboardingCase, case_id)
    return render_template("onboarding/case.html", case=case, copies=onboarding.signed_copies(case), today=today(),
                           can_edit=onboarding.can_edit(current_user), sees_offers=current_user.has_role(*VIEW),
                           can_attach=onboarding.can_attach_contract(current_user, case),
                           hrbp=onboarding.hrbp_for(case), documents=onboarding.case_documents(case),
                           pack=case.pack, can_review=case.pack is not None and starter_pack.can_review(current_user,
                                                                                                      case.pack),
                           pack_sections=starter_pack.sections_with_answers(case.pack) if case.pack else [],
                           pack_docs=starter_pack.uploaded(case.pack) if case.pack else {},
                           pack_doc_list=starter_pack.DOCUMENTS,
                           pack_link=starter_pack.link(case.pack, _base_url()) if case.pack else None)


@bp.route("/cases/<int:case_id>/take-on.pdf")
@roles_required(*CASE_VIEW)
def takeon_pdf(case_id):
    case = db.session.get(OnboardingCase, case_id) or abort(404)
    if not onboarding.can_view_case(current_user, case) or case.pack is None:
        abort(403 if case.pack else 404)
    audit.record("starter_pack.viewed", "onboarding_case", case.id)
    db.session.commit()
    return _pdf(starter_pack.takeon_pdf(case.pack), f"{case.reference} take-on form.pdf")


@bp.route("/templates", methods=["GET", "POST"])
@roles_required(*EDIT)
def templates():
    documents.ensure_documents()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "signatory":
                for key, field in (("letter_signatory_name", "signatory_name"),
                                   ("letter_signatory_title", "signatory_title")):
                    value = request.form.get(field, "").strip()[:120]
                    if key == "letter_signatory_title" and not value:
                        raise DomainError("Enter the signatory's job title.")
                    if value != settings.get(key):
                        audit.record("config.setting", "setting", key, before={"value": settings.get(key)},
                                     after={"value": value})
                        settings.set_value(key, value)
                message = "Signatory saved."
            elif action == "signature":
                upload = request.files.get("signature")
                if upload is None or not upload.filename:
                    raise DomainError("Choose the signature image (PNG or JPG).")
                stored = files.save_upload(upload, documents.SIGNATURE_FILE, None, user=current_user,
                                           allowed={".png", ".jpg", ".jpeg"})
                audit.record("document.signature", "stored_file", stored.id, after={"file": stored.original_name})
                message = "Signature uploaded. It's on every offer letter from now on."
            elif action == "remove_signature":
                sig = documents.signature_file()
                if sig:
                    audit.record("document.signature_removed", "stored_file", sig.id)
                    files.delete(sig)
                message = "Signature removed."
            elif action == "documents":
                names = onboarding.set_required_documents(request.form.get("documents", ""), current_user)
                message = (f"{len(names)} required document{'s' if len(names) != 1 else ''} saved." if names
                           else "Saved. Candidates won't be asked for any documents.")
            elif action == "checks":
                names = screening.set_checklist(request.form.get("checks", ""), current_user)
                message = f"{len(names)} background check{'s' if len(names) != 1 else ''} saved."
            elif action == "application_docs":
                required, optional = careers.set_application_documents(request.form.get("required", ""),
                                                                       request.form.get("optional", ""), current_user)
                message = f"Saved: {len(required)} required and {len(optional)} optional documents when applying."
            elif action == "form":
                key = request.form.get("key")
                candidate_forms.replace(key, request.files.get("form"), current_user)
                message = f"{candidate_forms.title(key)} replaced. Candidates download the new copy from now on."
            else:
                abort(400)
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("onboarding.templates"))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    db.session.commit()
    return render_template("onboarding/templates.html", signature=documents.signature_file(),
                           templates=DocumentTemplate.query.order_by(DocumentTemplate.id).all(),
                           signatory=documents.signatory(), required=onboarding.required_documents(),
                           checks=screening.checklist(), forms=candidate_forms.listing(),
                           app_required=careers.required_documents(), app_optional=careers.optional_documents())


@bp.route("/forms/<key>.pdf")
@roles_required(*CASE_VIEW)
def blank_form(key):
    """The current blank form, as candidates download it."""
    if key not in candidate_forms.FORMS:
        abort(404)
    return _pdf(candidate_forms.data(key), candidate_forms.filename(key))


@bp.route("/templates/<int:template_id>", methods=["GET", "POST"])
@roles_required(*EDIT)
def template(template_id):
    tpl = db.session.get(DocumentTemplate, template_id) or abort(404)
    if request.method == "POST":
        title, body = request.form.get("title", "").strip(), request.form.get("body", "").strip()
        try:
            if request.form.get("action") == "reset":
                _name, title, body = documents.DEFAULTS[tpl.key]
            elif not title or not body:
                raise DomainError("Enter the title and the wording.")
            documents.check_template(title, body)
            before = {"title": tpl.title, "body": tpl.body}
            tpl.title, tpl.body, tpl.updated_by_id = title, body, current_user.id
            b, a = audit.changes(before, {"title": title, "body": body})
            audit.record("update", "document_template", tpl.id, before=b, after=a)
            db.session.commit()
            flash("Template saved." if request.form.get("action") != "reset" else "Template reset to the default.",
                  "success")
            return redirect(url_for("onboarding.template", template_id=tpl.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("onboarding/template_form.html", tpl=tpl, form=request.form,
                           placeholders=documents.PLACEHOLDERS)


@bp.route("/templates/<int:template_id>/preview.pdf")
@roles_required(*EDIT)
def template_preview(template_id):
    tpl = db.session.get(DocumentTemplate, template_id) or abort(404)
    sample = {**documents.signatory(), "today": documents.long_date(today()), "salutation": "Mr",
              "name": "Codnell Chabalala", "address": "56 Jorrisen St\nBraamfontein\nJohannesburg\n2001",
              "ref": "OFR-2026-00001", "title": "Systems Analyst", "department": "ICT",
              "reports_to": "Group ICT Manager, Tinashe Chadamoyo", "location": "215 Peter Mokaba Road, Morningside",
              "grade": "Professional / Experienced / Specialists / Mid-Management",
              "employment_type": "Permanent", "employment": "Permanent Employment", "start_date": "01 July 2026",
              "end_date": "", "ctc": "R 360 000.00",
              "monthly": "R 30 000.00", "probation": "six (6) months", "conditions": [],
              "expires_on": "24 June 2026", "accepted_by": "", "accepted_on": ""}
    try:
        title, body = documents._env.from_string(tpl.title).render(**sample), \
            documents._env.from_string(tpl.body).render(**sample)
        return _pdf(documents.pdf(title, body.strip(), ref=sample["ref"]),
                    f"{tpl.name}.pdf")
    except Exception as exc:  # noqa: BLE001 - show HR Admin what's wrong instead of a server error
        flash(f"The preview couldn't be made: {exc}", "error")
        return redirect(url_for("onboarding.template", template_id=tpl.id))
