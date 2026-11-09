"""HTML emails (redesigned 8 Nov 2026, at the user's request, replacing the IGSP copy): a warm grey page, one white
card with the brand header and a three-colour stripe, a small label above the text, a details table, a flat orange
button and a quiet footer (templates/email/layout.html). Applicants (candidate_* keys) see the Icebolethu Group logo;
staff see the ICE People Administration System brand (the sidebar's mark and wordmark).

The wording still comes from the editable notification templates (notifications.DEFAULT_TEMPLATES). `html_for` wraps
a rendered subject and body in the layout: blank lines make paragraphs, "Label: value" lines become a details table,
"- " lines become bullets, and the sign-off ("Kind regards") is set apart. Each template key has a label and a button
(META); a status or outcome shows as a pill. Images travel inside the email (cid:...); the browser preview uses /static.
"""
import os
import re

from flask import current_app, url_for
from markupsafe import Markup, escape
from jinja2 import meta
from jinja2.sandbox import SandboxedEnvironment

STATIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
# The footer of every email (8 Nov 2026, at the user's request): the "we do life with you" banner, the FSP line and
# round social media icons (PNG, from tools/make_email_icons.py; email apps don't show SVG).
SOCIAL = [("Facebook", "https://www.facebook.com/IcebolethuGroup/", "social-facebook"),
          ("LinkedIn", "https://www.linkedin.com/company/icebolethu-group", "social-linkedin"),
          ("Instagram", "https://www.instagram.com/icebogroup", "social-instagram"),
          ("TikTok", "https://www.tiktok.com/@icebogroup", "social-tiktok"),
          ("YouTube", "https://www.youtube.com/channel/UC5h2kXvXAGtSO3aQhak3dLw", "social-youtube")]
WEBSITE = "https://www.icebolethugroup.co.za"
FSP_NUMBER = "FSP45714"

IMAGES = {"logo": ("logo.png", "png"), "mark": ("email/mark.png", "png"),
          "banner": ("email/footer-banner.jpg", "jpeg"),
          **{cid: (f"email/{cid}.png", "png") for _name, _url, cid in SOCIAL}}

# key: (the label above the text, the button label or None for no button).
META = {
    "requisition_status": ("Requisition update", "Open the requisition"),
    "position_status": ("Position update", "Open the position"),
    "approval_requested": ("Approval needed", "Review and decide"),
    "approval_reminder": ("Reminder", "Review and decide"),
    "approval_escalated": ("Escalated to you", "Review and decide"),
    "approval_outcome": ("Approval decision", "See the decision"),
    "delegation_set": ("Delegation", "Open my approvals"),
    "advert_published": ("Advert live", "Open the advert"),
    "advert_closed": ("Advert closed", "Open the advert"),
    "jd_review_due": ("Review due", "Review the job description"),
    "shortlist_review": ("Shortlist to review", "Pick who goes to interview"),
    "shortlist_reviewed": ("Shortlist reviewed", "Send invitations and regrets"),
    "panel_invite": ("Interview panel", "Open interviews to score"),
    "panel_added": ("Interview panel", "Open interviews to score"),
    "panel_scored": ("Scores are in", "See the results"),
    "candidate_application_received": ("Application received", "Check your application status"),
    "candidate_interview_invite": ("Congratulations", "Join the meeting"),     # button only online
    "candidate_regret": ("Application update", "See other vacancies"),
    "budget_overspend": ("Budget alert", "Open the budget"),
    "interview_passed": ("Make an offer", "Prepare the offer"),
    "offer_accepted": ("Offer accepted", "Open the offer"),
    "offer_declined": ("Offer not accepted", "Open the offer"),
    "candidate_offer": ("Congratulations", "Accept or decline the offer"),
    "candidate_offer_accepted": ("Welcome", None),
    "test": ("Test email", "Open ICE People"),
}
APPROVED = {"approved", "approve", "filled", "live", "open", "advertised"}
DECLINED = {"rejected", "reject", "declined", "cancelled", "returned", "abolished"}

# Example values for previews and samples, by placeholder name.
SAMPLE_VALUES = {
    "ref": "REQ-2026-00042", "title": "Funeral Arranger", "status": "Approved", "comment": "Budget confirmed for Q3.",
    "note": "Please bring your ID and certified copies of your qualifications.", "originator": "Precious Naidoo",
    "level": "3", "step": "Finance", "due": "Mon, 9 Nov 2026 16:00", "since": "Wed, 4 Nov 2026 09:15",
    "previous": "Kagiso Molefe", "actor": "Thandiwe Dlamini", "outcome": "approved", "user": "Sipho Ndlovu",
    "start": "10 Nov 2026", "end": "20 Nov 2026", "channels": "Careers site, LinkedIn and PNet",
    "closing": "30 Nov 2026", "failed": "", "applications": "47", "reason": "Closing date reached",
    "sender": "Ayanda Zulu", "count": "6", "reviewer": "Precious Naidoo", "selected": "4", "not_selected": "2",
    "role": "Line Manager",
    "slots": "- 10 Nov 2026 10:00: Thandeka Mokoena (Head office boardroom). "
             "Scorecard: https://hr.icebolethu.co.za/recruitment/interviews/12\n"
             "- 10 Nov 2026 11:00: Lwazi Mthethwa (Microsoft Teams). "
             "Scorecard: https://hr.icebolethu.co.za/recruitment/interviews/13", "questions": "5",
    "name": "Thandeka Mokoena", "average": "82.5", "date": "Tuesday, 10 November 2026", "time": "10:00",
    "venue": "Head office boardroom, 12 Example Road, Durban", "cost_centre": "SAL-100 Sales Durban",
    "pct": "91", "fy": "2026/27", "used": "R 1 820 000", "amount": "R 2 000 000",
    "duration": "1 hour", "platform": "Microsoft Teams", "online": True,
    "meeting_link": "https://teams.microsoft.com/meet/311602226638884?p=Example", "meeting_id": "311 602 226 638 884",
    "passcode": "bD6ac2sg", "decided_by": "Precious Naidoo", "employee_number": "ICE1037",
    "expires_on": "Friday, 13 November 2026", "start_date": "1 December 2026",
}
SAMPLE_LINKS = {"candidate_regret": None, "candidate_offer_accepted": None,
                "candidate_offer": "https://careers.icebolethu.co.za/offer/sample",
                "candidate_interview_invite": "https://teams.microsoft.com/meet/311602226638884?p=Example", "candidate_application_received": "/status"}

_LABEL = re.compile(r"^([A-Z][A-Za-z ()/]{1,24}):\s+(.+)$")
_SIGN_OFF = ("kind regards", "regards", "best regards", "warm regards", "yours sincerely", "sincerely")


def _blocks(body):
    """Body text -> [(kind, data)]: ("p", text), ("details", [(label, value)]), ("list", [items]), ("sign", lines)."""
    blocks = []
    for chunk in re.split(r"\n\s*\n", (body or "").strip()):
        lines = [l.rstrip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].strip().lower().rstrip(",") in _SIGN_OFF:
            blocks.append(("sign", lines))
            continue
        para = []                                         # plain lines of the current paragraph
        for line in lines:
            label, bullet = _LABEL.match(line.strip()), line.strip()[:2] in ("- ", "• ")
            kind = "details" if label else "list" if bullet else "p"
            if kind == "p":
                para.append(line.strip())
                continue
            if para:
                blocks.append(("p", " ".join(para)))
                para = []
            item = (label.group(1), label.group(2)) if label else line.strip()[2:]
            if blocks and blocks[-1][0] == kind:
                blocks[-1][1].append(item)
            else:
                blocks.append((kind, [item]))
        if para:
            blocks.append(("p", " ".join(para)))
    return blocks


# Pill colours (background, text): soft tints; green and red only mean approved and declined.
BADGES = {"approved": ("#E6F4EA", "#1E7B34"), "declined": ("#FBE7E9", "#B02A37"), "other": ("#FEF0E6", "#C2410C")}


_URL = re.compile(r"(https?://[^\s<]+[^\s<.,;:!?)])")


def linkify(text):
    """Escape text and make its web links clickable (the Teams joining link in an invitation)."""
    return Markup(_URL.sub(lambda m: f'<a href="{m.group(1)}" target="_blank" style="color:#F26522; '
                                     f'font-weight:600; text-decoration:underline; word-break:break-all;">'
                                     f'{m.group(1)}</a>', str(escape(text))))


def _pill(context):
    for key in ("status", "outcome"):
        value = str(context.get(key) or "").strip()
        if value:
            low = value.lower()
            tone = "approved" if low in APPROVED else "declined" if low in DECLINED else "other"
            bg, fg = BADGES[tone]
            return {"text": value[:1].upper() + value[1:], "bg": bg, "fg": fg}
    return None


def _path(endpoint, **values):
    """url_for that also works outside a request (scheduled jobs and CLI commands send email too)."""
    try:
        return url_for(endpoint, **values)
    except RuntimeError:
        with current_app.test_request_context():
            return url_for(endpoint, **values)


def _absolute(link):
    if not link:
        return None
    if link.startswith("http"):
        return link
    return (current_app.config.get("PUBLIC_BASE_URL") or "http://127.0.0.1:5000").rstrip("/") + link


def html_for(key, subject, body, link=None, context=None, web=False):
    """The designed HTML for one email. web=True points images at /static (browser preview) instead of cid:."""
    context = context or {}
    label, button = META.get(key, ("ICE People", "Open ICE People"))
    candidate = key.startswith("candidate_")
    if key == "candidate_regret":
        link = _path("careers.index")
    elif key == "candidate_application_received":
        link = _path("careers.check_status")
    images = ({name: _path("static", filename=path) for name, (path, _kind) in IMAGES.items()} if web
              else {name: f"cid:{name}" for name in IMAGES})
    preheader = re.sub(r"\s+", " ", body or "").strip()[:140]
    # The Jinja environment directly, not render_template: no request or signed-in user is needed (scheduled jobs).
    return current_app.jinja_env.get_template("email/layout.html").render(
        subject=subject, label=label, blocks=_blocks(body), pill=_pill(context), button=button if link else None,
        social=SOCIAL, linkify=linkify, website=WEBSITE, fsp=FSP_NUMBER,
        link=_absolute(link), candidate=candidate, images=images, preheader=preheader,
        careers=_absolute(_path("careers.index")),
        home=_absolute(_path("dashboards.home")))


def inline_images(html):
    """(cid, bytes, subtype) for each image the HTML uses, to attach as related parts."""
    found = []
    for name, (path, subtype) in IMAGES.items():
        if f"cid:{name}" in html:
            with open(os.path.join(STATIC, path), "rb") as fh:
                found.append((name, fh.read(), subtype))
    return found


def sample(key, subject_tpl, body_tpl):
    """Render a template with example values: (subject, body, link, context)."""
    env = SandboxedEnvironment(autoescape=False)
    names = meta.find_undeclared_variables(env.parse(subject_tpl + "\n" + body_tpl))
    context = {n: SAMPLE_VALUES.get(n, n.replace("_", " ").title()) for n in names}
    link = SAMPLE_LINKS.get(key, "/dashboard")
    return env.from_string(subject_tpl).render(**context), env.from_string(body_tpl).render(**context), link, context


def designed(key, subject, body, link=None, context=None):
    """html_for, or None if the design can't be built: the plain-text email still goes out."""
    try:
        return html_for(key, subject, body, link, context)
    except Exception:  # noqa: BLE001 - never lose an email over its layout
        current_app.logger.exception("Couldn't build the HTML for the %s email", key)
        return None
