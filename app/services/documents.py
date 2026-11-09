"""Offer letters and employment contracts as PDFs (8 Nov 2026, at the user's request; spec IN-009 and OB-004).

The layout follows Icebolethu's current offer letter (the user's example, 8 Nov 2026): the logo and a rule at the top
of page 1, "STRICTLY CONFIDENTIAL", the date and address block, "Dear Mr …", an underlined "RE:" line, numbered
sections, "Yours sincerely" with the signature and the signatory's name and title, an acceptance section on page 2,
and on every page the page number, the contact line (phone, addresses, web) and the patterned orange band
(templates/documents/letter.html; footer images from tools/make_letterhead.py).

The wording is in DocumentTemplate rows that HR Admin edits (Onboarding → Letter and contract templates); the
defaults below are seeded once. A body is text with {{ placeholders }}, laid out by these rules:
- A blank line starts a new block; inside a block each line keeps its own line (an address).
- "# " starts the underlined subject line ("# RE: Conditional employment offer letter").
- A short line with text under it and no full stop is a section heading ("1. Remuneration").
- Lines like "Start date: 1 July 2026" make a two-column table; "- " lines are bullets.
- **text** is bold. "[signature]" is the signature image; "[page break]" starts a new page.
"""
import io
import os
import re

from flask import current_app
from jinja2 import meta
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup, escape

from app.extensions import db
from app.models import DocumentTemplate
from app.services import settings
from app.services.errors import DomainError

_env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
STATIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
SIGNATURE_FILE = "document_signature"

# The contact line at the foot of every page, as on the current letterhead.
LETTERHEAD = {"phones": ["+27 86 000 7580", "+27 82 948 7894"],
              "addresses": ["277 Umbilo Rd, Congela, Durban, 4013", "387 Surrey Av, Ferndale, Randburg, 2194"],
              "web": "www.icebolethugroup.co.za"}

_SIGN_OFF = """Yours sincerely
[signature]
{% if signatory_name %}**{{ signatory_name }}**
{% endif %}**{{ signatory_title }}**"""

_ACCEPT = """[page break]

{% if accepted_on %}{{ name }} accepted this offer online on {{ accepted_on }}.{% else %}If you accept the above \
offer, kindly accept it online using the link in the email that came with this letter by **{{ expires_on }}**.{% endif %}


I, **{{ accepted_by or "________________________________" }}**, accept the {{ employment }} offer of a **{{ title }}** \
within the **{{ department }}** department of **Icebolethu Group** as detailed above.

Start date: {{ start_date }}
Offer reference: {{ ref }}
Accepted online: {{ accepted_on or "________________________" }}"""

_TERMS = """Remuneration
Your total cost to company is **{{ ctc }}** per annum ({{ monthly }} per month), paid monthly in arrears into your \
nominated bank account. It includes your basic salary and all company contributions. Statutory deductions (PAYE, \
UIF and SDL) are made as the law requires.

Hours of work
Your ordinary hours of work are set by company policy for your position and will not exceed 45 hours a week, in \
line with the Basic Conditions of Employment Act (BCEA). Overtime is worked only when agreed and is paid or \
compensated as the BCEA provides.

Leave
You are entitled to annual, sick and family responsibility leave as set out in the BCEA and company leave policy. \
Leave is applied for and recorded on Sage 300 self-service.

Confidentiality and personal information
You must keep the company's and its clients' information confidential during and after your employment. The \
company processes your personal information for employment purposes in line with the Protection of Personal \
Information Act (POPIA).

Policies
You agree to follow the company's policies and procedures, including the code of conduct and the disciplinary \
code, as amended from time to time. They form part of this contract."""

_CONTRACT_SIGN = """Signed for Icebolethu Group
[signature]
{% if signatory_name %}**{{ signatory_name }}**
{% endif %}**{{ signatory_title }}**

[page break]

Employee acceptance

I, **{{ name }}**, accept the terms of this contract.

Employee number: {{ employee_number }}
Signature: ________________________________
Date: ________________________________"""

_CONTRACT_HEAD = """{{ today }}

{% if address %}{{ address }}

{% endif %}Dear {{ salutation }} {{ name }}

"""

# key: (name, title, body)
DEFAULTS = {
    "offer_letter": ("Offer letter", "Conditional employment offer letter", """{{ today }}

{% if address %}{{ address }}

{% endif %}Dear {{ salutation }} {{ name }}

# RE: Conditional employment offer letter

We are pleased to offer you {{ employment }} in the position of **{{ title }}** within the **{{ department }}** \
department of Icebolethu Group with effect from **{{ start_date }}**{% if end_date %} until **{{ end_date }}**\
{% endif %}.{% if location %} You will be based at **{{ location }}**{% if reports_to %} and you will report \
directly to the **{{ reports_to }}**{% endif %}.{% elif reports_to %} You will report directly to the \
**{{ reports_to }}**.{% endif %}

Your appointment is subject to your satisfying our normal joining formalities, which include but are not limited to \
satisfactory qualification, criminal, reference and credit checks, and you are also expected to complete all \
relevant Icebolethu Group joining formalities within five (5) working days of assuming duty.
{% if conditions %}

It is also subject to:
{% for c in conditions %}
- {{ c }}
{% endfor %}
{% endif %}

1. Remuneration
1.1 Your total remuneration package, on a total cost to company basis, shall be **{{ ctc }}** per annum, broken \
down monthly as follows:

1.1.1 Basic salary: **{{ monthly }}** per month
{% if probation %}

1.2 Your appointment is subject to you successfully completing a {{ probation }} probation period.
{% endif %}

If you are happy with the offer, please accept it online by **{{ expires_on }}** using the link in the email that \
came with this letter. Upon receipt of your acceptance, Icebolethu Group will send you a Letter of Appointment with \
full terms and conditions of employment which are in line with the provisions of the Basic Conditions of \
Employment Act (BCEA).

""" + _SIGN_OFF + "\n\n" + _ACCEPT),
    "contract_permanent": ("Contract: permanent", "Letter of appointment (permanent)", _CONTRACT_HEAD + """\
# RE: Letter of appointment: permanent employment

Further to your acceptance of our offer, Icebolethu Group ("the company") appoints you to the position of \
**{{ title }}** within the **{{ department }}** department on the terms below.

Employee number: {{ employee_number }}
Position: {{ title }}
Department: {{ department }}
Reports to: {{ reports_to }}
Occupational level: {{ grade }}
Start date: {{ start_date }}

1. Commencement and probation
Your employment starts on **{{ start_date }}** and is permanent.{% if probation %} It is subject to you \
successfully completing a {{ probation }} probation period, during which your performance and suitability are \
assessed.{% endif %}

""" + _TERMS + """

Termination
Either party may end this contract by giving written notice as required by section 37 of the BCEA, or the longer \
period set by company policy for your position.

""" + _CONTRACT_SIGN),
    "contract_contract": ("Contract: fixed-term", "Letter of appointment (fixed-term)", _CONTRACT_HEAD + """\
# RE: Letter of appointment: fixed-term employment

Further to your acceptance of our offer, Icebolethu Group ("the company") appoints you to the position of \
**{{ title }}** within the **{{ department }}** department for a fixed term, on the terms below.

Employee number: {{ employee_number }}
Position: {{ title }}
Department: {{ department }}
Reports to: {{ reports_to }}
Start date: {{ start_date }}
End date: {{ end_date }}

1. Duration
Your employment starts on **{{ start_date }}** and ends automatically on **{{ end_date }}**, unless it is ended \
earlier under this contract or extended in writing by both parties. This contract creates no expectation of renewal \
or of permanent employment.

""" + _TERMS + """

Termination
Either party may end this contract before its end date by giving written notice as required by section 37 of the \
BCEA.

""" + _CONTRACT_SIGN),
    "contract_casual": ("Contract: casual", "Letter of appointment (casual)", _CONTRACT_HEAD + """\
# RE: Letter of appointment: casual employment

Further to your acceptance of our offer, Icebolethu Group ("the company") appoints you as a casual employee in the \
position of **{{ title }}** within the **{{ department }}** department, on the terms below.

Employee number: {{ employee_number }}
Position: {{ title }}
Department: {{ department }}
Reports to: {{ reports_to }}
Start date: {{ start_date }}

1. Nature of employment
You are employed on a casual basis and will work when the company needs you. The company doesn't guarantee a \
minimum number of shifts or hours, and you may decline a shift offered to you.

""" + _TERMS + """

Termination
Either party may end this contract by giving written notice as required by section 37 of the BCEA.

""" + _CONTRACT_SIGN),
}
CONTRACT_KEYS = {"Permanent": "contract_permanent", "Contract": "contract_contract", "Casual": "contract_casual"}

# Placeholders HR Admin may use, with what they are (shown on the template form).
PLACEHOLDERS = {
    "today": "Today's date", "salutation": "Mr, Ms, Mrs, Dr or Prof (chosen on the offer)",
    "name": "The candidate's or employee's full name", "address": "The candidate's postal address (several lines)",
    "ref": "The offer reference", "title": "Position title", "department": "Department",
    "reports_to": "Reports to: the manager's position and name", "location": "Where they will be based",
    "grade": "Occupational level", "employment_type": "Permanent, Contract or Casual",
    "employment": "\"Permanent Employment\", \"Fixed-term Employment\" or \"Casual Employment\"",
    "start_date": "Start date", "end_date": "End date (Contract only)", "ctc": "Annual cost to company",
    "monthly": "Monthly cost to company", "probation": "The probation period in words, e.g. six (6) months",
    "conditions": "The offer's extra conditions (a list)", "expires_on": "Last day to accept the offer",
    "signatory_name": "Who signs (Letter settings)", "signatory_title": "Their job title (Letter settings)",
    "accepted_by": "The candidate's name once they accept online", "accepted_on": "When they accepted online",
    "employee_number": "Employee number (contracts)",
}
NUMBERS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]


def long_date(value):
    """01 July 2026, as on the current offer letter."""
    return f"{value.day:02d} {value:%B %Y}" if value else ""


def long_datetime(value):
    return f"{value.day:02d} {value:%B %Y} at {value:%H:%M}" if value else ""


def probation_words(months):
    """6 → "six (6) months", as in the current letter."""
    if not months:
        return ""
    word = NUMBERS[months] if 0 < months < len(NUMBERS) else str(months)
    return f"{word} ({months}) month{'s' if months != 1 else ''}"


def signatory():
    return {"signatory_name": settings.get("letter_signatory_name").strip(),
            "signatory_title": settings.get("letter_signatory_title").strip() or "Group Human Resources Manager"}


def signature_file():
    from app.services import files
    copies = files.files_for(SIGNATURE_FILE, None)
    return copies[-1] if copies else None              # the latest upload


def ensure_documents():
    for key, (name, title, body) in DEFAULTS.items():
        if not DocumentTemplate.query.filter_by(key=key).first():
            db.session.add(DocumentTemplate(key=key, name=name, title=title, body=body))


def template(key):
    tpl = DocumentTemplate.query.filter_by(key=key).first()
    if tpl is None:
        name, title, body = DEFAULTS[key]
        tpl = DocumentTemplate(key=key, name=name, title=title, body=body)
    return tpl


def check_template(title, body):
    """Errors in a template HR Admin typed: bad syntax or unknown placeholders."""
    try:
        names = meta.find_undeclared_variables(_env.parse(f"{title}\n{body}"))
    except Exception as exc:  # noqa: BLE001 - jinja's TemplateSyntaxError and friends
        raise DomainError(f"The template has a mistake: {exc}") from exc
    unknown = sorted(n for n in names if n not in PLACEHOLDERS and n != "c")
    if unknown:
        raise DomainError(f"Unknown placeholder(s): {', '.join(unknown)}.")


def render(key, context):
    tpl = template(key)
    context = {**signatory(), **context}
    return _env.from_string(tpl.title).render(**context), _env.from_string(tpl.body).render(**context).strip()


# ------------------------------------------------------------------ layout

_LABEL = re.compile(r"^([A-Z][A-Za-z ()/]{1,30}):\s+(.+)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def rich(text):
    """Escape, then **bold**."""
    return Markup(_BOLD.sub(r"<b>\1</b>", str(escape(text))))


def _is_heading(first, rest):
    """A short line over a paragraph ("1. Remuneration"). Not an address block, whose lines are all short."""
    return (rest and len(" ".join(rest)) > 60 and len(first) <= 60 and not first.endswith((".", ":", ",")) and ":" not in first
            and not first.startswith(("Dear ", "I, ", "**")) and first.lower() not in ("yours sincerely",
                                                                                        "yours faithfully",
                                                                                        "kind regards"))


def blocks(body):
    """Body text → [(kind, data)]: title, heading, p (lines), table [(label, value)], list, signature, pagebreak."""
    out = []
    for chunk in re.split(r"\n\s*\n", (body or "").strip()):
        lines = [l.rstrip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if first == "[page break]":
            out.append(("pagebreak", None))
            lines = lines[1:]
            if not lines:
                continue
            first = lines[0].strip()
        if first.startswith("# "):
            out.append(("title", first[2:].strip().upper()))
            lines = lines[1:]
        elif _is_heading(first, lines[1:]):
            out.append(("heading", first.upper() if re.match(r"^\d+\.\s", first) else first))
            lines = lines[1:]
        para = []

        def flush():
            if para:
                out.append(("p", list(para)))
                para.clear()
        for line in lines:
            text = line.strip()
            label = _LABEL.match(text)
            if text == "[signature]":
                flush()
                out.append(("signature", None))
            elif label:
                flush()
                if out and out[-1][0] == "table":
                    out[-1][1].append(label.groups())
                else:
                    out.append(("table", [label.groups()]))
            elif text.startswith(("- ", "• ")):
                flush()
                if out and out[-1][0] == "list":
                    out[-1][1].append(text[2:])
                else:
                    out.append(("list", [text[2:]]))
            else:
                para.append(text)
        flush()
    return out


def pdf(title, body, ref=None):
    """The document as PDF bytes, on the letterhead."""
    from xhtml2pdf import pisa

    from app.services import files
    sig = signature_file()
    html = current_app.jinja_env.get_template("documents/letter.html").render(
        title=title, blocks=blocks(body), ref=ref, rich=rich, letterhead=LETTERHEAD,
        logo=os.path.join(STATIC, "logo.png"), images=os.path.join(STATIC, "documents"),
        signature=files.path_for(sig) if sig else None)
    out = io.BytesIO()
    result = pisa.CreatePDF(html, dest=out, encoding="utf-8")
    if result.err:
        raise DomainError("The PDF couldn't be made. Check the template.")
    return out.getvalue()
