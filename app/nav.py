"""Left-rail navigation for the staff area, filtered by the signed-in user's roles."""
from app.models.user import COMPLIANCE, FINANCE, GCOO, HOD, HR_ADMIN, HR_MANAGER, HR_ROLES, IT, LINE_MANAGER
from app.services.interviews import PANEL_ROLES
from app.services.positions import REQUEST_ROLES, VIEW_ROLES as POSITION_VIEW_ROLES
from app.services.requisitions import CREATE_ROLES, SEE_ALL_ROLES

ANY = None  # visible to every signed-in user

# Each entry: (label, endpoint, icon, roles, active endpoint prefixes, description)
LINKS = [
    ("Dashboard", "dashboards.home", "dashboard", ANY, ("dashboards.",), ""),
    ("My Approvals", "approvals.inbox", "check", ANY, ("approvals.inbox",), ""),
]

MENUS = [
    ("Talent", [
        ("Requisitions", "requisitions.index", "file", CREATE_ROLES | SEE_ALL_ROLES | {HOD, LINE_MANAGER},
         ("requisitions.",), "Request new or replacement positions"),
        ("Approved Positions", "positions.index", "briefcase", POSITION_VIEW_ROLES,
         ("positions.index", "positions.new", "positions.edit", "positions.detail", "positions.import"),
         "The approved positions register"),
        ("Vacancy Dashboard", "positions.dashboard", "trending", POSITION_VIEW_ROLES, ("positions.dashboard",),
         "Vacancies by business unit, branch and more"),
        ("Ad-hoc Positions", "positions.adhoc_list", "plus", POSITION_VIEW_ROLES | REQUEST_ROLES, ("positions.adhoc",),
         "Request a position that isn't on the register"),
        ("Job Adverts", "adverts.index", "external", HR_ROLES,
         ("adverts.index", "adverts.new", "adverts.edit", "adverts.detail", "adverts.submit", "adverts.close",
          "adverts.readvertise"), "Advertise approved requisitions"),
        ("JD Library", "adverts.library", "file", HR_ROLES, ("adverts.library", "adverts.template"),
         "Standard job descriptions adverts start from"),
        ("Shortlist Reviews", "recruitment.shortlists", "users", {HOD}, ("recruitment.shortlist",),
         "Pick who goes to interview from HR's shortlists"),
        ("Interviews to Score", "recruitment.interviews_to_score", "star", set(PANEL_ROLES),
         ("recruitment.interviews", "recruitment.scorecard", "recruitment.interview_"),
         "Score the candidates on your interview panels"),
        ("Recruitment", "recruitment.dashboard", "trending", HR_ROLES, ("recruitment.dashboard",),
         "Hiring pipeline and latest applications"),
        ("Job Openings", "recruitment.jobs", "briefcase", HR_ROLES, ("recruitment.job",),
         "Vacancies and ranked applicants"),
        ("CV Database", "recruitment.candidates", "database", HR_ROLES, ("recruitment.candidate",),
         "Every CV, searchable and rankable"),
    ]),
    ("Budget", [
        ("Budget Lines", "budget.index", "building", {FINANCE, HR_ADMIN, HR_MANAGER, GCOO},
         ("budget.index", "budget.edit", "budget.import"), "Headcount budget per cost centre"),
        ("Budget Impact", "budget.report", "trending", {FINANCE, HR_ADMIN, HR_MANAGER, GCOO}, ("budget.report",),
         "Budget and demand per department"),
    ]),
    ("People", [
        ("Employees", "admin.employees", "users", HR_ROLES, ("admin.employee",), "Employee records"),
        ("Departments", "admin.departments", "building", {HR_ADMIN}, ("admin.department",),
         "Departments, department managers and cost centres"),
        ("Org Structure", "admin.org_structure", "filter", {HR_ADMIN}, ("admin.org_structure",),
         "Business units, regions, branches and job families"),
    ]),
    ("ICT", [
        ("Approvals Dashboard", "approvals.dashboard", "clock", {IT}, ("approvals.dashboard",),
         "Pending approvals and ageing"),
        ("Users & Roles", "admin.users", "shield", {IT}, ("admin.user",), "Accounts and roles"),
        ("Routing Rules", "admin.rules", "filter", {IT}, ("admin.rule",), "Who approves what"),
        ("Settings", "admin.settings_page", "sparkles", {IT},
         ("admin.settings", "admin.holiday", "admin.template"), "Thresholds, holidays, templates"),
        ("Assets", "admin.assets", "briefcase", {IT}, ("admin.asset",), "Laptops, phones and cards issued to staff"),
        ("Audit Log", "admin.audit_log", "file", {IT, COMPLIANCE}, ("admin.audit_log",),
         "Every action, change and access"),
        ("Integration Log", "admin.integrations", "external", {IT}, ("admin.integrations",),
         "Calls to payroll, AD, LMS and others"),
    ]),
]

USER_MENU = [
    ("My Profile", "portal.me", "users", ("portal.me",)),
    ("Notifications", "portal.notifications", "mail", ("portal.notifications",)),
    ("Delegation", "approvals.delegations", "clock", ("approvals.delegations",)),
    ("Password", "auth.account", "shield", ("auth.account",)),
]


def _item(entry, endpoint):
    label, ep, icon, _roles, prefixes, description = entry
    return {"label": label, "endpoint": ep, "icon": icon, "description": description,
            "active": any(endpoint.startswith(p) for p in prefixes)}


def _visible(user, roles):
    return roles is ANY or user.has_role(*roles)


def nav_for(user, endpoint):
    endpoint = endpoint or ""
    links = [_item(e, endpoint) for e in LINKS if _visible(user, e[3])]
    menus = []
    for title, entries in MENUS:
        items = [_item(e, endpoint) for e in entries if _visible(user, e[3])]
        if items:
            menus.append({"title": title, "items": items, "active": any(i["active"] for i in items)})
    user_menu = [{"label": l, "endpoint": ep, "icon": i, "active": any(endpoint.startswith(p) for p in pre)}
                 for l, ep, i, pre in USER_MENU]
    can_search = any(i["endpoint"] == "requisitions.index" for m in menus for i in m["items"])
    return {"links": links, "menus": menus, "user_menu": user_menu,
            "search": "requisitions.index" if can_search else None}
