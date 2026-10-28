from abc import ABC, abstractmethod

from app.integrations.base import Adapter


class ERPInterface(ABC):
    @abstractmethod
    def get_cost_centres(self): ...
    @abstractmethod
    def get_budget(self, cost_centre_code, financial_year): ...
    @abstractmethod
    def get_gl_codes(self): ...


class MockERP(Adapter, ERPInterface):
    system = "erp"

    def get_cost_centres(self):
        from app.models import CostCentre
        return self.call("get_cost_centres", {},
                         lambda: [{"code": c.code, "name": c.name} for c in CostCentre.query.all()])

    def get_budget(self, cost_centre_code, financial_year):
        from app.models import BudgetLine, CostCentre

        def fetch():
            line = (BudgetLine.query.join(CostCentre)
                    .filter(CostCentre.code == cost_centre_code, BudgetLine.financial_year == financial_year).first())
            return {"amount": str(line.amount) if line else "0"}
        return self.call("get_budget", {"cost_centre": cost_centre_code, "fy": financial_year}, fetch)

    def get_gl_codes(self):
        return self.call("get_gl_codes", {}, lambda: [{"code": "5100", "name": "Salaries and wages"},
                                                     {"code": "5110", "name": "Contract staff"}])
