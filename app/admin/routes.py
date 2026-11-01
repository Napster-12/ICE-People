"""Configuration: users and roles, employees, departments, routing rules, settings, public holidays,
notification templates, the asset register, audit log and integration log. HR keeps the people pages; ICT (the IT role) owns the rest."""
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import (ApprovedPosition, Asset, AuditLog, Branch, BusinessUnit, CostCentre, Department, Employee,
                        IntegrationLog, JobFamily, JobGrade, Region,
                        NotificationTemplate, PublicHoliday, Role, RoutingRule, Setting, StoredFile, User)
from app.models.org import ASSET_STATUSES, EMPLOYEE_STATUSES, EMPLOYMENT_TYPES
from app.models.user import COMPLIANCE, GROUP_HR, HR_ADMIN, HR_MANAGER, HR_ROLES, HRBP, IT
from app.models.workflow import SPECIAL_APPROVERS
from app.services import audit, files, positions, settings
from app.services.conditions import ConditionError, validate
from app.services.errors import DomainError
from app.services.dates import today
from app.services.validators import validate_sa_id
from app.services.workflow import HANDLERS
from app.web import paginate

bp = Blueprint("admin", __name__, url_prefix="/admin")
EMPLOYEE_EDIT = (HR_ADMIN, HR_MANAGER, GROUP_HR, HRBP)


@bp.route("/")
@roles_required()
def legacy_dashboard():
    """The old portal's /admin now opens the main dashboard."""
    return redirect(url_for("dashboards.home"))


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


# ------------------------------------------------------------------ users

@bp.route("/users")
@roles_required(IT)
def users():
    q = User.query.order_by(User.full_name)
    if request.args.get("q"):
        like = f"%{request.args['q']}%"
        q = q.filter(db.or_(User.full_name.ilike(like), User.username.ilike(like), User.email.ilike(like)))
    if request.args.get("role"):
        q = q.filter(User.roles.any(Role.name == request.args["role"]))
    rows, pager = paginate(q, 30)
    return render_template("admin/users.html", rows=rows, pager=pager, roles=Role.query.order_by(Role.name).all(),
                           args=request.args)


@bp.route("/users/new", methods=["GET", "POST"])
@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@roles_required(IT)
def user_form(user_id=None):
    user = db.session.get(User, user_id) if user_id else None
    if user_id and user is None:
        abort(404)
    roles = Role.query.order_by(Role.name).all()
    if request.method == "POST":
        f = request.form
        errors = []
        username = f.get("username", "").strip()
        if not username or not f.get("full_name", "").strip():
            errors.append("Username and full name are required.")
        clash = User.query.filter(db.func.lower(User.username) == username.lower()).first()
        if clash and (user is None or clash.id != user.id):
            errors.append("That username is taken.")
        email = f.get("email", "").strip()
        if email:
            taken = User.query.filter(db.func.lower(User.email) == email.lower()).first()
            if taken and (user is None or taken.id != user.id):
                errors.append(f"That email is already used by {taken.username}. Emails are used to sign in.")
        password = f.get("password", "")
        if user is None and len(password) < 10:
            errors.append("Set a password of at least 10 characters.")
        if password and len(password) < 10:
            errors.append("Passwords must be at least 10 characters.")
        employee_id = f.get("employee_id", type=int) or None
        if employee_id:
            other = User.query.filter(User.employee_id == employee_id).first()
            if other and (user is None or other.id != user.id):
                errors.append(f"That employee is already linked to {other.username}.")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            before = None
            if user is None:
                user = User(username=username, full_name="", password_hash="")
                db.session.add(user)
            else:
                before = {"username": user.username, "active": user.active, "roles": sorted(user.role_names),
                          "employee_id": user.employee_id}
            user.username = username
            user.full_name = f.get("full_name").strip()
            user.email = f.get("email", "").strip() or None
            user.active = bool(f.get("active"))
            user.employee_id = employee_id
            chosen = set(f.getlist("roles"))
            user.roles = [r for r in roles if r.name in chosen]
            if password:
                user.set_password(password)
            db.session.flush()
            after = {"username": user.username, "active": user.active, "roles": sorted(user.role_names),
                     "employee_id": user.employee_id}
            if before is None:
                audit.record("create", "user", user.id, after=after)
            else:
                b, a = audit.changes(before, after)
                audit.record("config.user", "user", user.id, before=b, after=a)
            if password and before is not None:
                audit.record("password.reset", "user", user.id)
            db.session.commit()
            flash("User saved.", "success")
            return redirect(url_for("admin.users"))
    employees = Employee.query.order_by(Employee.last_name).all()
    return render_template("admin/user_form.html", user=user, roles=roles, employees=employees)


# -------------------------------------------------------------- employees

@bp.route("/employees")
@roles_required(*HR_ROLES)
def employees():
    q = Employee.query.options(joinedload(Employee.department), joinedload(Employee.manager),
                               joinedload(Employee.job_grade))
    if request.args.get("q"):
        like = f"%{request.args['q']}%"
        q = q.filter(db.or_(Employee.first_name.ilike(like), Employee.last_name.ilike(like),
                            Employee.employee_number.ilike(like), Employee.position_title.ilike(like)))
    if request.args.get("department_id", type=int):
        q = q.filter(Employee.department_id == request.args.get("department_id", type=int))
    if request.args.get("status"):
        q = q.filter(Employee.status == request.args["status"])
    rows, pager = paginate(q.order_by(Employee.last_name, Employee.first_name), 30)
    return render_template("admin/employees.html", rows=rows, pager=pager, args=request.args,
                           departments=Department.query.order_by(Department.name).all(), statuses=EMPLOYEE_STATUSES,
                           can_edit=current_user.has_role(*EMPLOYEE_EDIT))


EMPLOYEE_FIELDS = ["employee_number", "first_name", "last_name", "email", "phone", "department_id",
                   "cost_centre_id", "job_grade_id", "approved_position_id", "position_title", "manager_id",
                   "start_date", "employment_type", "status", "critical_role"]
SENSITIVE_FIELDS = ["id_number", "bank_account", "date_of_birth", "race", "gender", "disability"]


@bp.route("/employees/new", methods=["GET", "POST"])
@bp.route("/employees/<int:emp_id>", methods=["GET", "POST"])
@roles_required(*HR_ROLES)
def employee_form(emp_id=None):
    emp = db.session.get(Employee, emp_id) if emp_id else None
    if emp_id and emp is None:
        abort(404)
    can_edit = current_user.has_role(*EMPLOYEE_EDIT)
    sensitive = current_user.can_see_sensitive
    if emp is not None and sensitive and request.method == "GET":
        audit.record("data.view_sensitive", "employee", emp.id)
        db.session.commit()
    if request.method == "POST":
        if not can_edit:
            abort(403)
        f = request.form
        values = {
            "employee_number": f.get("employee_number", "").strip(),
            "first_name": f.get("first_name", "").strip(), "last_name": f.get("last_name", "").strip(),
            "email": f.get("email", "").strip() or None, "phone": f.get("phone", "").strip() or None,
            "department_id": f.get("department_id", type=int) or None,
            "cost_centre_id": f.get("cost_centre_id", type=int) or None,
            "job_grade_id": f.get("job_grade_id", type=int) or None,
            "approved_position_id": f.get("approved_position_id", type=int) or None,
            "position_title": f.get("position_title", "").strip() or None,
            "manager_id": f.get("manager_id", type=int) or None,
            "start_date": _date(f.get("start_date")),
            "employment_type": f.get("employment_type") or "Permanent",
            "status": f.get("status") or "Permanent",
            "critical_role": bool(f.get("critical_role")),
        }
        if sensitive:
            values.update({
                "id_number": f.get("id_number", "").replace(" ", "") or None,
                "bank_account": f.get("bank_account", "").strip() or None,
                "date_of_birth": _date(f.get("date_of_birth")),
                "race": f.get("race") or None, "gender": f.get("gender") or None,
                "disability": f.get("disability") or None,
            })
        errors = []
        if not values["employee_number"] or not values["first_name"] or not values["last_name"]:
            errors.append("Employee number, first name and last name are required.")
        clash = Employee.query.filter_by(employee_number=values["employee_number"]).first()
        if clash and (emp is None or clash.id != emp.id):
            errors.append("That employee number is already used.")
        if emp is not None and values["manager_id"] == emp.id:
            errors.append("An employee can't be their own manager.")
        if sensitive and values.get("id_number"):
            errors += validate_sa_id(values["id_number"], values.get("date_of_birth"))
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            fields = EMPLOYEE_FIELDS + (SENSITIVE_FIELDS if sensitive else [])
            before = {k: str(getattr(emp, k)) for k in fields} if emp else None
            old_position_id = emp.approved_position_id if emp else None
            if emp is None:
                emp = Employee()
                db.session.add(emp)
            for k, v in values.items():
                setattr(emp, k, v)
            db.session.flush()
            positions.employee_changed(emp, old_position_id)
            # Sensitive values are logged as changed, never in clear text.
            after = {k: ("•••" if k in SENSITIVE_FIELDS else str(getattr(emp, k))) for k in fields}
            if before is None:
                audit.record("create", "employee", emp.id, after=after)
            else:
                masked_before = {k: ("•••" if k in SENSITIVE_FIELDS else v) for k, v in before.items()}
                changed = [k for k in fields if before[k] != str(getattr(emp, k))]
                audit.record("update", "employee", emp.id, before={k: masked_before[k] for k in changed},
                             after={k: after[k] for k in changed})
            db.session.commit()
            flash("Employee saved.", "success")
            return redirect(url_for("admin.employees"))
    return render_template(
        "admin/employee_form.html", emp=emp, can_edit=can_edit, sensitive=sensitive,
        departments=Department.query.order_by(Department.name).all(),
        cost_centres=CostCentre.query.order_by(CostCentre.code).all(),
        grades=JobGrade.query.order_by(JobGrade.grade).all(),
        positions=ApprovedPosition.query.filter(ApprovedPosition.status.notin_(["Abolished", "Rejected"]))
        .order_by(ApprovedPosition.title, ApprovedPosition.position_number).all(),
        managers=Employee.query.filter(Employee.status.notin_(["Exited", "Archived"])).order_by(Employee.last_name).all(),
        statuses=EMPLOYEE_STATUSES, employment_types=EMPLOYMENT_TYPES)


# ------------------------------------------------------------ departments

@bp.route("/departments", methods=["GET", "POST"])
@roles_required(HR_ADMIN)
def departments():
    if request.method == "POST":
        f = request.form
        kind = f.get("kind")
        code, name = f.get("code", "").strip().upper(), f.get("name", "").strip()
        if not code or not name:
            flash("Code and name are required.", "error")
        elif kind == "department":
            dept = db.session.get(Department, f.get("id", type=int) or 0)
            clash = Department.query.filter_by(code=code).first()
            if clash and (dept is None or clash.id != dept.id):
                flash("That department code is taken.", "error")
            else:
                before = {"code": dept.code, "name": dept.name, "hod": dept.hod_employee_id,
                          "job_family": dept.job_family_id} if dept else None
                if dept is None:
                    dept = Department(code=code, name=name)
                    db.session.add(dept)
                dept.code, dept.name = code, name
                dept.hod_employee_id = f.get("hod_employee_id", type=int) or None
                dept.business_unit_id = f.get("business_unit_id", type=int) or None
                dept.job_family_id = f.get("job_family_id", type=int) or None
                db.session.flush()
                audit.record("config.department", "department", dept.id, before=before,
                             after={"code": code, "name": name, "hod": dept.hod_employee_id,
                                    "business_unit": dept.business_unit_id, "job_family": dept.job_family_id})
                db.session.commit()
                flash("Department saved.", "success")
        elif kind == "cost_centre":
            dept = db.session.get(Department, f.get("department_id", type=int) or 0)
            if dept is None or CostCentre.query.filter_by(code=code).first():
                flash("Choose a department and a new, unique cost centre code.", "error")
            else:
                cc = CostCentre(code=code, name=name, department_id=dept.id)
                db.session.add(cc)
                db.session.flush()
                audit.record("config.cost_centre", "cost_centre", cc.id, after={"code": code, "dept": dept.code})
                db.session.commit()
                flash("Cost centre added.", "success")
        return redirect(url_for("admin.departments"))
    depts = Department.query.options(joinedload(Department.cost_centres), joinedload(Department.hod)) \
        .order_by(Department.name).all()
    employees = Employee.query.order_by(Employee.last_name).all()
    return render_template("admin/departments.html", depts=depts, employees=employees,
                           business_units=BusinessUnit.query.order_by(BusinessUnit.name).all(),
                           families=JobFamily.query.order_by(JobFamily.name).all())


# ---------------------------------------------------------- org structure

ORG_KINDS = {"business_unit": (BusinessUnit, "Business units", "Business unit"), "region": (Region, "Regions", "Region"),
             "branch": (Branch, "Branches / areas", "Branch"), "job_family": (JobFamily, "Job families", "Job family")}


@bp.route("/org-structure", methods=["GET", "POST"])
@roles_required(HR_ADMIN)
def org_structure():
    if request.method == "POST":
        f = request.form
        kind = f.get("kind")
        if kind not in ORG_KINDS:
            abort(400)
        model = ORG_KINDS[kind][0]
        code, name = f.get("code", "").strip().upper(), f.get("name", "").strip()
        row = db.session.get(model, f.get("id", type=int) or 0)
        clash = model.query.filter_by(code=code).first()
        if not code or not name:
            flash("Code and name are required.", "error")
        elif clash and (row is None or clash.id != row.id):
            flash(f"The code {code} is already used.", "error")
        else:
            before = {"code": row.code, "name": row.name, "active": row.active} if row else None
            if row is None:
                row = model(code=code, name=name)
                db.session.add(row)
            row.code, row.name, row.active = code, name, bool(f.get("active", "1"))
            if kind == "branch":
                row.region_id = f.get("region_id", type=int) or None
            db.session.flush()
            audit.record(f"config.{kind}", kind, row.id, before=before,
                         after={"code": row.code, "name": row.name, "active": row.active})
            db.session.commit()
            flash(f"{ORG_KINDS[kind][2]} saved.", "success")
        return redirect(url_for("admin.org_structure"))
    lists = {k: (title, m.query.order_by(m.name).all()) for k, (m, title, _one) in ORG_KINDS.items()}
    return render_template("admin/org_structure.html", lists=lists,
                           regions=Region.query.filter_by(active=True).order_by(Region.name).all())


# ---------------------------------------------------------- routing rules

@bp.route("/rules")
@roles_required(IT)
def rules():
    rows = RoutingRule.query.order_by(RoutingRule.workflow_type, RoutingRule.level, RoutingRule.id).all()
    return render_template("admin/rules.html", rows=rows)


@bp.route("/rules/new", methods=["GET", "POST"])
@bp.route("/rules/<int:rule_id>", methods=["GET", "POST"])
@roles_required(IT)
def rule_form(rule_id=None):
    rule = db.session.get(RoutingRule, rule_id) if rule_id else None
    if rule_id and rule is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        wf_type = f.get("workflow_type", "").strip()
        values = {"workflow_type": wf_type, "level": f.get("level", type=int) or 1,
                  "name": f.get("name", "").strip(), "approver": f.get("approver", "").strip(),
                  "condition": f.get("condition", "").strip(), "sla_days": f.get("sla_days", type=int) or 1,
                  "active": bool(f.get("active"))}
        errors = []
        if not values["name"] or not values["approver"]:
            errors.append("Name and approver are required.")
        if values["approver"] not in SPECIAL_APPROVERS and not Role.query.filter_by(name=values["approver"]).first():
            errors.append("Choose a valid approver.")
        if wf_type not in HANDLERS:
            errors.append("Choose a workflow type.")
        else:
            try:
                validate(values["condition"], HANDLERS[wf_type].sample_context)
            except ConditionError as exc:
                errors.append(str(exc))
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            before = {k: getattr(rule, k) for k in values} if rule else None
            if rule is None:
                rule = RoutingRule(**values)
                db.session.add(rule)
            else:
                for k, v in values.items():
                    setattr(rule, k, v)
            db.session.flush()
            audit.record("config.routing_rule", "routing_rule", rule.id, before=before, after=values)
            db.session.commit()
            flash("Routing rule saved. New submissions use it straight away.", "success")
            return redirect(url_for("admin.rules"))
    fields = sorted(HANDLERS["requisition"].sample_context) if "requisition" in HANDLERS else []
    return render_template("admin/rule_form.html", rule=rule, roles=Role.query.order_by(Role.name).all(),
                           special=SPECIAL_APPROVERS, workflow_types=sorted(HANDLERS), fields=fields,
                           default_sla=settings.get("default_sla_days", int))


# -------------------------------------------------- settings and holidays

@bp.route("/settings", methods=["GET", "POST"])
@roles_required(IT)
def settings_page():
    settings.ensure_defaults()
    rows = Setting.query.order_by(Setting.key).all()
    if request.method == "POST":
        errors = []
        for row in rows:
            value = request.form.get(row.key, "").strip()
            if row.key in settings.TEXT_KEYS:
                if not value:
                    errors.append(f"{row.label}: can't be empty.")
                elif value != row.value:
                    audit.record("config.setting", "setting", row.key, before={"value": row.value},
                                 after={"value": value})
                    row.value = value
                continue
            try:
                number = float(value)
            except ValueError:
                errors.append(f"{row.label}: enter a number.")
                continue
            if row.key == "fy_start_month" and not (1 <= number <= 12 and number == int(number)):
                errors.append("Financial year start month must be 1–12.")
                continue
            if number < 0:
                errors.append(f"{row.label}: can't be negative.")
                continue
            if value != row.value:
                audit.record("config.setting", "setting", row.key, before={"value": row.value}, after={"value": value})
                row.value = value
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, "error")
        else:
            db.session.commit()
            flash("Settings saved.", "success")
        return redirect(url_for("admin.settings_page"))
    holidays = PublicHoliday.query.order_by(PublicHoliday.date).all()
    templates = NotificationTemplate.query.order_by(NotificationTemplate.name).all()
    db.session.commit()
    return render_template("admin/settings.html", rows=rows, holidays=holidays, templates=templates,
                           text_keys=settings.TEXT_KEYS)


@bp.route("/holidays", methods=["POST"])
@roles_required(IT)
def holiday_add():
    d, name = _date(request.form.get("date")), request.form.get("name", "").strip()
    if d is None or not name:
        flash("Enter a date and a name.", "error")
    elif PublicHoliday.query.filter_by(date=d).first():
        flash("There is already a holiday on that date.", "error")
    else:
        h = PublicHoliday(date=d, name=name)
        db.session.add(h)
        db.session.flush()
        audit.record("config.holiday_add", "public_holiday", h.id, after={"date": d.isoformat(), "name": name})
        db.session.commit()
        flash("Public holiday added.", "success")
    return redirect(url_for("admin.settings_page") + "#holidays")


@bp.route("/holidays/<int:holiday_id>/delete", methods=["POST"])
@roles_required(IT)
def holiday_delete(holiday_id):
    h = db.session.get(PublicHoliday, holiday_id) or abort(404)
    audit.record("config.holiday_delete", "public_holiday", h.id, before={"date": h.date.isoformat(), "name": h.name})
    db.session.delete(h)
    db.session.commit()
    flash("Public holiday removed.", "success")
    return redirect(url_for("admin.settings_page") + "#holidays")


@bp.route("/templates/<int:template_id>", methods=["GET", "POST"])
@roles_required(IT)
def template_form(template_id):
    from jinja2 import TemplateSyntaxError
    from jinja2.sandbox import SandboxedEnvironment
    tpl = db.session.get(NotificationTemplate, template_id) or abort(404)
    if request.method == "POST":
        subject, body = request.form.get("subject", "").strip(), request.form.get("body", "").strip()
        try:
            env = SandboxedEnvironment()
            env.parse(subject)
            env.parse(body)
        except TemplateSyntaxError as exc:
            flash(f"Template error: {exc.message}", "error")
        else:
            if not subject or not body:
                flash("Subject and body are required.", "error")
            else:
                audit.record("config.notification_template", "notification_template", tpl.id,
                             before={"subject": tpl.subject, "body": tpl.body}, after={"subject": subject, "body": body})
                tpl.subject, tpl.body = subject, body
                db.session.commit()
                flash("Template saved.", "success")
                return redirect(url_for("admin.settings_page") + "#templates")
    return render_template("admin/template_form.html", tpl=tpl)


# ---------------------------------------------------------------- assets

@bp.route("/assets")
@roles_required(IT)
def assets():
    q = Asset.query.join(Employee).options(joinedload(Asset.employee))
    a = request.args
    if a.get("q"):
        like = f"%{a['q'].strip()}%"
        q = q.filter(db.or_(Asset.asset_tag.ilike(like), Asset.description.ilike(like),
                            Employee.first_name.ilike(like), Employee.last_name.ilike(like),
                            Employee.employee_number.ilike(like)))
    if a.get("category"):
        q = q.filter(Asset.category == a["category"])
    if a.get("status"):
        q = q.filter(Asset.status == a["status"])
    rows, pager = paginate(q.order_by(Asset.asset_tag), 50)
    forms = {f.entity_id: f for f in StoredFile.query.filter(StoredFile.entity_type == "asset_allocation",
                                                             StoredFile.entity_id.in_([r.id for r in rows]))
             .order_by(StoredFile.created_at)}   # the latest upload wins
    categories = [c for (c,) in db.session.query(Asset.category).distinct().order_by(Asset.category) if c]
    counts = dict(db.session.query(Asset.status, db.func.count(Asset.id)).group_by(Asset.status))
    return render_template("admin/assets.html", rows=rows, pager=pager, args=a, categories=categories,
                           statuses=ASSET_STATUSES, counts=counts, forms=forms)


@bp.route("/assets/new", methods=["GET", "POST"])
@bp.route("/assets/<int:asset_id>", methods=["GET", "POST"])
@roles_required(IT)
def asset_form(asset_id=None):
    asset = db.session.get(Asset, asset_id) if asset_id else None
    if asset_id and asset is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        values = {"asset_tag": f.get("asset_tag", "").strip(), "category": f.get("category", "").strip() or None,
                  "description": f.get("description", "").strip() or None,
                  "employee_id": f.get("employee_id", type=int), "issued_on": _date(f.get("issued_on")),
                  "status": f.get("status", ""), "returned_on": _date(f.get("returned_on"))}
        errors = []
        if not values["asset_tag"]:
            errors.append("Asset tag is required.")
        elif Asset.query.filter(Asset.asset_tag == values["asset_tag"], Asset.id != (asset.id if asset else 0)).first():
            errors.append(f"Asset tag {values['asset_tag']} is already on the register.")
        if not values["employee_id"] or not db.session.get(Employee, values["employee_id"]):
            errors.append("Choose the employee the asset is issued to.")
        if values["status"] not in ASSET_STATUSES:
            errors.append("Choose a status.")
        if values["status"] == "Returned" and not values["returned_on"]:
            values["returned_on"] = today()
        if values["status"] == "Issued":
            values["returned_on"] = None
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            before = {k: getattr(asset, k) for k in values} if asset else None
            if asset is None:
                asset = Asset(**values)
                db.session.add(asset)
            else:
                for k, v in values.items():
                    setattr(asset, k, v)
            db.session.flush()
            audit.record("asset.saved", "asset", asset.id, before=before, after=values)
            upload = request.files.get("allocation_form")
            try:
                if upload and upload.filename:
                    files.save_upload(upload, "asset_allocation", asset.id, current_user)
            except DomainError as exc:
                db.session.rollback()
                asset = db.session.get(Asset, asset_id) if asset_id else None
                flash(str(exc), "error")
            else:
                db.session.commit()
                flash(f"Asset {asset.asset_tag} saved.", "success")
                return redirect(url_for("admin.assets"))
    employees = Employee.query.order_by(Employee.first_name, Employee.last_name).all()
    categories = [c for (c,) in db.session.query(Asset.category).distinct().order_by(Asset.category) if c]
    forms = list(reversed(files.files_for("asset_allocation", asset.id))) if asset else []
    return render_template("admin/asset_form.html", item=asset, employees=employees, statuses=ASSET_STATUSES,
                           categories=categories, forms=forms, employee_id=request.args.get("employee_id", type=int))


# --------------------------------------------------------------- the logs

@bp.route("/audit")
@roles_required(IT, COMPLIANCE)
def audit_log():
    q = AuditLog.query
    a = request.args
    if a.get("action"):
        q = q.filter(AuditLog.action.ilike(f"%{a['action']}%"))
    if a.get("entity"):
        q = q.filter(AuditLog.entity == a["entity"])
    if a.get("entity_id"):
        q = q.filter(AuditLog.entity_id == a["entity_id"])
    if a.get("user"):
        q = q.filter(AuditLog.username.ilike(f"%{a['user']}%"))
    if _date(a.get("date_from")):
        q = q.filter(AuditLog.timestamp >= datetime.combine(_date(a["date_from"]), datetime.min.time()))
    if _date(a.get("date_to")):
        q = q.filter(AuditLog.timestamp <= datetime.combine(_date(a["date_to"]), datetime.max.time()))
    rows, pager = paginate(q.order_by(AuditLog.id.desc()), 50)
    entities = [e for (e,) in db.session.query(AuditLog.entity).distinct().order_by(AuditLog.entity) if e]
    return render_template("admin/audit.html", rows=rows, pager=pager, args=a, entities=entities)


@bp.route("/integrations")
@roles_required(IT)
def integrations():
    q = IntegrationLog.query
    if request.args.get("system"):
        q = q.filter(IntegrationLog.system == request.args["system"])
    if request.args.get("failures"):
        q = q.filter(IntegrationLog.success.is_(False))
    rows, pager = paginate(q.order_by(IntegrationLog.id.desc()), 50)
    systems = [s for (s,) in db.session.query(IntegrationLog.system).distinct().order_by(IntegrationLog.system)]
    failures = IntegrationLog.query.filter_by(success=False).count()
    return render_template("admin/integrations.html", rows=rows, pager=pager, args=request.args, systems=systems,
                           failures=failures)
