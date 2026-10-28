"""Platform tables: calendar, settings, reference sequences, audit, notifications, files, integrations."""
from sqlalchemy import event

from app.extensions import db
from app.services.dates import now


class PublicHoliday(db.Model):
    __tablename__ = "public_holidays"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)


class Setting(db.Model):
    """Configurable values (SLAs, thresholds...) editable by HR Admin."""
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    label = db.Column(db.String(160))
    help = db.Column(db.String(255))


class RefSequence(db.Model):
    __tablename__ = "ref_sequences"
    prefix = db.Column(db.String(10), primary_key=True)
    year = db.Column(db.Integer, primary_key=True)
    last = db.Column(db.Integer, nullable=False, default=0)


class AuditLog(db.Model):
    """Append-only. There are no update or delete paths for these rows."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=now, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    username = db.Column(db.String(80))
    ip = db.Column(db.String(64))
    action = db.Column(db.String(60), nullable=False, index=True)
    entity = db.Column(db.String(60), index=True)
    entity_id = db.Column(db.String(40), index=True)
    before = db.Column(db.JSON)
    after = db.Column(db.JSON)
    detail = db.Column(db.String(500))


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditLog, "before_update")
def _no_audit_update(*_args):
    raise AuditImmutableError("Audit log entries cannot be changed.")


@event.listens_for(AuditLog, "before_delete")
def _no_audit_delete(*_args):
    raise AuditImmutableError("Audit log entries cannot be deleted.")


class NotificationTemplate(db.Model):
    __tablename__ = "notification_templates"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    link = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    read_at = db.Column(db.DateTime, index=True)

    user = db.relationship("User")


class StoredFile(db.Model):
    """An uploaded file kept outside /static under a random name."""
    __tablename__ = "stored_files"
    id = db.Column(db.Integer, primary_key=True)
    stored_name = db.Column(db.String(80), unique=True, nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(120), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    entity_id = db.Column(db.Integer, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    uploaded_by = db.relationship("User")


class IntegrationLog(db.Model):
    __tablename__ = "integration_log"
    id = db.Column(db.Integer, primary_key=True)
    system = db.Column(db.String(40), nullable=False, index=True)
    method = db.Column(db.String(60), nullable=False)
    request = db.Column(db.JSON)
    response = db.Column(db.JSON)
    success = db.Column(db.Boolean, nullable=False, index=True)
    attempt = db.Column(db.Integer, nullable=False, default=1)
    error = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
