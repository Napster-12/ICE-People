"""Generic approval workflow: routing rules, instances, steps and delegations."""
from app.extensions import db
from app.services.dates import now

# Special approver values (anything else is a role name).
LINE_MANAGER_OR_HOD = "@line_manager_or_hod"
ORIGINATOR_MANAGER = "@originator_manager"
GCOO_OR_EXCO = "@gcoo_or_exco"
DEPARTMENT_MANAGER = "@department_manager"
DEPARTMENT_LINE_MANAGER = "@department_line_manager"
SPECIAL_APPROVERS = {
    LINE_MANAGER_OR_HOD: "Line Manager / Department Manager of the originator",
    ORIGINATOR_MANAGER: "Originator's manager",
    GCOO_OR_EXCO: "GCOO, or an Exco member",
    DEPARTMENT_MANAGER: "Department Manager of the request's department",
    DEPARTMENT_LINE_MANAGER: "Line Manager above the department's Department Manager",
}

INSTANCE_STATUSES = ["Pending", "Approved", "Returned", "Rejected", "Cancelled"]
STEP_STATUSES = ["Waiting", "Pending", "Approved", "Returned", "Rejected", "Cancelled"]


class RoutingRule(db.Model):
    __tablename__ = "routing_rules"
    id = db.Column(db.Integer, primary_key=True)
    workflow_type = db.Column(db.String(40), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    approver = db.Column(db.String(80), nullable=False)
    condition = db.Column(db.String(500), default="", nullable=False)
    sla_days = db.Column(db.Integer, nullable=False, default=2)
    active = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def approver_label(self):
        return SPECIAL_APPROVERS.get(self.approver, self.approver)


class WorkflowInstance(db.Model):
    __tablename__ = "workflow_instances"
    id = db.Column(db.Integer, primary_key=True)
    workflow_type = db.Column(db.String(40), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    round = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="Pending", index=True)
    originator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    context = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    completed_at = db.Column(db.DateTime)

    originator = db.relationship("User")
    steps = db.relationship("WorkflowStep", back_populates="instance", order_by="WorkflowStep.level",
                            cascade="all, delete-orphan")

    @property
    def current_step(self):
        return next((s for s in self.steps if s.status == "Pending"), None)


class WorkflowStep(db.Model):
    __tablename__ = "workflow_steps"
    id = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(db.Integer, db.ForeignKey("workflow_instances.id"), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    approver_rule = db.Column(db.String(80), nullable=False)
    sla_days = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Waiting", index=True)
    # approver = who the rule resolved to; assignee = who must act now (delegate / escalation).
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    routing_note = db.Column(db.String(255))
    action = db.Column(db.String(20))
    comment = db.Column(db.Text)
    activated_at = db.Column(db.DateTime, index=True)
    due_at = db.Column(db.DateTime, index=True)
    acted_at = db.Column(db.DateTime)
    reminded_at = db.Column(db.DateTime)
    escalated_at = db.Column(db.DateTime)
    escalated_from_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    instance = db.relationship(WorkflowInstance, back_populates="steps")
    approver = db.relationship("User", foreign_keys=[approver_id])
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    actor = db.relationship("User", foreign_keys=[actor_id])
    escalated_from = db.relationship("User", foreign_keys=[escalated_from_id])


class Delegation(db.Model):
    __tablename__ = "delegations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    delegate_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    delegate = db.relationship("User", foreign_keys=[delegate_id])
