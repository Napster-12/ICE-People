from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class OrgChartInterface(ABC):
    @abstractmethod
    def get_reporting_lines(self, employee): ...
    @abstractmethod
    def get_approved_positions(self, department_code, financial_year): ...


class MockOrgChart(Adapter, OrgChartInterface):
    """Reads the local Employee / ApprovedPosition tables."""
    system = "orgchart"

    def get_reporting_lines(self, employee):
        def fetch():
            chain, current = [], employee.manager
            while current and len(chain) < 10:
                chain.append(current.employee_number)
                current = current.manager
            return chain
        return self.call("get_reporting_lines", {"employee_number": employee.employee_number}, fetch)

    def get_approved_positions(self, department_code, financial_year):
        from app.models import ApprovedPosition, Department

        def fetch():
            rows = (ApprovedPosition.query.join(Department)
                    .filter(Department.code == department_code, ApprovedPosition.financial_year == financial_year))
            return [{"title": p.title, "headcount": p.headcount} for p in rows]
        return self.call("get_approved_positions", {"department": department_code, "fy": financial_year}, fetch)
