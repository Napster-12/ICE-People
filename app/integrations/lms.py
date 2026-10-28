from abc import ABC, abstractmethod

from app.integrations.base import Adapter

MOCK_COURSES = [
    {"code": "POPIA-101", "title": "POPIA essentials", "competency": "Compliance", "mandatory": True},
    {"code": "OHS-101", "title": "Health and safety induction", "competency": "Compliance", "mandatory": True},
    {"code": "ETH-101", "title": "Code of ethics", "competency": "Integrity", "mandatory": True},
    {"code": "XL-201", "title": "Excel for business", "competency": "Data literacy", "mandatory": False},
    {"code": "LDR-301", "title": "First-time manager", "competency": "Leadership", "mandatory": False},
    {"code": "CX-201", "title": "Customer service excellence", "competency": "Customer focus", "mandatory": False},
]


class LMSInterface(ABC):
    @abstractmethod
    def enrol(self, employee, course_code): ...
    @abstractmethod
    def get_completions(self, employee): ...
    @abstractmethod
    def list_courses_by_competency(self, competency): ...


class MockLMS(Adapter, LMSInterface):
    system = "lms"

    def enrol(self, employee, course_code):
        payload = {"employee_number": employee.employee_number, "course": course_code}
        return self.call("enrol", payload, lambda: {"status": "enrolled", "course": course_code})

    def get_completions(self, employee):
        return self.call("get_completions", {"employee_number": employee.employee_number}, lambda: [])

    def list_courses_by_competency(self, competency):
        return self.call("list_courses_by_competency", {"competency": competency},
                         lambda: [c for c in MOCK_COURSES if c["competency"].lower() == (competency or "").lower()])
