"""Shared model helpers: timestamps, dict-style access and encrypted columns."""
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy.types import Text, TypeDecorator

from app.extensions import db
from app.services.dates import now


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)


class MappingMixin:
    """Lets a model be read like a mapping (row["field"]), as ats.py expects."""

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


def snapshot(obj, fields):
    """Plain-dict copy of selected fields, for audit before/after values."""
    out = {}
    for f in fields:
        value = getattr(obj, f, None)
        out[f] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
    return out


def _fernet():
    return Fernet(current_app.config["FERNET_KEY"].encode())


class EncryptedString(TypeDecorator):
    """Text column encrypted at rest with Fernet (key from FERNET_KEY in .env)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return value
        return _fernet().encrypt(str(value).encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            return None
