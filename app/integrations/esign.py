import hashlib
import secrets
from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class ESignatureInterface(ABC):
    @abstractmethod
    def send_for_signature(self, document_bytes, signer_email): ...
    @abstractmethod
    def get_signed_document(self, envelope_id): ...


class MockESignature(Adapter, ESignatureInterface):
    system = "esign"

    def __init__(self):
        super().__init__()
        self._envelopes = {}

    def send_for_signature(self, document_bytes, signer_email):
        def send():
            envelope = "ENV-" + secrets.token_hex(6).upper()
            self._envelopes[envelope] = document_bytes
            return {"envelope_id": envelope, "sha256": hashlib.sha256(document_bytes).hexdigest()}
        return self.call("send_for_signature", {"signer": signer_email, "size": len(document_bytes)}, send)

    def get_signed_document(self, envelope_id):
        def fetch():
            data = self._envelopes.get(envelope_id, b"")
            return {"envelope_id": envelope_id, "sha256": hashlib.sha256(data).hexdigest()}
        return self.call("get_signed_document", {"envelope_id": envelope_id}, fetch)
