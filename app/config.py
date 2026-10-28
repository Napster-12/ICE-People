"""Configuration. Secrets come only from the environment (.env)."""
import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

MOCK_INTEGRATIONS = {
    "payroll": "app.integrations.payroll:MockPayroll",
    "erp": "app.integrations.erp:MockERP",
    "directory": "app.integrations.directory:MockDirectory",
    "lms": "app.integrations.lms:MockLMS",
    "job_portals": "app.integrations.job_portals:MockJobPortals",
    "screening": "app.integrations.screening:MockScreening",
    "email": "app.integrations.email_calendar:MockEmailCalendar",
    "esign": "app.integrations.esign:MockESignature",
    "dms": "app.integrations.dms:MockDocumentStore",
    "orgchart": "app.integrations.orgchart:MockOrgChart",
    "leave": "app.integrations.leave:MockLeaveCalendar",
}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    FERNET_KEY = os.environ.get("FERNET_KEY")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(INSTANCE_DIR, "hr.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or os.path.join(INSTANCE_DIR, "uploads")
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024          # per file
    MAX_CONTENT_LENGTH = 30 * 1024 * 1024        # per request (several attachments)
    ALLOWED_UPLOADS = {".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png"}

    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)   # idle timeout
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    TIMEZONE = "Africa/Johannesburg"
    BABEL_DEFAULT_LOCALE = "en"
    BABEL_DEFAULT_TIMEZONE = TIMEZONE

    INTEGRATIONS = dict(MOCK_INTEGRATIONS)
    INTEGRATION_RETRIES = int(os.environ.get("INTEGRATION_RETRIES", 2))

    LEGACY_DB = os.environ.get("LEGACY_DB") or os.path.join(BASE_DIR, "portal.db")
    TEMPLATES_AUTO_RELOAD = True


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE


class ProductionConfig(Config):
    TEMPLATES_AUTO_RELOAD = False


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    FERNET_KEY = "l5yDmgolSwF7VWSjYOUYRiAFWEkCj99y5igIwomesHM="
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    INTEGRATION_RETRIES = 2


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
