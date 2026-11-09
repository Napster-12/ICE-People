"""In-app notifications plus email through the email adapter. Templates are editable by HR Admin."""
import logging

from jinja2.sandbox import SandboxedEnvironment

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Notification, NotificationTemplate, Role, User

log = logging.getLogger(__name__)
_env = SandboxedEnvironment(autoescape=False)

INTERVIEW_INVITE_BODY = """Dear {{ name }}

Congratulations! Your application for the {{ title }} position (reference {{ ref }}) has been successful, and we \
are pleased to invite you to an interview.

Kindly take note of the interview details below:

Position: {{ title }}
Date: {{ date }}
Time: {{ time }}
{% if duration %}Duration: About {{ duration }}
{% endif %}{% if online %}Platform: {{ platform }} (see the joining details below){% else %}Venue: {{ venue }}{% endif %}

{% if online %}{{ platform }} meeting
Join: {{ meeting_link }}
{% if meeting_id %}Meeting ID: {{ meeting_id }}
{% endif %}{% if passcode %}Passcode: {{ passcode }}{% endif %}

Please join 5 minutes early from a quiet place, and test your camera, microphone and internet connection \
beforehand. Have your ID ready to show the panel.{% else %}Please arrive 15 minutes early and bring your ID and \
certified copies of your qualifications.{% endif %}{% if note %}

{{ note }}{% endif %}

Please confirm your attendance by replying to this email. If you can't make this time, let us know as soon as \
possible.

Good luck!

Kind regards
Icebolethu Group Human Resources"""

# key: (name, subject, body). Seeded into NotificationTemplate; HR Admin edits them there.
DEFAULT_TEMPLATES = {
    "requisition_status": ("Requisition status changed",
                           "{{ ref }}: {{ title }} is now {{ status }}",
                           "Requisition {{ ref }} ({{ title }}) moved to {{ status }}.{% if comment %}\n\nComment: {{ comment }}{% endif %}"),
    "position_status": ("Position status changed",
                        "{{ ref }}: {{ title }} is now {{ status }}",
                        "Position {{ ref }} ({{ title }}) is now {{ status }}.{% if note %}\n\n{{ note }}{% endif %}"),
    "approval_requested": ("Approval requested",
                           "Approval needed: {{ ref }} {{ title }}",
                           "{{ originator }} needs your approval for {{ ref }} ({{ title }}) at level {{ level }} – {{ step }}.\nPlease respond by {{ due }}."),
    "approval_reminder": ("Approval reminder",
                          "Reminder: {{ ref }} is waiting for you",
                          "{{ ref }} ({{ title }}) has been waiting for your approval since {{ since }}. It is due {{ due }}."),
    "approval_escalated": ("Approval escalated",
                           "Escalated: {{ ref }} passed its SLA",
                           "{{ ref }} ({{ title }}) passed its approval SLA with {{ previous }} and has been escalated to you."),
    "approval_outcome": ("Approval outcome for the originator",
                         "{{ ref }} was {{ outcome }}",
                         "{{ actor }} {{ outcome }} {{ ref }} ({{ title }}) at level {{ level }}.\n\nComment: {{ comment }}"),
    "delegation_set": ("Delegation set",
                       "You are a delegate for {{ user }}",
                       "{{ user }} has delegated approvals to you from {{ start }} to {{ end }}."),
    "advert_published": ("Advert published",
                         "Advert live: {{ ref }} {{ title }}",
                         "Advert {{ ref }} ({{ title }}) is live on {{ channels }} until {{ closing }}.{% if failed %}\n\nCouldn't publish to: {{ failed }}. Check the integration log.{% endif %}"),
    "advert_closed": ("Advert closed",
                      "Advert closed: {{ ref }} {{ title }}",
                      "Advert {{ ref }} ({{ title }}) has closed with {{ applications }} application(s).\n\nReason: {{ reason }}"),
    "jd_review_due": ("Job description review due",
                      "JD review due: {{ title }}",
                      "The job description for {{ title }} is due for its annual review on {{ due }}."),
    "shortlist_review": ("Shortlist sent to the Department Manager",
                         "Shortlist to review: {{ ref }} {{ title }}",
                         "{{ sender }} sent you {{ count }} shortlisted applicant(s) for {{ ref }} ({{ title }}).\n"
                         "Choose who goes to interview."),
    "shortlist_reviewed": ("Department Manager reviewed the shortlist",
                           "Shortlist reviewed: {{ ref }} {{ title }}",
                           "{{ reviewer }} picked {{ selected }} applicant(s) for interview for {{ ref }} ({{ title }}); "
                           "{{ not_selected }} were not selected.{% if comment %}\n\nComment: {{ comment }}{% endif %}\n\n"
                           "{% if questions %}They typed {{ questions }} interview question(s) for the panel; you can "
                           "edit them on the interview panel page.\n\n{% endif %}"
                           "You can now send the interview invitations and regret letters."),
    "panel_invite": ("Interview panel invitation",
                     "Interview panel: {{ ref }} {{ title }}",
                     "{{ sender }} has invited you to the interview panel for {{ ref }} ({{ title }}) as {{ role }}.\n\n"
                     "Interviews:\n{{ slots }}\n\nOpen each candidate's scorecard link at the time of their "
                     "interview: it opens when the interview starts. Score each interview question from 1 to 5 and "
                     "add a comment. Calendar invites follow for each interview."),
    "panel_added": ("Added to an interview panel",
                    "You're on the interview panel: {{ ref }} {{ title }}",
                    "{{ sender }} has added you to the interview panel for {{ ref }} ({{ title }}).\n\n"
                    "HR will send you the interview dates and calendar invites. You'll then see each candidate "
                    "and their CV under Interviews to score, and score them after their interview."),
    "panel_scored": ("Interview panel finished scoring a candidate",
                     "Panel scores in: {{ name }} for {{ title }}",
                     "The whole interview panel has scored {{ name }} for {{ title }}. Combined score: {{ average }}%."),
    "candidate_application_received": ("Applicant: application received",
                                       "We've received your application{% if title %} for {{ title }}{% endif %}",
                                       "Dear {{ name }}\n\nThank you for applying{% if title %} for {{ title }}"
                                       "{% else %} to join our talent pool{% endif %} at Icebolethu Group. We have "
                                       "received your application and CV.\n\nReference: {{ ref }}\n"
                                       "{% if title %}Position: {{ title }}\n{% endif %}Received: {{ date }}\n\n"
                                       "Please keep your reference number. You can use it with your email address "
                                       "to check the status of your application on our careers site.\n\n"
                                       "{% if title %}If you are shortlisted, we will contact you about the next "
                                       "steps. {% endif %}Your CV stays in our talent pool, so we may also contact "
                                       "you about other suitable positions.\n\nKind regards\n"
                                       "Icebolethu Group Human Resources"),
    # Detailed and congratulatory (8 Nov 2026, at the user's request), with the platform and joining details.
    "candidate_interview_invite": ("Applicant: interview invitation",
                                   "Congratulations! Interview invitation: {{ title }} at Icebolethu Group",
                                   INTERVIEW_INVITE_BODY),
    "candidate_regret": ("Applicant: regret",
                         "Your application for {{ title }} at Icebolethu Group",
                         "Dear {{ name }}\n\nThank you for applying for {{ title }} (reference {{ ref }}) and for "
                         "your interest in Icebolethu Group. After careful consideration, we regret that your "
                         "application was not successful this time.{% if note %}\n\n{{ note }}{% endif %}\n\n"
                         "Your CV stays in our talent pool, and we may contact you when a matching position opens."
                         "\n\nKind regards\nIcebolethu Group Human Resources"),
    # Offers and onboarding (8 Nov 2026): HR Admin owns them.
    "interview_passed": ("Candidate passed the interview (to HR Admin)",
                             "Make an offer: {{ name }} passed the interview for {{ title }}",
                             "{{ decided_by }} marked {{ name }} successful after the interview for {{ title }}.\n\n"
                             "Candidate: {{ name }}\nApplication: {{ ref }}\nPanel score: {{ average }}%"
                             "{% if comment %}\nComment: {{ comment }}{% endif %}\n\n"
                             "Please prepare and send the offer letter."),
    "offer_accepted": ("Offer accepted (to HR Admin)",
                       "Offer accepted: {{ name }} for {{ title }}",
                       "{{ name }} accepted offer {{ ref }} for {{ title }}.\n\nStart date: {{ start_date }}\n"
                       "Employee number: {{ employee_number }}\n\nAn onboarding case has been opened. Please "
                       "check the employee number, then prepare the contract. The other applicants for this "
                       "advert are marked Not selected; send them the regret letter from the job's messages page."),
    "offer_declined": ("Offer declined or expired (to HR Admin)",
                       "Offer {{ outcome }}: {{ name }} for {{ title }}",
                       "Offer {{ ref }} to {{ name }} for {{ title }} was {{ outcome }}.\n\nReason: {{ reason }}\n\n"
                       "You can mark the next-ranked candidate successful on the interview panel, or re-advertise."),
    "candidate_offer": ("Applicant: offer of employment",
                        "Congratulations! Your offer of employment: {{ title }} at Icebolethu Group",
                        "Dear {{ name }}\n\nCongratulations! We are delighted to offer you the position of "
                        "{{ title }} at Icebolethu Group. Your offer letter is attached.\n\n"
                        "Offer reference: {{ ref }}\nPosition: {{ title }}\nStart date: {{ start_date }}\n"
                        "Reply by: {{ expires_on }}\n\nPlease read the letter carefully, then use the button below "
                        "to accept or decline the offer by {{ expires_on }}. If you have any questions, reply to "
                        "this email.\n\nKind regards\nIcebolethu Group Human Resources"),
    "candidate_offer_accepted": ("Applicant: offer accepted, welcome",
                                 "Welcome to Icebolethu Group, {{ name }}!",
                                 "Dear {{ name }}\n\nThank you for accepting our offer for the {{ title }} "
                                 "position. We are excited to welcome you to the team.\n\nPosition: {{ title }}\n"
                                 "Start date: {{ start_date }}\n\nOur HR team will contact you shortly about your "
                                 "employment contract and the documents we need before your first day.\n\n"
                                 "Kind regards\nIcebolethu Group Human Resources"),
    "budget_overspend": ("Budget overspend alert",
                         "Budget alert: {{ cost_centre }} at {{ pct }}%",
                         "Cost centre {{ cost_centre }} has committed and consumed {{ pct }}% of its {{ fy }} budget ({{ used }} of {{ amount }})."),
}


def ensure_templates():
    for key, (name, subject, body) in DEFAULT_TEMPLATES.items():
        if not NotificationTemplate.query.filter_by(key=key).first():
            db.session.add(NotificationTemplate(key=key, name=name, subject=subject, body=body))


def render(key, context):
    tpl = NotificationTemplate.query.filter_by(key=key).first()
    if tpl is None:
        name, subject, body = DEFAULT_TEMPLATES[key]
    else:
        subject, body = tpl.subject, tpl.body
    return _env.from_string(subject).render(**context), _env.from_string(body).render(**context)


def notify(users, key, link=None, email=True, **context):
    """Create an in-app notification (and an email) for each user."""
    if isinstance(users, User):
        users = [users]
    seen = set()
    created = []
    subject, body = render(key, context)
    for user in users:
        if user is None or user.id in seen:
            continue
        seen.add(user.id)
        note = Notification(user_id=user.id, title=subject, body=body, link=link)
        db.session.add(note)
        created.append(note)
        if email and user.email:
            from app.services.emails import designed
            try:
                get_adapter("email").send_email(user.email, subject, body,
                                                html=designed(key, subject, body, link, context))
            except IntegrationError as exc:
                log.error("Email to %s failed: %s", user.email, exc)
    return created


def users_with_role(role_name):
    return User.query.filter(User.active.is_(True), User.roles.any(Role.name == role_name)).all()


def unread_count(user):
    return Notification.query.filter_by(user_id=user.id, read_at=None).count()
