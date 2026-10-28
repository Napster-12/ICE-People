from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class DirectoryInterface(ABC):
    """Active Directory / Azure AD (write)."""
    @abstractmethod
    def provision_user(self, employee, access_profile): ...
    @abstractmethod
    def update_access(self, employee, access_profile): ...
    @abstractmethod
    def disable_user(self, employee, immediate=False): ...


class MockDirectory(Adapter, DirectoryInterface):
    system = "directory"

    def provision_user(self, employee, access_profile):
        payload = {"employee_number": employee.employee_number, "profile": access_profile}
        upn = f"{employee.first_name}.{employee.last_name}@icebolethu.co.za".lower().replace(" ", "")
        return self.call("provision_user", payload, lambda: {"upn": upn, "status": "requested"})

    def update_access(self, employee, access_profile):
        payload = {"employee_number": employee.employee_number, "profile": access_profile}
        return self.call("update_access", payload, lambda: {"status": "updated"})

    def disable_user(self, employee, immediate=False):
        payload = {"employee_number": employee.employee_number, "immediate": immediate}
        return self.call("disable_user", payload, lambda: {"status": "disabled"})
