"""Mock leave calendar (used to suggest delegates and route around absent approvers)."""
from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class LeaveCalendarInterface(ABC):
    @abstractmethod
    def is_on_leave(self, employee, on_date): ...


class MockLeaveCalendar(Adapter, LeaveCalendarInterface):
    system = "leave"

    def is_on_leave(self, employee, on_date):
        from app.models import LeaveEntry
        if employee is None:
            return False
        return LeaveEntry.query.filter(LeaveEntry.employee_id == employee.id, LeaveEntry.start_date <= on_date,
                                       LeaveEntry.end_date >= on_date).first() is not None
