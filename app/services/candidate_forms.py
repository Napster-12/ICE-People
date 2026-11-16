"""Forms candidates download, complete and upload (16 Nov 2026, at the user's request), and the POPIA consent the
candidate gives online before the background checks.

The blank forms ship in static/forms/ (Icebolethu's and its providers' own PDFs). HR Admin can replace any of them
under Onboarding → Offer letter and documents (a StoredFile with entity type "candidate_form" and the form's id; the
latest upload wins). Third-party forms (MIE, Liberty) stay exactly as issued: Liberty treats a modified form as
invalid, and the Disclosure is sworn before a Commissioner of Oaths.
"""
import os

from app.services import audit, documents, files
from app.services.errors import DomainError

ENTITY = "candidate_form"
TYPES = {".pdf"}

# key: (id, title, file in static/forms, what the candidate does with it)
FORMS = {
    "mie": (1, "MIE Personal Credential Disclosure Form", "mie-consent.pdf",
            "Complete the candidate section, sign and date it, then upload it with your consent."),
    "code_of_conduct": (2, "Icebolethu Group Employee Code of Conduct", "code-of-conduct.pdf",
                        "Read it before accepting the offer."),
    "disclosure": (3, "Business and Financial Disclosure Form", "business-financial-disclosure.pdf",
                   "Complete it, swear or affirm it before a Commissioner of Oaths, then upload the signed copy."),
    "liberty": (4, "Liberty Nomination of Beneficiary Form", "liberty-nomination-of-beneficiary.pdf",
                "Complete and sign it in black ink without changing the form, then upload it."),
}


def _check(key):
    if key not in FORMS:
        raise DomainError("Unknown form.")
    return FORMS[key]


def title(key):
    return _check(key)[1]


def uploaded(key):
    """HR Admin's replacement, if any (newest)."""
    found = files.files_for(ENTITY, _check(key)[0])
    return found[-1] if found else None


def data(key):
    """The blank form's bytes: HR Admin's replacement, else the one shipped with the system."""
    replacement = uploaded(key)
    if replacement is not None:
        return files.read(replacement)
    with open(os.path.join(documents.STATIC, "forms", _check(key)[2]), "rb") as f:
        return f.read()


def filename(key):
    return _check(key)[2]


def replace(key, upload, user):
    if upload is None or not upload.filename:
        raise DomainError("Choose the PDF to upload.")
    stored = files.save_upload(upload, ENTITY, _check(key)[0], user=user, allowed=TYPES)
    audit.record("candidate_form.replaced", "stored_file", stored.id, after={"form": title(key),
                 "file": stored.original_name}, user=user)
    return stored


def listing():
    return [{"key": k, "title": t, "help": h, "uploaded": uploaded(k)} for k, (_i, t, _f, h) in FORMS.items()]


# ------------------------------------------------------------------ the POPIA consent (Icebolethu's form, online)

POPIA_INTRO = ("The purpose of the Protection of Personal Information Act, 2013 (Act No. 4 of 2013) (POPIA) is to "
               "protect the personal information of individuals and businesses and to give effect to their right "
               "of privacy as provided for in Section 14 of the Constitution of the Republic of South Africa, 1996. "
               "By giving this consent, you consent to your personal information being processed by the Icebolethu "
               "Group. Consent is effective immediately and remains effective until it is withdrawn.")

POPIA_CLAUSES = [
    "I, {name}, a natural person (the \"Data Subject\") with ID number {id_number}, hereby give my consent to the "
    "Icebolethu Group (\"IG\", the \"Responsible Party\") to collect, process and distribute my personal information "
    "where IG is legally required to do so, as my employer.",
    "I understand my right to privacy and the right to have my personal information processed in accordance with "
    "the conditions for the lawful processing of personal information.",
    "I confirm that by voluntarily submitting any personal information to IG, in any form, I give an indefinite, "
    "unconditional and specific consent for IG to share such personal information (my ID copy) with third parties, "
    "including the South African Police Service, the FIC / FICA or supervisory bodies, the State Security Agency, "
    "credit bureaus and other agencies, for the purposes of a criminal record check, a financial record check, and "
    "verifying my academic qualifications and employment history.",
    "I declare that all my personal information supplied to IG is accurate, up to date, not misleading and complete "
    "in all respects, that it will be held and/or stored securely for the purpose for which it was collected, and "
    "that I will immediately advise IG of any changes to my personal information.",
    "I understand that I have the right to request that my personal information be corrected or deleted if it is "
    "inaccurate, irrelevant, excessive, out of date, incomplete, misleading or obtained unlawfully, or that the "
    "personal information or record be destroyed or deleted if the Responsible Party is no longer authorised to "
    "retain it.",
    "By giving this consent, I accept and understand the IG Code of Ethics policy and any other policies that are "
    "applicable to IG.",
]


def popia_clauses(name="……………………", id_number="……………………"):
    return [c.format(name=name, id_number=id_number) for c in POPIA_CLAUSES]


def popia_pdf(screening):
    """The consent as given online, on the letterhead, kept with the checks."""
    when = screening.consent_at
    body = "\n\n".join(
        ["# Consent form for collection of personal information",
         "Consent to process personal information in terms of Section 18 of the Protection of Personal Information "
         "Act, 2013 (Act No. 4 of 2013).", POPIA_INTRO]
        + [f"{i}. {c}" for i, c in enumerate(popia_clauses(screening.consent_name, screening.consent_id_number), 1)]
        + [f"Signed electronically at {screening.consent_place} on {documents.long_datetime(when)}, by typing "
           f"their full name (application {screening.application.reference}).",
           f"Data subject: {screening.consent_name}\nID number: {screening.consent_id_number}\n"
           f"IP address: {screening.consent_ip or 'not recorded'}"])
    return documents.pdf("POPIA consent", body, ref=screening.application.reference)
