# ICE People Administration System

Icebolethu Group's people administration system.

One Flask application that combines the original recruitment portal (careers site, ATS and CV
database) with the HR modules specified in [docs/SPEC.md](docs/SPEC.md). Every page uses one
stylesheet, `app/static/style.css`. The staff pages follow the layout, design and colours of the IGSP
(Icebolethu Group Supplier Portal) admin area: a white sidebar with the logo, the page title on a grey
background, flat orange buttons, and the logo colours only. The careers site keeps its own layout, with
sunburst accents.

**Built so far: phases 1–5**

- Platform: sign-in, roles, audit log, notifications, the
  business-day calendar, the workflow engine and mock integrations.
- Requisitions, budget checks (costed from the position's budgeted CTC), and the Finance budget screens.
- The requisition approval chain, with delegation, SLA reminders and escalation, plus the approvals
  inbox and dashboard.
- The approved positions register: one record per position, yearly register approval, ad-hoc position
  requests, freeze / abolish / regrade, and the vacancy dashboard. Every requisition is raised from a
  vacant position.
- Job adverts and the JD library: adverts drafted from approved requisitions, HR Manager approval,
  publishing to the careers site and job-portal channels, and views and applications per channel.
- Separate sign-in pages for staff, managers and the HR admin portal, and a home page for each.
- The asset register (IT).
- The original careers site, ATS and CV database, carried over unchanged in behaviour, with a
  yes/no eligibility check before applying.

The remaining phases are listed in the spec (§12.1).

## Who does what

Icebolethu has **Line Managers** and **Department Managers** (the system has no "HOD"):

- A Department Manager reports to their department's Line Manager, and Line Managers report to Exco.
- **Requisitions** are raised by Department Managers (and HR). Line Managers don't raise them; they see
  them and approve them.
- The finance role is called **Finance**.
- **Job grades** are Intern, Junior, Senior, Manager and Exco. Grades carry no salary: a requisition is costed
  from its position's **budgeted CTC** on the register (pro-rated by months for a contract), so every position
  needs a budgeted CTC before a requisition for it can be submitted. Positions CSV files give the grade by name.

**Approval chains** (defaults; IT can change them under **ICT → Routing Rules**):

| Request | Chain |
|---|---|
| Requisition | Department Manager of the position's department → the Line Manager above them → Finance → Group HR Manager → GCOO / Exco. A Department Manager raising it starts at their Line Manager. |
| Ad-hoc position, raised by a manager | Finance (unbudgeted) → GCOO / Exco |
| Ad-hoc position, raised by HR | Department Manager of the position's department → Finance (unbudgeted) → GCOO / Exco |
| Positions register (yearly) | Finance → Group HR Manager |
| Freeze / unfreeze / abolish / regrade | Finance → Group HR Manager |
| Job advert | HR Manager |

If nobody holds the role a step needs, the step goes to HR Admin (or, when HR Admin raised it, to their manager),
and the approval page says so. Nobody approves their own request: that step goes to their manager.

## Setup on Windows (VS Code terminal)

```powershell
py -3.11 -m venv .venv            # Python 3.11 or newer
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env            # then fill in SECRET_KEY and FERNET_KEY (commands are in the file)
$env:FLASK_APP = "run.py"
flask db upgrade                  # creates instance\hr.db
python seed.py --department-accounts   # departments, reference data and the department accounts (see below)
python run.py                     # http://127.0.0.1:5000
```

On macOS or Linux, use `python3 -m venv .venv`, then `source .venv/bin/activate`, then
`cp .env.example .env` and `export FLASK_APP=run.py`.

**Choosing what to seed** (run one of these on an empty database, after `flask db upgrade`):

| Command | What you get |
|---|---|
| `python seed.py --department-accounts` | No demo data. Departments, cost centres, the org structure, reference data and the [department accounts](#department-accounts). **The current dev database was built this way (31 Oct 2026).** |
| `python seed.py` | The full demo: budgets, the positions register, sample requisitions, an ad-hoc request, the JD library, a live advert with applicants, and the [test users](#test-users-full-demo-only). Add `flask import-legacy` for the old portal's jobs, CVs and applications. |
| `python seed.py --accounts-only` | Only the test users, departments and reference data, without the demo records. |

## Current dev database

`instance/hr.db` was reset on 31 Oct 2026 and holds no demo data: no budgets, positions, requisitions,
adverts, jobs, candidates or uploaded files. It has the departments, cost centres, org structure, reference data
(roles, grades, public holidays, approval chains, notification templates, settings) and the 35 department
accounts below. Before anyone can raise a requisition, Finance loads the **budget lines** and HR loads the
**approved positions register** (both accept CSV imports).

The previous databases and uploads are kept in `instance/backup-before-reset-2026-10-31/`.

## Links

With the app running (`python run.py`), every page is at `http://127.0.0.1:5000`. If port 5000 is busy,
`run.py` picks the next free port and prints it; use that port instead. "HR roles" means HR Admin, Group HR
Manager, HR Manager, HR Business Partner, Recruiter and HR OD.

**Sign-in (public)**

| Page | Address | Who can open it |
|---|---|---|
| [Staff self-service landing](http://127.0.0.1:5000/login/staff) | `/login/staff` | Employees |
| [Staff sign-in](http://127.0.0.1:5000/login/staff/sign-in) | `/login/staff/sign-in` | Employees |
| [Manager self-service landing](http://127.0.0.1:5000/login/manager) | `/login/manager` | Line managers, Department Managers |
| [Manager sign-in](http://127.0.0.1:5000/login/manager/sign-in) | `/login/manager/sign-in` | Line managers, Department Managers |
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
| [Requisitions](http://127.0.0.1:5000/requisitions/) | `/requisitions/` | Line Managers, Department Managers, HR, Finance, GCOO, Exco, Compliance |
| [New requisition](http://127.0.0.1:5000/requisitions/new) | `/requisitions/new` | Department Managers, HR |
| [Approved positions register](http://127.0.0.1:5000/positions/) | `/positions/` | Line Managers, Department Managers, HR, Finance, GCOO, Exco, Compliance |
| [Add a position](http://127.0.0.1:5000/positions/new) | `/positions/new` | HR Admin, Group HR, HR Manager, HRBP |
| [Import positions (CSV)](http://127.0.0.1:5000/positions/import) | `/positions/import` | HR Admin, Group HR, HR Manager, HRBP |
| [Positions CSV template](http://127.0.0.1:5000/positions/import/template.csv) | `/positions/import/template.csv` | HR Admin, Group HR, HR Manager, HRBP |
| [Vacancy dashboard](http://127.0.0.1:5000/positions/dashboard) | `/positions/dashboard` | Line Managers, Department Managers, HR, Finance, GCOO, Exco, Compliance |
| [Vacancy dashboard (Excel export)](http://127.0.0.1:5000/positions/dashboard?format=xlsx) | `/positions/dashboard?format=xlsx` | Line Managers, Department Managers, HR, Finance, GCOO, Exco, Compliance |
| [Ad-hoc position requests](http://127.0.0.1:5000/positions/ad-hoc) | `/positions/ad-hoc` | Line Managers, Department Managers, HR, Finance, GCOO, Exco, Compliance |
| [Request an ad-hoc position](http://127.0.0.1:5000/positions/ad-hoc/new) | `/positions/ad-hoc/new` | Line managers, Department Managers, HR |

**Budget**

| Page | Address | Who can open it |
|---|---|---|
| [Budget lines](http://127.0.0.1:5000/budget/) | `/budget/` | Finance, HR Admin, HR Manager, GCOO |
| [Add a budget line](http://127.0.0.1:5000/budget/new) | `/budget/new` | Finance, HR Admin |
| [Import budget (CSV)](http://127.0.0.1:5000/budget/import) | `/budget/import` | Finance, HR Admin |
| [Budget CSV template](http://127.0.0.1:5000/budget/import/template.csv) | `/budget/import/template.csv` | Finance, HR Admin |
| [Budget impact report](http://127.0.0.1:5000/budget/report) | `/budget/report` | Finance, HR Admin, HR Manager, GCOO |

**Recruitment (ATS)**

| Page | Address | Who can open it |
|---|---|---|
| [Recruitment dashboard](http://127.0.0.1:5000/recruitment/) | `/recruitment/` | HR roles |
| [Job adverts](http://127.0.0.1:5000/adverts/) | `/adverts/` | HR roles |
| [JD library](http://127.0.0.1:5000/adverts/library) | `/adverts/library` | HR roles |
| [Job openings](http://127.0.0.1:5000/recruitment/jobs) | `/recruitment/jobs` | HR roles |
| [New job opening](http://127.0.0.1:5000/recruitment/jobs/new) | `/recruitment/jobs/new` | HR roles |
| [CV database](http://127.0.0.1:5000/recruitment/candidates) | `/recruitment/candidates` | HR roles |
| [Shortlist reviews](http://127.0.0.1:5000/recruitment/shortlists) | `/recruitment/shortlists` | Department Managers |
| Interview invitations and regret letters | `/recruitment/jobs/<id>/messages` | HR roles |
| Interview panel (members, slots, criteria, invitations, results) | `/recruitment/jobs/<id>/panel` | HR roles |
| [Interviews to score](http://127.0.0.1:5000/recruitment/interviews) | `/recruitment/interviews` | Panel members (managers HR invites) |

**People and organisation (HR)**

| Page | Address | Who can open it |
|---|---|---|
| [Employees](http://127.0.0.1:5000/admin/employees) | `/admin/employees` | HR roles |
| [New employee](http://127.0.0.1:5000/admin/employees/new) | `/admin/employees/new` | HR roles |
| [Departments, Department Managers and cost centres](http://127.0.0.1:5000/admin/departments) | `/admin/departments` | HR Admin |
| [Business units, regions, branches, job families](http://127.0.0.1:5000/admin/org-structure) | `/admin/org-structure` | HR Admin |

**System administration (the sidebar's ICT menu, for the IT role)**

| Page | Address | Who can open it |
|---|---|---|
| [Approvals dashboard](http://127.0.0.1:5000/approvals/dashboard) | `/approvals/dashboard` | IT |
| [Users and roles](http://127.0.0.1:5000/admin/users) | `/admin/users` | IT |
| [New user](http://127.0.0.1:5000/admin/users/new) | `/admin/users/new` | IT |
| [Routing rules](http://127.0.0.1:5000/admin/rules) | `/admin/rules` | IT |
| [New routing rule](http://127.0.0.1:5000/admin/rules/new) | `/admin/rules/new` | IT |
| [Settings, holidays and notification templates](http://127.0.0.1:5000/admin/settings) | `/admin/settings` | IT |
| [Assets](http://127.0.0.1:5000/admin/assets) | `/admin/assets` | IT |
| [New asset](http://127.0.0.1:5000/admin/assets/new) | `/admin/assets/new` | IT |
| [Audit log](http://127.0.0.1:5000/admin/audit) | `/admin/audit` | IT, Compliance |
| [Integration log](http://127.0.0.1:5000/admin/integrations) | `/admin/integrations` | IT |

**Pages for one record** (open them from the lists above; replace `<id>` with the record's number):

| Address | Page |
|---|---|
| `/requisitions/<id>` and `/requisitions/<id>/edit` | A requisition, and editing a draft or returned one |
| `/positions/<id>` and `/positions/<id>/edit` | A position, and editing it |
| `/positions/ad-hoc/<id>/edit` | Changing a returned ad-hoc request |
| `/budget/<id>/edit` | A budget line |
| `/adverts/new/<requisition id>` | Create an advert from a fully approved requisition |
| `/adverts/<id>` and `/adverts/<id>/edit` | An advert (approval, channels, views and applications per channel, versions), and editing a draft or returned one |
| `/adverts/library/<id>/edit` | A job description in the JD library |
| `/recruitment/jobs/<id>`, `/recruitment/jobs/<id>/export.csv` | A job opening's ranked applicants, and as CSV |
| `/recruitment/jobs/<id>/edit` | Editing a job imported from the old portal (adverts are edited under `/adverts`) |
| `/recruitment/candidates/<id>` and `/recruitment/candidates/<id>/cv` | A candidate and their CV |
| `/admin/employees/<id>`, `/admin/users/<id>`, `/admin/rules/<id>`, `/admin/templates/<id>` | Employee, user, routing rule, notification template |
| `/admin/assets/<id>` | An asset, with its signed allocation form |
| `/jobs/<id>` | A vacancy on the public careers site, with step 1 of applying: five yes/no eligibility questions. A "No" sends the applicant to the talent pool page |
| `/jobs/<id>/apply` | Step 2 of applying: the application form (opens only after the eligibility check is passed) |
| `/files/<id>` | Download an attachment (permission checked) |

`/admin/login` and `/admin/` are old portal addresses; they redirect to the HR admin sign-in and the dashboard.

## Department accounts

These are the accounts in the current dev database. `python seed.py --department-accounts` creates them on an
empty database (after `flask db upgrade`). They all use the `SEED_PASSWORD` from `.env` (by default
`Icebolethu@Test2026`), and each email is `<username>@icebolethu.co.za`.

| Username | Role | Reports to | Signs in at |
|---|---|---|---|
| `exco` | GCOO and Exco | | [/login](http://127.0.0.1:5000/login) |
| `hradmin` | HR Admin | `exco` | [/login](http://127.0.0.1:5000/login) |
| `grouphr` | Group HR Manager | `exco` | [/login](http://127.0.0.1:5000/login) |
| `finance` | Finance | `exco` | [/login](http://127.0.0.1:5000/login) |
| `it` | IT (the ICT menu) | `exco` | [/login](http://127.0.0.1:5000/login) |
| `lm.<dept>` | Line Manager | `exco` | [/login/manager](http://127.0.0.1:5000/login/manager) |
| `dm.<dept>` | Department Manager: heads the department and raises its requisitions | the department's `lm.` account | [/login/manager](http://127.0.0.1:5000/login/manager) |
| `dm.hr` | Department Manager of HR **and HR Manager** (approves job adverts) | `lm.hr` | [/login](http://127.0.0.1:5000/login) (HR admin portal) |

`<dept>` is one of: `hr`, `finance`, `sales`, `operations`, `catering`, `burials`, `ict`, `facilities`, `fleet`,
`security`, `marketing`, `foundations`, `cleaning`, `risk`, `itravel`. For example, `dm.catering` and
`lm.catering`. Every account also has the Employee role.

- **Placeholder names:** the accounts have names like "Catering Department Manager". IT can change names
  and emails in Users & Roles once real people are known.
- **Shared password:** every account shares one password. Change the passwords before real people use the
  system, with `flask set-password <username>`, or let each person use **Change password**.
- **Missing roles:** there are no Recruiter, Payroll or Compliance accounts
  yet. IT creates them in Users & Roles when they're needed. Until then, approval steps for those roles go
  to `hradmin`.

**Signing in:** use your own sign-in page (see Links): staff, managers, or the HR admin portal for HR,
Finance, IT and Exco. Signing in on another group's page sends you to your own. Type either the username or
the email address, plus the password. The "Continue with Microsoft" button is a placeholder. The system will
move to Microsoft single sign-on (Entra ID), which also provides two-step verification, so this system has no
two-step sign-in of its own.

## Test users (full demo only)

These accounts exist only after the full demo seed (`python seed.py` or `python seed.py --accounts-only`).
**They are not in the current dev database.** The automated tests create their own copies. **Development and
testing only:** never create these accounts on a production server.

**Password for every test user: `Icebolethu@Test2026`**

This is the default `SEED_PASSWORD` in `.env.example`. If you change `SEED_PASSWORD` in `.env`
before running `seed.py`, use your value instead.

| Username | Email | Password | Role | Department |
|---|---|---|---|---|
| `employee` | `employee@icebolethu.test` | `Icebolethu@Test2026` | Employee | Sales |
| `linemanager` | `linemanager@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Sales |
| `hod` | `hod@icebolethu.test` | `Icebolethu@Test2026` | Department Manager | Sales |
| `panel` | `panel@icebolethu.test` | `Icebolethu@Test2026` | Panel Member | Sales |
| `hrbp` | `hrbp@icebolethu.test` | `Icebolethu@Test2026` | HR Business Partner | HR |
| `recruiter` | `recruiter@icebolethu.test` | `Icebolethu@Test2026` | Recruiter | HR |
| `hrod` | `hrod@icebolethu.test` | `Icebolethu@Test2026` | HR OD | HR |
| `hrmanager` | `hrmanager@icebolethu.test` | `Icebolethu@Test2026` | HR Manager | HR |
| `grouphr` | `grouphr@icebolethu.test` | `Icebolethu@Test2026` | Group HR Manager | HR |
| `hradmin` | `hradmin@icebolethu.test` | `Icebolethu@Test2026` | HR Admin | HR |
| `finance` | `finance@icebolethu.test` | `Icebolethu@Test2026` | Finance | Finance |
| `payroll` | `payroll@icebolethu.test` | `Icebolethu@Test2026` | Payroll | Finance |
| `it` | `it@icebolethu.test` | `Icebolethu@Test2026` | IT | Operations |
| `assets` | `assets@icebolethu.test` | `Icebolethu@Test2026` | Asset Controller | Operations |
| `compliance` | `compliance@icebolethu.test` | `Icebolethu@Test2026` | Compliance | Operations |
| `gcoo` | `gcoo@icebolethu.test` | `Icebolethu@Test2026` | GCOO | Operations |
| `exco` | `exco@icebolethu.test` | `Icebolethu@Test2026` | Exco | Operations |
| `lm.catering` | `lm.catering@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Catering |
| `lm.burials` | `lm.burials@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Burials |
| `lm.ict` | `lm.ict@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | ICT |
| `lm.finance` | `lm.finance@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Finance |
| `lm.facilities` | `lm.facilities@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Facilities |
| `lm.fleet` | `lm.fleet@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Fleet |
| `lm.security` | `lm.security@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Security |
| `lm.marketing` | `lm.marketing@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Marketing |
| `lm.foundations` | `lm.foundations@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Foundations |
| `lm.hr` | `lm.hr@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | HR |
| `lm.cleaning` | `lm.cleaning@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Cleaning |
| `lm.risk` | `lm.risk@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | Risk & Compliance |
| `lm.itravel` | `lm.itravel@icebolethu.test` | `Icebolethu@Test2026` | Line Manager | iTravel |

Every test user also has the Employee role.

**Reporting lines in the demo** (these predate the Line Manager / Department Manager order and are kept for
the demo data):
- Sales: `employee` → `linemanager` → `hod` → `gcoo`
- HR: `hrbp`, `recruiter`, `hrod` and `hradmin` → `hrmanager` → `grouphr` → `gcoo`
- Finance: `payroll` → `finance` → `gcoo`
- Operations: `it`, `assets` and `compliance` → `gcoo`
- Department line managers: `lm.hr` → `hrmanager`, `lm.finance` → `finance`, the rest → `gcoo`. The newer
  departments (Catering, Burials, ICT, Facilities, Fleet, Security, Marketing, Foundations, Cleaning,
  Risk & Compliance, iTravel) have no Department Manager user yet, so `gcoo` is their Department Manager.

**Old portal login:** `flask import-legacy` also brings across the old portal's `admin` login. It keeps its
old password, which is upgraded to argon2 at first sign-in, and gets the HR Admin and Recruiter roles.

## Walkthrough (current dev database)

1. **Budget:** sign in as `finance` at [/login](http://127.0.0.1:5000/login) and open **Budget Lines**. Add a line
   for each cost centre, or import them from CSV (the template is on the import page).
2. **Positions:** sign in as `hradmin` and open **Approved Positions**. Add positions, or import the register
   from CSV, and click **Send register for approval** (Finance → Group HR Manager, `grouphr`). Once it's approved,
   its positions become vacant or filled.
3. **Raise a requisition:** sign in as a Department Manager, for example `dm.sales` at
   [/login/manager](http://127.0.0.1:5000/login/manager), and open **Requisitions → New Requisition**. Choose
   a vacant position: the title, department, cost centre, grade and New / Replacement fill in from it. Choose
   the employment type and a start date; the budget check shows the CTC (the position's budgeted CTC) and the
   budget available. Click
   **Submit for approval**. Line Managers can't raise requisitions; their home page shows
   **Team requisitions** instead.
4. **Approve it:** sign in as `lm.sales` (the Department Manager's Line Manager), then `finance`, `grouphr`
   and `exco`, and open **My Approvals** each time. Approve,
   return or reject. Approving needs no comment; returning or rejecting asks for a reason. Returning a requisition sends it back to the
   originator, and resubmitting restarts the chain at level 1.
5. When the final level approves, the CTC is committed against the cost centre (see **Budget Lines** as
   `finance`) and the position moves to "In recruitment". Closing the requisition unfilled releases the
   commitment and makes the position vacant again.
6. **Ad-hoc positions:** a position that isn't on the register needs an **ad-hoc position request** first
   (**Ad-hoc Positions → Request a position**). A request from `lm.catering` goes to `finance`, then `exco`. A request
   from `hradmin` for a Catering position goes to `dm.catering` first, then `finance`, then `exco`.
7. **Vacancy Dashboard** (as `hradmin`, `finance` or a manager) groups vacancies by business unit, branch,
   region and more, and exports to Excel.
8. **Approvals → Delegation** sends your approvals to someone else for a date range.
   `flask run-sla-checks` sends reminders after 24 business hours and escalates any step past its
   SLA to the approver's manager.
9. **Advertising an approved requisition:** open **Job Adverts** as an HR user. Approved requisitions are
   listed under "Ready to advertise". **Create advert** drafts it from the requisition, its position (title,
   location, minimum requirements) and the matching JD library entry. Check it, choose channels and
   **Save and send for approval**. The HR Manager (`dm.hr`) approves it from **My Approvals**: it goes live on
   the careers site and the chosen channels, and the requisition moves to "Advertised". Links on job portals add
   `?src=LinkedIn` (the channel's name) so views and applications are counted per channel. Create the advert as
   `hradmin` (or another HR user), because no one can approve their own advert.
10. **Shortlist and interviews:** as HR, open the advert under **Job Openings**, move the strongest applicants to
    **Shortlisted** and click **Send shortlist to …** (the Department Manager of the advert's department, e.g.
    `dm.ict`). The Department Manager sees it under **Shortlist Reviews** (and on their home page), opens the CVs,
    ticks who goes to interview and sends the selection to HR. Picked applicants move to **Interview**, the rest
    to **Not selected**, and HR is notified. HR then clicks **Interview invitations** (enter date, time and venue)
    and **Regret letters** on the advert to email the applicants; regrets mark them **Rejected**, and every email
    is kept on the application.
11. **Interview panel and scoring:** on the advert, click **Interview panel**. The Department Manager is already on
    it; invite more managers from the business (managers only), give each candidate a date, time and venue, adjust
    the scoring criteria if needed (weights total 100), and click **Send invitations**. Panellists get a
    notification, an email and a calendar invite, and the candidates get their interview invitation. Each panellist
    opens **Interviews to score** (or the task on their home page), reads the CV and, after the interview, scores
    every criterion 1–5 with a recommendation. They see the other scores only after submitting their own. The panel
    page ranks the candidates by the panel's combined score.

## Scheduled jobs

Run these with Windows Task Scheduler or cron, from the project folder with the venv active:

| Command | When |
|---|---|
| `flask run-sla-checks` | Hourly during business hours |
| `flask close-expired-adverts` | Daily, just after midnight |
| `flask remind-jd-reviews` | Daily |

## Commands

| Command | Purpose |
|---|---|
| `flask db upgrade` | Create or upgrade the database schema |
| `python seed.py --department-accounts` | Departments, reference data and the department accounts, with no demo data (how the current dev database was built) |
| `python seed.py` | The full demo data and test users. Safe to run again. |
| `python seed.py --accounts-only` | The test users, departments and reference data only |
| `python seed_ict_demo.py` | Dummy ICT recruitment data: 30 open ICT adverts (with positions and requisitions), 150 applicants, about 385 applications; the first 10 adverts have 3 shortlisted applicants each. Needs the department accounts. |
| `python seed_ict_demo.py --remove` | Delete exactly the ICT dummy data |
| `flask import-legacy [--path portal.db]` | Copy the original portal's data. Safe to run again. |
| `flask set-password <username>` | Reset a user's password |
| `flask reprocess-cvs` | Re-read every CV and re-score every application |
| `python -m pytest --cov=app/services` | Tests with coverage |

## Project layout

```
app/
  models/         one file per domain (org, user, system, workflow, budget, requisition, recruitment)
  services/       business rules: workflow engine, budget, requisitions, audit, notifications, calendar,
                  references, files, positions register, adverts, ATS scoring (ats.py), careers
  integrations/   interface + Mock* adapter per external system (payroll, ERP, AD, LMS, job portals...)
  auth/ admin/ portal/ dashboards/ requisitions/ positions/ approvals/ budget/ adverts/ recruitment/   one Blueprint each
  templates/ static/   shared layout and the one stylesheet (IGSP admin look for staff pages)
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

These are the standard weights. Each job description in the **JD Library** can set its own (they must add up to
100; 0 leaves a part out), and an advert drafted from it scores its applicants with those weights. Criteria left
blank on a job are skipped, and the remaining weights are rescaled to 100%.

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
