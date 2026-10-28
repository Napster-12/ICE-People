"""In-app notifications plus email through the email adapter. Templates are editable by HR Admin."""
import logging

from jinja2.sandbox import SandboxedEnvironment

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Notification, NotificationTemplate, Role, User

log = logging.getLogger(__name__)
_env = SandboxedEnvironment(autoescape=False)

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
            try:
                get_adapter("email").send_email(user.email, subject, body)
            except IntegrationError as exc:
                log.error("Email to %s failed: %s", user.email, exc)
    return created


def users_with_role(role_name):
    return User.query.filter(User.active.is_(True), User.roles.any(Role.name == role_name)).all()


def unread_count(user):
    return Notification.query.filter_by(user_id=user.id, read_at=None).count()
