"""Import every model so SQLAlchemy and Flask-Migrate see the full schema."""
from app.models.budget import BudgetLine, BudgetMovement, OverspendAlert  # noqa: F401
from app.models.org import (ApprovedPosition, Asset, Branch, BusinessUnit, CostCentre, Department,  # noqa: F401
                            Employee, JobFamily, JobGrade, LeaveEntry, PositionChange, PositionRegister, Region)
from app.models.recruitment import Application, Candidate, Job  # noqa: F401
from app.models.requisition import Requisition, RequisitionVersion  # noqa: F401
from app.models.system import (AuditLog, IntegrationLog, Notification, NotificationTemplate,  # noqa: F401
                               PublicHoliday, RefSequence, Setting, StoredFile)
from app.models.user import Role, User  # noqa: F401
from app.models.workflow import Delegation, RoutingRule, WorkflowInstance, WorkflowStep  # noqa: F401
