import secrets
from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class ScreeningInterface(ABC):
    @abstractmethod
    def request_check(self, candidate, checks): ...
    @abstractmethod
    def get_result(self, request_id): ...


class MockScreening(Adapter, ScreeningInterface):
    system = "screening"

    def request_check(self, candidate, checks):
        payload = {"candidate": getattr(candidate, "id", None), "checks": list(checks)}
        return self.call("request_check", payload,
                         lambda: {"request_id": "SCR-" + secrets.token_hex(4).upper(), "status": "Pending"})

    def get_result(self, request_id):
        return self.call("get_result", {"request_id": request_id}, lambda: {"status": "Clear"})
