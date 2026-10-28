# ICE People Administration System

Icebolethu Group's people administration system.

One Flask application that combines the original recruitment portal (careers site, ATS and CV
database) with the HR modules specified in [docs/SPEC.md](docs/SPEC.md). Every page uses
the same Icebolethu brand design in `app/static/style.css`.

**Built so far: phases 1–4**

- Platform: sign-in, roles, audit log, notifications, the
  business-day calendar, the workflow engine and mock integrations.
- Requisitions, budget checks, and the Finance budget and salary band screens.
- The requisition approval chain, with delegation, SLA reminders and escalation, plus the approvals
  inbox and dashboard.
- The approved positions register: one record per position, yearly register approval, ad-hoc position
  requests, freeze / abolish / regrade, and the vacancy dashboard. Every requisition is raised from a
  vacant position.
- Separate sign-in pages for staff, managers and the HR admin portal.
- The original careers site, ATS and CV database, carried over unchanged in behaviour.

The remaining phases are listed in the spec (§12.1).

## Setup on Windows (VS Code terminal)

```powershell
py -3.11 -m venv .venv            # Python 3.11 or newer
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env            # then fill in SECRET_KEY and FERNET_KEY (commands are in the file)
$env:FLASK_APP = "run.py"
flask db upgrade                  # creates instance\hr.db
python seed.py                    # demo org structure, positions, budgets, users and requisitions
flask import-legacy               # optional: jobs, CVs and applications from the old portal.db
python run.py                     # http://127.0.0.1:5000
```

On macOS or Linux, use `python3 -m venv .venv`, then `source .venv/bin/activate`, then
`cp .env.example .env` and `export FLASK_APP=run.py`.

## Links

With the app running (`python run.py`), every page is at `http://127.0.0.1:5000`. If port 5000 is busy,
`run.py` picks the next free port and prints it; use that port instead. "HR roles" means HR Admin, Group HR
Manager, HR Manager, HR Business Partner, Recruiter and HR OD.

**Sign-in (public)**

| Page | Address | Who can open it |
|---|---|---|
| [Staff self-service landing](http://127.0.0.1:5000/login/staff) | `/login/staff` | Employees |
| [Staff sign-in](http://127.0.0.1:5000/login/staff/sign-in) | `/login/staff/sign-in` | Employees |
| [Manager self-service landing](http://127.0.0.1:5000/login/manager) | `/login/manager` | Line managers, HODs |
| [Manager sign-in](http://127.0.0.1:5000/login/manager/sign-in) | `/login/manager/sign-in` | Line managers, HODs |
| [HR admin portal landing](http://127.0.0.1:5000/login) | `/login` | HR, Finance, Payroll, IT, Assets, Compliance, GCOO, Exco |
| [HR admin sign-in](http://127.0.0.1:5000/login/sign-in) | `/login/sign-in` | HR, Finance, Payroll, IT, Assets, Compliance, GCOO, Exco |

**Careers site (public)**

| Page | Address | Who can open it |
|---|---|---|
| [Open vacancies](http://127.0.0.1:5000/) | `/` | Anyone |
| [Submit a CV to the talent pool](http://127.0.0.1:5000/talent-pool) | `/talent-pool` | Anyone |
| [Track an application](http://127.0.0.1:5000/status) | `/status` | Anyone |

**Everyone signed in**

| Page | Address | Who can open it |
|---|---|---|
| [Dashboard](http://127.0.0.1:5000/dashboard) | `/dashboard` | All staff |
| [My Approvals](http://127.0.0.1:5000/approvals/) | `/approvals/` | All staff |
| [Delegation](http://127.0.0.1:5000/approvals/delegations) | `/approvals/delegations` | All staff |
| [My profile](http://127.0.0.1:5000/me) | `/me` | All staff |
| [Notifications](http://127.0.0.1:5000/notifications) | `/notifications` | All staff |
| [Change password](http://127.0.0.1:5000/account) | `/account` | All staff |

**Requisitions and approved positions**

| Page | Address | Who can open it |
|---|---|---|
| [Requisitions](http://127.0.0.1:5000/requisitions/) | `/requisitions/` | Managers, HODs, HR, Finance, GCOO, Exco, Compliance |
| [New requisition](http://127.0.0.1:5000/requisitions/new) | `/requisitions/new` | Line managers, HODs, HR |
| [Approved positions register](http://127.0.0.1:5000/positions/) | `/positions/` | Managers, HODs, HR, Finance, GCOO, Exco, Compliance |
| [Add a position](http://127.0.0.1:5000/positions/new) | `/positions/new` | HR Admin, Group HR, HR Manager, HRBP |
| [Import positions (CSV)](http://127.0.0.1:5000/positions/import) | `/positions/import` | HR Admin, Group HR, HR Manager, HRBP |
| [Positions CSV template](http://127.0.0.1:5000/positions/import/template.csv) | `/positions/import/template.csv` | HR Admin, Group HR, HR Manager, HRBP |
| [Vacancy dashboard](http://127.0.0.1:5000/positions/dashboard) | `/positions/dashboard` | Managers, HODs, HR, Finance, GCOO, Exco, Compliance |
| [Vacancy dashboard (Excel export)](http://127.0.0.1:5000/positions/dashboard?format=xlsx) | `/positions/dashboard?format=xlsx` | Managers, HODs, HR, Finance, GCOO, Exco, Compliance |
| [Ad-hoc position requests](http://127.0.0.1:5000/positions/ad-hoc) | `/positions/ad-hoc` | Managers, HODs, HR, Finance, GCOO, Exco, Compliance |
| [Request an ad-hoc position](http://127.0.0.1:5000/positions/ad-hoc/new) | `/positions/ad-hoc/new` | Line managers, HODs, HR |

**Budget**

| Page | Address | Who can open it |
|---|---|---|
| [Budget lines](http://127.0.0.1:5000/budget/) | `/budget/` | Finance, HR Admin, HR Manager, GCOO |
| [Add a budget line](http://127.0.0.1:5000/budget/new) | `/budget/new` | Finance, HR Admin |
| [Import budget (CSV)](http://127.0.0.1:5000/budget/import) | `/budget/import` | Finance, HR Admin |
| [Budget CSV template](http://127.0.0.1:5000/budget/import/template.csv) | `/budget/import/template.csv` | Finance, HR Admin |
| [Budget impact report](http://127.0.0.1:5000/budget/report) | `/budget/report` | Finance, HR Admin, HR Manager, GCOO |
| [Salary bands](http://127.0.0.1:5000/budget/salary-bands) | `/budget/salary-bands` | Finance (view), HR Admin (edit) |

**Recruitment (ATS)**

| Page | Address | Who can open it |
|---|---|---|
| [Recruitment dashboard](http://127.0.0.1:5000/recruitment/) | `/recruitment/` | HR roles |
| [Job openings](http://127.0.0.1:5000/recruitment/jobs) | `/recruitment/jobs` | HR roles |
| [New job opening](http://127.0.0.1:5000/recruitment/jobs/new) | `/recruitment/jobs/new` | HR roles |
| [CV database](http://127.0.0.1:5000/recruitment/candidates) | `/recruitment/candidates` | HR roles |

**People and admin**

| Page | Address | Who can open it |
|---|---|---|
| [Employees](http://127.0.0.1:5000/admin/employees) | `/admin/employees` | HR roles |
| [New employee](http://127.0.0.1:5000/admin/employees/new) | `/admin/employees/new` | HR roles |
| [Departments and cost centres](http://127.0.0.1:5000/admin/departments) | `/admin/departments` | HR Admin |
| [Business units, regions, branches, job families](http://127.0.0.1:5000/admin/org-structure) | `/admin/org-structure` | HR Admin |
| [Approvals dashboard](http://127.0.0.1:5000/approvals/dashboard) | `/approvals/dashboard` | HR Admin, HR Manager |
| [Users and roles](http://127.0.0.1:5000/admin/users) | `/admin/users` | HR Admin |
| [New user](http://127.0.0.1:5000/admin/users/new) | `/admin/users/new` | HR Admin |
| [Routing rules](http://127.0.0.1:5000/admin/rules) | `/admin/rules` | HR Admin |
| [New routing rule](http://127.0.0.1:5000/admin/rules/new) | `/admin/rules/new` | HR Admin |
| [Settings, holidays and notification templates](http://127.0.0.1:5000/admin/settings) | `/admin/settings` | HR Admin |
| [Audit log](http://127.0.0.1:5000/admin/audit) | `/admin/audit` | HR Admin, Compliance |
| [Integration log](http://127.0.0.1:5000/admin/integrations) | `/admin/integrations` | HR Admin, IT |

**Pages for one record** (open them from the lists above; replace `<id>` with the record's number):

| Address | Page |
|---|---|
| `/requisitions/<id>` and `/requisitions/<id>/edit` | A requisition, and editing a draft or returned one |
| `/positions/<id>` and `/positions/<id>/edit` | A position, and editing it |
| `/positions/ad-hoc/<id>/edit` | Changing a returned ad-hoc request |
| `/budget/<id>/edit` | A budget line |
| `/recruitment/jobs/<id>`, `/recruitment/jobs/<id>/edit`, `/recruitment/jobs/<id>/export.csv` | A job opening, editing it, its applicants as CSV |
| `/recruitment/candidates/<id>` and `/recruitment/candidates/<id>/cv` | A candidate and their CV |
| `/admin/employees/<id>`, `/admin/users/<id>`, `/admin/rules/<id>`, `/admin/templates/<id>` | Employee, user, routing rule, notification template |
| `/jobs/<id>` | A vacancy on the public careers site, with step 1 of applying: five yes/no eligibility questions. A "No" sends the applicant to the talent pool page |
| `/jobs/<id>/apply` | Step 2 of applying: the application form (opens only after the eligibility check is passed) |
| `/files/<id>` | Download an attachment (permission checked) |

`/admin/login` and `/admin/` are old portal addresses; they redirect to the HR admin sign-in and the dashboard.

## Test users

`seed.py` creates one user per role. **Development and testing only:** never create these accounts on
a production server.

**Password for every test user: `Icebolethu@Test2026`**

This is the default `SEED_PASSWORD` in `.env.example`. If you change `SEED_PASSWORD` in `.env`
before running `seed.py`, use your value instead.

| Username | Email | Password | Role | Department |
|---|---|---|---|---|
| `employee` | `employee@icebolethu.test` | `Icebolethu@Test2026` | Employee | Sales |
| `linemanager` | `linemanager@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Sales |
| `hod` | `hod@icebolethu.test` | `Icebolethu@Test2026` | HOD | Sales |
| `panel` | `panel@icebolethu.test` | `Icebolethu@Test2026` | Panel Member | Sales |
| `hrbp` | `hrbp@icebolethu.test` | `Icebolethu@Test2026` | HR Business Partner | HR |
| `recruiter` | `recruiter@icebolethu.test` | `Icebolethu@Test2026` | Recruiter | HR |
| `hrod` | `hrod@icebolethu.test` | `Icebolethu@Test2026` | HR OD | HR |
| `hrmanager` | `hrmanager@icebolethu.test` | `Icebolethu@Test2026` | HR Manager | HR |
| `grouphr` | `grouphr@icebolethu.test` | `Icebolethu@Test2026` | Group HR Manager | HR |
| `hradmin` | `hradmin@icebolethu.test` | `Icebolethu@Test2026` | HR Admin | HR |
| `finance` | `finance@icebolethu.test` | `Icebolethu@Test2026` | Finance / Budget Controller | Finance |
| `payroll` | `payroll@icebolethu.test` | `Icebolethu@Test2026` | Payroll | Finance |
| `it` | `it@icebolethu.test` | `Icebolethu@Test2026` | IT | Operations |
| `assets` | `assets@icebolethu.test` | `Icebolethu@Test2026` | Asset Controller | Operations |
| `compliance` | `compliance@icebolethu.test` | `Icebolethu@Test2026` | Compliance | Operations |
| `gcoo` | `gcoo@icebolethu.test` | `Icebolethu@Test2026` | GCOO | Operations |
| `exco` | `exco@icebolethu.test` | `Icebolethu@Test2026` | Exco | Operations |

Every test user also has the Employee role.

**Reporting lines** decide who approves what:
- Sales: `employee` → `linemanager` → `hod` → `gcoo`
- HR: `hrbp`, `recruiter`, `hrod` and `hradmin` → `hrmanager` → `grouphr` → `gcoo`
- Finance: `payroll` → `finance` → `gcoo`
- Operations: `it`, `assets` and `compliance` → `gcoo`

**Old portal login:** after `flask import-legacy`, you can also sign in as `admin` with the password
it had in the old portal.

**Signing in:** use your own sign-in page (see Links): staff, managers, or the HR admin portal for HR,
Finance and the other admin roles. Signing in on another group's page sends you to your own. Type either
the username or the email address, plus the password. The "Continue with Microsoft" button is a placeholder. The system will move to Microsoft single sign-on
(Entra ID), which also provides two-step verification, so this system has no two-step sign-in of
its own.

`flask import-legacy` also brings across the old portal's `admin` login. It keeps its old password,
which is upgraded to argon2 at first sign-in, and gets the HR Admin and Recruiter roles.

## Walkthrough

1. Sign in as `linemanager` at [/login/manager](http://127.0.0.1:5000/login/manager) and open
   **Requisitions → New Requisition**. Choose a vacant position: the title, department, cost centre,
   grade and New / Replacement fill in from it. Choose Permanent and a start date; the budget check shows
   the CTC and the budget available. Click **Submit for approval**.
2. The approval chain comes from **Admin → Routing Rules**: line manager → Finance → Group HR Manager →
   GCOO (or an Exco member if there is no GCOO).
3. Sign in as `hod`, then `finance`, `grouphr` and `gcoo`, and open **My Approvals** each time. Approve,
   return or reject; a comment is required for each. Returning a requisition sends it back to the
   originator, and resubmitting restarts the chain at level 1.
4. When the final level approves, the CTC is committed against the cost centre (see **Budget Lines** as
   `finance`) and the position moves to "In recruitment". Closing the requisition unfilled releases the
   commitment and makes the position vacant again.
5. Positions not on the register need an **ad-hoc position request** first. The seeded "Claims Liaison
   Officer" request is waiting for `finance`.
6. As `hradmin`, open **Approved Positions** to see the register, freeze or regrade a position, and open the
   **Vacancy Dashboard** to group vacancies by business unit, branch, region and more, or export to Excel.
7. **Approvals → Delegation** sends your approvals to someone else for a date range.
   `flask run-sla-checks` sends reminders after 24 business hours and escalates any step past its
   SLA to the approver's manager.

## Scheduled jobs

Run these with Windows Task Scheduler or cron, from the project folder with the venv active:

| Command | When |
|---|---|
| `flask run-sla-checks` | Hourly during business hours |

## Commands

| Command | Purpose |
|---|---|
| `flask db upgrade` | Create or upgrade the database schema |
| `python seed.py` | Demo data. Safe to run again. |
| `flask import-legacy [--path portal.db]` | Copy the original portal's data. Safe to run again. |
| `flask set-password <username>` | Reset a user's password |
| `flask reprocess-cvs` | Re-read every CV and re-score every application |
| `python -m pytest --cov=app/services` | Tests with coverage |

## Project layout

```
app/
  models/         one file per domain (org, user, system, workflow, budget, requisition, recruitment)
  services/       business rules: workflow engine, budget, requisitions, audit, notifications, calendar,
                  references, files, ATS scoring (ats.py), careers
  integrations/   interface + Mock* adapter per external system (payroll, ERP, AD, LMS, job portals...)
  auth/ admin/ portal/ dashboards/ requisitions/ positions/ approvals/ budget/ recruitment/   one Blueprint each
  templates/ static/   shared layout and the Icebolethu stylesheet
legacy/           the original single-file portal (app.py, ats.py, seed_dummy.py), kept unchanged for reference
migrations/  tests/  seed.py  run.py
```

## How the ATS score works (`app/services/ats.py`)

| Component | Weight | How it's measured |
|---|---|---|
| Required skills | 45% | Share of the job's required skills found in the CV and skills field |
| Preferred skills | 15% | Share of preferred skills found |
| Experience | 20% | Stated years (or years detected in the CV) ÷ job minimum |
| Education | 10% | Highest qualification (form or detected in the CV) vs job minimum |
| Job-description fit | 10% | Overlap with key terms in the job title and description |

Criteria left blank on a job are skipped, and the remaining weights are rescaled to 100%.

## Security and data protection

- Sign-in will move to Microsoft SSO (Entra ID), which provides MFA and account protection, so this
  system doesn't lock accounts itself. Until then, test passwords are hashed with argon2, every failed
  sign-in is recorded in the audit log, and sign-in attempts are rate-limited.
- Sessions time out after 30 minutes idle. Every form is protected against CSRF.
- Secrets come only from `.env`, which is never committed.
- ID numbers and bank details are encrypted at rest with `FERNET_KEY`. **Back up this
  key:** without it, those fields can't be read.
- Uploads are stored in `instance/uploads` under random names. Only PDF, DOCX, XLSX, JPG and PNG
  files up to 10 MB are accepted, and permission is checked on every download.
- The audit log is append-only. It records sign-ins, every change (with before and after values),
  approvals, file access and configuration changes.
- **Deployment:** serve over HTTPS (TLS 1.2 or newer) behind IIS, nginx or a load balancer, and set
  `SESSION_COOKIE_SECURE=1` and `APP_ENV=production`. Run with a WSGI server such as `waitress` on
  Windows or `gunicorn` on Linux.
- **Data residency:** host the application, database and backups in South Africa (POPIA).
- **Backups (RPO ≤ 1 h, RTO ≤ 4 h):**
  - SQL Server or PostgreSQL: hourly log backups and a nightly full backup, copied off-site to a
    South African region.
  - Back up `instance/uploads` hourly as well, and keep `.env` (including `FERNET_KEY`) in a secrets
    vault.
  - Test a restore every quarter.
- **Switching database:** set `DATABASE_URL` (examples are in `.env.example`), install the driver,
  then run `flask db upgrade`.
