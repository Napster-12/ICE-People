"""Onboarding, run by HR Admin (8 Nov 2026, at the user's request): offers to make, offers, onboarding cases with the
employee number and contract, and the letter and contract templates. Business rules are in services/onboarding.py."""
from datetime import date

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import Application, DocumentTemplate, Offer, OnboardingCase
from app.models.onboarding import OFFER_EDITABLE, OFFER_OPEN, SALUTATIONS
from app.models.org import EMPLOYMENT_TYPES
from app.models.user import FINANCE
from app.services import audit, documents, files, onboarding, settings, workflow
from app.services.dates import today
from app.services.errors import DomainError

bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")
EDIT = onboarding.EDIT_ROLES
VIEW = onboarding.VIEW_ROLES


def _base_url():
    return current_app.config.get("PUBLIC_BASE_URL") or request.host_url


def _pdf(data, name, download=False):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"',
                             "X-Content-Type-Options": "nosniff"})


@bp.route("")
@roles_required(*VIEW)
def index():
    offers = Offer.query.order_by(Offer.created_at.desc()).limit(100).all()
    return render_template("onboarding/index.html", to_make=onboarding.offers_to_make(),
                           open_offers=[o for o in offers if o.status in OFFER_OPEN],
                           closed_offers=[o for o in offers if o.status not in OFFER_OPEN][:20],
                           cases=onboarding.cases(), today=today(), can_edit=onboarding.can_edit(current_user))


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
                message = (f"Offer sent to {offer.candidate.email}." if outcome == "sent" else
                           "The offer is above the requisition's costed CTC, so it has gone to Finance for approval. "
                           "Send it once it's approved.")
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
                           can_edit=onboarding.can_edit(current_user), case=offer.onboarding_case)


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
@roles_required(*VIEW)
def case(case_id):
    case = db.session.get(OnboardingCase, case_id) or abort(404)
    if request.method == "POST":
        if not onboarding.can_edit(current_user):
            abort(403)
        action = request.form.get("action")
        try:
            if action == "employee_number":
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
            return redirect(url_for("onboarding.case", case_id=case.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            case = db.session.get(OnboardingCase, case_id)
    return render_template("onboarding/case.html", case=case, copies=onboarding.signed_copies(case), today=today(),
                           can_edit=onboarding.can_edit(current_user),
                           contract_name=documents.template(
                               documents.CONTRACT_KEYS.get(case.employee.employment_type, "contract_permanent")).name)


@bp.route("/cases/<int:case_id>/contract.pdf")
@roles_required(*EDIT)
def contract(case_id):
    case = db.session.get(OnboardingCase, case_id) or abort(404)
    data = onboarding.contract_pdf(case, current_user)
    db.session.commit()
    return _pdf(data, f"{case.employee.employee_number} contract.pdf", download=bool(request.args.get("download")))


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
                message = "Signature uploaded. It's on every letter and contract from now on."
            elif action == "remove_signature":
                sig = documents.signature_file()
                if sig:
                    audit.record("document.signature_removed", "stored_file", sig.id)
                    files.delete(sig)
                message = "Signature removed."
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
                           signatory=documents.signatory())


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
    contract = tpl.key != "offer_letter"
    sample = {**documents.signatory(), "today": documents.long_date(today()), "salutation": "Mr",
              "name": "Codnell Chabalala", "address": "56 Jorrisen St\nBraamfontein\nJohannesburg\n2001",
              "ref": "OFR-2026-00001", "title": "Systems Analyst", "department": "ICT",
              "reports_to": "Group ICT Manager, Tinashe Chadamoyo", "location": "215 Peter Mokaba Road, Morningside",
              "grade": "Professional / Experienced / Specialists / Mid-Management",
              "employment_type": "Permanent", "employment": "Permanent Employment", "start_date": "01 July 2026",
              "end_date": "30 June 2027" if tpl.key == "contract_contract" else "", "ctc": "R 360 000.00",
              "monthly": "R 30 000.00", "probation": "six (6) months", "conditions": [],
              "expires_on": "24 June 2026", "accepted_by": "", "accepted_on": "", "employee_number": "ICE1037"}
    try:
        title, body = documents._env.from_string(tpl.title).render(**sample), \
            documents._env.from_string(tpl.body).render(**sample)
        return _pdf(documents.pdf(title, body.strip(), ref="ICE1037" if contract else sample["ref"]),
                    f"{tpl.name}.pdf")
    except Exception as exc:  # noqa: BLE001 - show HR Admin what's wrong instead of a server error
        flash(f"The preview couldn't be made: {exc}", "error")
        return redirect(url_for("onboarding.template", template_id=tpl.id))
