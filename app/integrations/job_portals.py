import secrets
from abc import ABC, abstractmethod

from app.integrations.base import Adapter

CHANNELS = ["Internal", "Intranet", "PNet", "LinkedIn", "CareerJunction"]


class JobPortalInterface(ABC):
    @abstractmethod
    def publish_advert(self, channel, advert): ...
    @abstractmethod
    def close_advert(self, channel, external_id): ...
    @abstractmethod
    def fetch_applications(self, channel, external_id): ...


class MockJobPortals(Adapter, JobPortalInterface):
    system = "job_portals"

    def publish_advert(self, channel, advert):
        payload = {"channel": channel, "title": getattr(advert, "title", str(advert))}
        return self.call("publish_advert", payload,
                         lambda: {"external_id": f"{channel[:3].upper()}-{secrets.token_hex(4)}", "status": "live"})

    def close_advert(self, channel, external_id):
        return self.call("close_advert", {"channel": channel, "external_id": external_id},
                         lambda: {"status": "closed"})

    def fetch_applications(self, channel, external_id):
        return self.call("fetch_applications", {"channel": channel, "external_id": external_id}, lambda: [])
