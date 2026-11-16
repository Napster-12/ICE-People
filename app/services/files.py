"""Uploads: stored outside /static under random names, type-whitelisted, size-limited,
and permission-checked on every download.

Where the bytes live (16 Nov 2026): FILE_STORAGE=local (default) keeps them in UPLOAD_FOLDER; FILE_STORAGE=s3 puts
them in the S3_BUCKET (under S3_PREFIX), encrypted at rest (SSE-KMS with S3_KMS_KEY_ID, else SSE-S3). The bucket stays
private: every download still goes through the app's permission check. Only store_bytes, read, delete and local_copy
touch the storage; nothing else should open files by path."""
import contextlib
import tempfile
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
    """Local storage only. Use read() or local_copy() instead, which work with S3 too."""
    return os.path.join(_folder(), stored.stored_name)


# ------------------------------------------------------------------ storage backends

def _s3():
    return current_app.config.get("FILE_STORAGE", "local") == "s3"


_client = None


def s3_client():
    """One boto3 client per process. Credentials come from the standard AWS chain: the server's IAM role (preferred)
    or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment."""
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("s3", region_name=current_app.config.get("AWS_REGION") or None)
    return _client


def _key(stored_name):
    prefix = (current_app.config.get("S3_PREFIX") or "").strip("/")
    return f"{prefix}/{stored_name}" if prefix else stored_name


def _put(stored_name, data, content_type):
    if not _s3():
        with open(os.path.join(_folder(), stored_name), "wb") as f:
            f.write(data)
        return
    extra = {"ContentType": content_type}
    kms = current_app.config.get("S3_KMS_KEY_ID")
    extra.update({"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms} if kms else {"ServerSideEncryption": "AES256"})
    s3_client().put_object(Bucket=current_app.config["S3_BUCKET"], Key=_key(stored_name), Body=data, **extra)


def _get(stored_name):
    if not _s3():
        with open(os.path.join(_folder(), stored_name), "rb") as f:
            return f.read()
    obj = s3_client().get_object(Bucket=current_app.config["S3_BUCKET"], Key=_key(stored_name))
    return obj["Body"].read()


def _remove(stored_name):
    if not _s3():
        try:
            os.remove(os.path.join(_folder(), stored_name))
        except FileNotFoundError:
            pass
        return
    s3_client().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=_key(stored_name))


@contextlib.contextmanager
def local_copy(stored):
    """A path on disk for libraries that need one (the PDF maker's signature image). With S3, a temporary copy
    that is deleted afterwards."""
    if not _s3():
        yield path_for(stored)
        return
    ext = os.path.splitext(stored.stored_name)[1]
    handle, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(_get(stored.stored_name))
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


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
    content_type = MIME_TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"
    _put(stored_name, data, content_type)
    stored = StoredFile(stored_name=stored_name, original_name=name, content_type=content_type,
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
    return _get(stored.stored_name)


def can_download(user, stored):
    rule = ACCESS_RULES.get(stored.entity_type)
    return bool(rule and rule(user, stored.entity_id))


def files_for(entity_type, entity_id):
    return (StoredFile.query.filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(StoredFile.created_at).all())


def delete(stored):
    _remove(stored.stored_name)
    db.session.delete(stored)
