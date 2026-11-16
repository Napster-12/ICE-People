"""Every document on file for an employee, gathered for the employee record (16 Nov 2026, at the user's request).

They come from wherever they were collected: the application (CV and documents), the background checks (consent
and reports), the offer (the letter as sent and as accepted), the onboarding case (the candidate's documents and the
signed contract), the new starter pack (the uploaded forms and the Take-On form) and the asset register (signed
allocation forms). Each viewer sees only the files their role may open (files.can_download), so nothing new is
exposed; the Take-On form is a generated PDF that follows the onboarding case's access.
"""
from flask import url_for

from app.services import files

VIEWABLE = {"application/pdf", "image/png", "image/jpeg"}     # open in the on-page viewer; others download
GROUPS = ["Employment", "Onboarding documents", "New starter pack", "Application", "Background checks", "Assets"]


def _clean(name):
    """Stored names are made safe ("ID_copy_-_id.pdf"): show them as typed ("ID copy - id.pdf")."""
    return (name or "").replace("_-_", " - ").replace("_", " ")


def collect(employee, user):
    """[(group, [{"label", "file", "when", "url"}])] for the groups that have something the user may open."""
    from app.services import careers, onboarding, screening, starter_pack
    groups = {g: [] for g in GROUPS}

    def add(group, label, stored):
        if stored is not None and files.can_download(user, stored):
            groups[group].append({"label": label, "file": _clean(stored.original_name), "when": stored.created_at,
                                  "url": url_for("portal.download", file_id=stored.id),
                                  "viewable": stored.content_type in VIEWABLE})

    for case in employee.onboarding_cases:
        offer = case.offer
        if offer is not None:
            add("Employment", f"Offer letter {offer.reference} (as sent)", offer.letter_file)
            add("Employment", f"Offer letter {offer.reference} (as accepted)", offer.accepted_file)
        for stored in onboarding.signed_copies(case):
            add("Employment", "Signed employment contract", stored)
        for stored in onboarding.case_documents(case):
            label = _clean(stored.original_name).split(" - ")[0]
            add("Onboarding documents", label, stored)
        pack = case.pack
        if pack is not None:
            for key, stored in starter_pack.uploaded(pack).items():
                add("New starter pack", starter_pack.DOC_LABELS.get(key, key).split(" (")[0], stored)
            if pack.data and onboarding.can_view_case(user, case):
                groups["New starter pack"].insert(0, {
                    "label": "New Hire Take-On form", "file": f"{case.reference} take-on form.pdf",
                    "when": pack.submitted_at, "url": url_for("onboarding.takeon_pdf", case_id=case.id),
                    "viewable": True})
        application = case.application
        if application is not None:
            cand = application.candidate
            add("Application", "CV", cand.cv_file)
            for name, stored in careers.candidate_documents(cand):
                add("Application", name, stored)
            record = application.screening
            if record is not None:
                for stored in screening.consent_files(record):
                    label = "POPIA consent" if stored.original_name.startswith("POPIA") else "MIE consent form"
                    add("Background checks", label, stored)
                for check in record.checks:
                    for stored in screening.reports(check)[:1]:
                        add("Background checks", f"{check.name} report ({check.status.lower()})", stored)
    for asset in employee.assets:
        found = files.files_for("asset_allocation", asset.id)
        if found:
            add("Assets", f"Asset allocation form: {asset.asset_tag}", found[-1])
    return [(g, groups[g]) for g in GROUPS if groups[g]]
