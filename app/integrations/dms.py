import secrets
from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class DocumentStoreInterface(ABC):
    @abstractmethod
    def store(self, name, data, metadata=None): ...
    @abstractmethod
    def retrieve(self, document_id): ...


class MockDocumentStore(Adapter, DocumentStoreInterface):
    system = "dms"

    def __init__(self):
        super().__init__()
        self._docs = {}

    def store(self, name, data, metadata=None):
        def put():
            doc_id = "DMS-" + secrets.token_hex(6).upper()
            self._docs[doc_id] = (name, data)
            return {"document_id": doc_id}
        return self.call("store", {"name": name, "size": len(data), "metadata": metadata or {}}, put)

    def retrieve(self, document_id):
        def get():
            name, _data = self._docs.get(document_id, ("", b""))
            return {"document_id": document_id, "name": name}
        return self.call("retrieve", {"document_id": document_id}, get)
