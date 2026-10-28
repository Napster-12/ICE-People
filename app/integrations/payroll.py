from abc import ABC, abstractmethod
from decimal import Decimal

from app.integrations.base import Adapter


class PayrollInterface(ABC):
    @abstractmethod
    def push_new_starter(self, employee): ...
    @abstractmethod
    def push_status_change(self, employee, status): ...
    @abstractmethod
    def push_leaver(self, employee, last_day): ...
    @abstractmethod
    def get_leave_balance(self, employee): ...
    @abstractmethod
    def push_salary_change(self, employee, amount): ...


class MockPayroll(Adapter, PayrollInterface):
    system = "payroll"

    def push_new_starter(self, employee):
        payload = {"employee_number": employee.employee_number, "name": employee.full_name}
        return self.call("push_new_starter", payload, lambda: {"status": "accepted"})

    def push_status_change(self, employee, status):
        payload = {"employee_number": employee.employee_number, "status": status}
        return self.call("push_status_change", payload, lambda: {"status": "accepted"})

    def push_leaver(self, employee, last_day):
        payload = {"employee_number": employee.employee_number, "last_day": str(last_day)}
        return self.call("push_leaver", payload, lambda: {"status": "accepted"})

    def get_leave_balance(self, employee):
        # Deterministic mock: 1.25 days per month of service, capped at 21.
        def fetch():
            return {"days": str(min(Decimal("21"), Decimal(employee.id % 17) + Decimal("3.5")))}
        return self.call("get_leave_balance", {"employee_number": employee.employee_number}, fetch)

    def push_salary_change(self, employee, amount):
        payload = {"employee_number": employee.employee_number, "amount": str(amount)}
        return self.call("push_salary_change", payload, lambda: {"status": "accepted"})
