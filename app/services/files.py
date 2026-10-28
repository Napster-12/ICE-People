"""Uploads: stored outside /static under random names, type-whitelisted, size-limited,
and permission-checked on every download."""
import hashlib
import mimetypes
import os
import secrets

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import StoredFile
from app.services import audit
from app.services.errors import DomainError

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".txt": "text/plain",
}

# entity_type -> function(user, entity_id) -> bool. Modules register their own rules.
ACCESS_RULES = {}


def register_access(entity_type, rule):
    ACCESS_RULES[entity_type] = rule


def _folder():
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    return folder


def path_for(stored):
    return os.path.join(_folder(), stored.stored_name)


def store_bytes(data, original_name, entity_type, entity_id=None, user=None, allowed=None, check=True):
    name = secure_filename(original_name or "") or "file"
    ext = os.path.splitext(name)[1].lower()
    if check:
        allowed = allowed or current_app.config["ALLOWED_UPLOADS"]
        if ext not in allowed:
            nice = ", ".join(sorted(e.lstrip(".").upper() for e in allowed))
            raise DomainError(f"'{original_name}' isn't an allowed file type ({nice}).")
        if len(data) > current_app.config["MAX_UPLOAD_BYTES"]:
            limit = current_app.config["MAX_UPLOAD_BYTES"] // (1024 * 1024)
            raise DomainError(f"'{original_name}' is larger than {limit} MB.")
        if not data:
            raise DomainError(f"'{original_name}' is empty.")
    stored_name = secrets.token_hex(16) + ext
    with open(os.path.join(_folder(), stored_name), "wb") as f:
        f.write(data)
    stored = StoredFile(stored_name=stored_name, original_name=name,
                        content_type=MIME_TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream",
                        size=len(data), sha256=hashlib.sha256(data).hexdigest(), entity_type=entity_type,
                        entity_id=entity_id, uploaded_by_id=getattr(user, "id", None))
    db.session.add(stored)
    db.session.flush()
    audit.record("file.upload", entity_type, entity_id, after={"file_id": stored.id, "name": name, "size": len(data)},
                 user=user)
    return stored


def save_upload(file_storage, entity_type, entity_id=None, user=None, allowed=None):
    data = file_storage.read()
    return store_bytes(data, file_storage.filename, entity_type, entity_id, user, allowed)


def read(stored):
    with open(path_for(stored), "rb") as f:
        return f.read()


def can_download(user, stored):
    rule = ACCESS_RULES.get(stored.entity_type)
    return bool(rule and rule(user, stored.entity_id))


def files_for(entity_type, entity_id):
    return (StoredFile.query.filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(StoredFile.created_at).all())


def delete(stored):
    try:
        os.remove(path_for(stored))
    except FileNotFoundError:
        pass
    db.session.delete(stored)
