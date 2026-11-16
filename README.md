# ICE People Administration System

Icebolethu Group's people administration system: recruitment, onboarding, the approved positions register,
headcount budgets, approvals and travel requests, in one Flask application.

It combines the original recruitment portal (careers site, ATS and CV database) with the HR modules in the build
specification (`docs/SPEC.md`, kept outside the repository). The staff pages follow the layout, design and colours
of the IGSP (Icebolethu Group Supplier Portal) admin area, with a light and a dark mode. The public careers site
keeps the Icebolethu Group name and its own layout.

## What's built

**Platform**
- Sign-in pages for staff, managers and the HR admin portal, each with its own home page. Everyone can also use
  the staff portal and switch between portals from the sidebar.
- Roles, the audit log, notifications (in the app and by email), the business-day calendar, the approval
  workflow engine (delegation, SLA reminders and escalation), and the **My Approvals** inbox.
- Designed emails for applicants and staff that work on phones. Live sending uses SMTP in the background.
- Light and dark mode per account (**My Profile → Appearance**).

**Workforce planning**
- **Approved positions register:** one record per position, yearly approval of the register, ad-hoc position
  requests, freeze, abolish and regrade, and a vacancy dashboard with Excel export. Each department has its own
  **HR Business Partner**, who maintains that department's positions.
- **Headcount budget:** budget lines per cost centre (CSV import), costed from each position's budgeted CTC, with
  commitments and an overspend alert.
- **Requisitions** raised from a vacant position, with a budget check and the approval chain below.

**Recruitment**
- **Job adverts** drafted from approved requisitions and the **JD library**. The HR Manager approves them before
  they're published to the careers site and job-portal channels, with views and applications counted per channel.
- **Careers site:** typed yes/no eligibility questions per advert, then the application form. It asks for a full
  profile (names, ID or passport, address, notice period, salary, driver's licence and voluntary employment-equity
  details) plus the required documents and the CV, with key skills one per row.
- **ATS scoring** of every application, with standard or per-JD weights.
- **Shortlist review** by the Department Manager, then interview invitations and regret letters.
- **Interview panels:** the Department Manager and the Talent Acquisition Specialist, plus invited managers. They
  score typed interview questions 1–5, blind until each has submitted, and the candidates are ranked.

**Hiring and onboarding**
- **Background checks** before any offer. The candidate consents online (Icebolethu's POPIA consent form) and
  uploads the signed MIE form. HR Admin or the department's HR BP records each result once, and it can't be edited
  afterwards. The offer can only be sent when every check is clear.
- **Offers:** an offer letter on the Icebolethu letterhead. Finance approves any offer above the costed CTC. The
  candidate accepts online, which includes accepting the Code of Conduct and attaching the onboarding documents
  (anything already sent with the application isn't asked for again).
- **Acceptance** fills the position, consumes the budget, closes the advert, creates the employee record
  (Pre-boarding, next ICE number) and opens an onboarding case.
- **New starter pack:** a secure link where the new starter fills in the New Hire Take-On form online and uploads
  the Business and Financial Disclosure and the Liberty nomination of beneficiary. HR Admin or the HR BP approves it
  (it's also in My Approvals), which updates the employee record. The HR BP attaches the signed contract.
- **Employee record:** every document from the application, checks, offer, onboarding and assets, opened in an
  on-page viewer.

**Other**
- **Travel requests** (the i-Travel form): approved by the requester's manager, booked by i-Travel, paid by Finance.
- **Asset register** (IT), with signed allocation forms.

The remaining phases (references to referees, the new-starter portal, Performance Management, Sage 300 posting,
off-boarding and more) are in the spec's release plan.

## Who does what

- **Line Managers and Department Managers** (there's no "HOD"): a Department Manager heads a department and reports
  to a Line Manager, and Line Managers report to Exco. Department Managers and HR raise requisitions; Line Managers
  see and approve them.
- **HR Admin** runs onboarding: offers, cases, employee numbers, the offer letter wording, and the forms and
  document lists.
- **HR Business Partner:** one per department (HR Admin assigns them on the Departments page). They maintain the
  department's positions, run its background checks, review new starter packs and attach signed contracts.
- **Group HR Manager:** the head of the HR department. Every "Group HR Manager" approval goes to that person.
- **HR Manager** approves job adverts.
- **Talent Acquisition Specialist:** a recruitment-only role covering adverts, the JD library, candidates and
  interview panels. They score on every panel.
- **Finance** approves budgets, requisitions, unbudgeted positions, offers above the costed CTC and travel payments.
- **i-Travel** books approved travel requests.
- **IT** runs system administration (the sidebar's ICT menu): users and roles, routing rules, settings, templates,
  assets, the audit log and the integration log.
- **Occupational levels** (job grades): 1 Support / Unskilled Staff, 2 Skilled Staff / Technical / Junior
  Management / Supervisor, 3 Professional / Experienced / Specialists / Mid-Management, 4 Senior Management,
  5 Top Management. They carry no salary: requisitions are costed from the position's budgeted CTC.

**Approval chains** (defaults; IT changes them under **ICT → Routing Rules**):

| Request | Chain |
|---|---|
| Requisition | Department Manager (only when HR raised it) → the Department Manager's Line Manager → Finance → Group HR Manager → GCOO / Exco |
| Ad-hoc position | Department Manager (only when HR raised it) → Finance (unbudgeted) → GCOO / Exco |
| Positions register (yearly) | Finance Department Manager → Group HR Manager |
| Freeze, unfreeze, abolish, regrade | Finance → Group HR Manager |
| Job advert | HR Manager |
| Offer above the costed CTC | Finance |
| Travel request | The requester's manager; then i-Travel books it and Finance approves the payment |
| Background check results, new starter pack | HR Admin or the department's HR Business Partner (not a workflow chain) |

If nobody holds the role a step needs, the step goes to HR Admin (or, when HR Admin raised it, to their manager).
Nobody approves their own request: that step goes to their manager.

## Hiring, step by step

1. **Advertise:** HR or the Talent Acquisition Specialist creates an advert from an approved requisition under
   **Job Adverts**, types its eligibility questions and sends it to the HR Manager. Approved, it goes live.
2. **Apply:** the applicant answers the eligibility questions, then fills in the application form. A wrong answer
   sends them to the talent pool page instead.
3. **Shortlist:** HR shortlists the strongest applicants and sends them to the Department Manager, who picks who
   goes to interview and types the interview questions. HR emails invitations and regrets.
4. **Interview:** HR sets up the panel and the slots and sends the invitations. Each panellist scores the questions
   after the interview, and HR marks the best candidate **successful**.
5. **Background checks:** HR Admin or the HR BP starts them on the **Onboarding** page. The candidate consents
   online, then the results are recorded as they come in from MIE.
6. **Offer:** HR Admin prepares it (Finance approves it if it's above the costed CTC) and sends it once every check
   is clear. The candidate accepts or declines online.
7. **Onboarding:** acceptance opens the onboarding case and the employee record. The new starter completes their
   pack, HR Admin or the HR BP approves it, and the HR BP attaches the signed contract.

## Setup for development

Python 3.11 or newer. On Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env            # then fill in SECRET_KEY and FERNET_KEY (the commands are in the file)
$env:FLASK_APP = "run.py"
flask db upgrade                  # creates instance\hr.db (SQLite)
flask seed-reference-data         # roles, occupational levels, holidays, approval chains, settings, templates
flask create-user it --email it@icebolethu.co.za --name "IT Administrator" --role IT
python run.py                     # http://127.0.0.1:5000
```

On macOS or Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, `cp .env.example .env` and
`export FLASK_APP=run.py`.

Then sign in as that IT user at `/login` and add the departments (HR Admin's **Departments** page), people and
roles (**Users & Roles**). The demo and dummy-data scripts (`seed.py`, `seed_ict_demo.py`, `seed_jd_library.py`,
`seed_staff_details.py`) are kept on the development machine only and aren't in this repository.

`.env.example` lists every setting for development, including live email (`MAIL_PROVIDER=smtp`).

## Production

Production runs on **PostgreSQL** with files in a private **Amazon S3** bucket. Copy
[`.env.production.example`](.env.production.example) to `.env` on the server and fill in every `CHANGE_ME`. It
explains each setting. In short:

```bash
pip install -r requirements.txt     # includes psycopg (Postgres), boto3 (S3) and gunicorn
flask db upgrade                    # creates the tables in Postgres
flask seed-reference-data
flask create-user ictadmin --email ict@icebolethu.co.za --name "ICT Administrator" --role IT
gunicorn --workers 3 --bind 127.0.0.1:8000 run:app
```

- **Database:** `DATABASE_URL=postgresql+psycopg://…?sslmode=require`. The migrations haven't been run on
  Postgres yet, so run `flask db upgrade` on a staging database first.
- **Files:** `FILE_STORAGE=s3` with `S3_BUCKET` (region `af-south-1` by default). Every upload and generated PDF is
  stored there, encrypted at rest. Keep the bucket private: people download through the app, which checks their
  permissions. Give the server an IAM role rather than access keys. `flask upload-files-to-s3` copies existing
  files from a server's disk once.
- **Behind a load balancer or nginx:** set `PROXY_FIX_HOPS` (usually 1) so the app sees real client IPs and HTTPS,
  and `SESSION_COOKIE_SECURE=1`.
- **Encryption key:** `FERNET_KEY` encrypts ID numbers, bank details and Take-On forms. Keep it in a secrets vault;
  moving existing data needs the same key.
- **Email:** use a company mailbox and leave `EMAIL_COPY_TO` empty (emails carry personal information).
- Production always runs with the debugger off.

## Scheduled jobs

Run these with cron or Windows Task Scheduler, from the project folder with the virtual environment active:

| Command | When |
|---|---|
| `flask run-sla-checks` | Hourly during business hours: approval reminders and escalations |
| `flask close-expired-adverts` | Daily, just after midnight |
| `flask expire-offers` | Daily: offers past their answer-by date lapse |
| `flask remind-jd-reviews` | Daily |

## Commands

| Command | Purpose |
|---|---|
| `flask db upgrade` | Create or upgrade the database schema |
| `flask seed-reference-data` | First-time setup of a new database. Safe to run again: it only adds what's missing |
| `flask create-user <username> --email … --name … --role …` | Create an account (repeat `--role` for several) |
| `flask set-password <username>` | Reset a user's password |
| `flask upload-files-to-s3 [--from-folder …]` | Copy stored files from disk to the S3 bucket |
| `flask reprocess-cvs` | Re-read every CV and re-score every application (after ATS changes) |
| `flask send-test-email --to <address>` | Check the email settings |
| `flask send-email-samples --to <address>` | Email one filled-in sample of every email template |
| `flask import-legacy [--path portal.db]` | Copy the original recruitment portal's data, if you have its `portal.db` |
| `python -m pytest --cov=app/services` | The tests, with coverage (the test files are kept on the development machine) |

## Main pages

With the app running locally, every page is at `http://127.0.0.1:5000` (if port 5000 is busy, `run.py` picks the
next free one and prints it).

| Area | Address | Who |
|---|---|---|
| Sign-in: staff, managers, HR admin portal | `/login/staff`, `/login/manager`, `/login` | Everyone, on their own page |
| Careers site, talent pool, application status | `/`, `/talent-pool`, `/status` | Public |
| Dashboard, My Approvals, delegation | `/dashboard`, `/approvals/`, `/approvals/delegations` | All staff |
| My Profile (with Appearance), notifications, password | `/me`, `/notifications`, `/account` | All staff |
| Requisitions | `/requisitions/` | Managers, HR, Finance, GCOO, Exco |
| Approved positions, ad-hoc requests, vacancy dashboard | `/positions/`, `/positions/ad-hoc`, `/positions/dashboard` | Managers, HR, Finance, GCOO, Exco |
| Budget lines and report | `/budget/`, `/budget/report` | Finance, HR |
| Job adverts and JD library | `/adverts/`, `/adverts/library` | HR, Talent Acquisition |
| Recruitment: openings, CV database, shortlists, interviews | `/recruitment/` | HR, Talent Acquisition; Department Managers for shortlists; panellists for scoring |
| Onboarding: background checks, offers, new starters, letter and forms | `/onboarding` | HR Admin, HR Manager, Group HR; HR BPs for their departments |
| Employees, departments, org structure | `/admin/employees`, `/admin/departments`, `/admin/org-structure` | HR |
| Travel requests and the i-Travel dashboard | `/travel`, `/travel/dashboard` | All staff; i-Travel and Finance |
| System administration (ICT menu) | `/admin/users`, `/admin/rules`, `/admin/settings`, `/admin/assets`, `/admin/audit` | IT (Compliance: audit log) |

**Links candidates get by email** (secure, single-purpose; they stop working once used):

| Link | Purpose |
|---|---|
| `/background-checks/<token>` | Give or refuse consent to the background checks and upload the MIE form |
| `/offer/<token>` | Read the offer letter, accept (documents and Code of Conduct) or decline |
| `/new-starter/<token>` | The new starter pack: the Take-On form and the forms to upload |

## Project layout

```
app/
  models/         one file per domain (org, user, system, workflow, budget, requisition, recruitment,
                  onboarding, travel)
  services/       business rules: workflow engine, budget, requisitions, positions, adverts, ATS scoring (ats.py),
                  careers, interviews, shortlisting, screening (background checks), onboarding, starter pack,
                  candidate forms, documents (letters), emails, files (local disk or S3), travel, audit...
  integrations/   an interface and a mock adapter per external system (payroll, ERP, AD, LMS, job portals,
                  screening...); email has a live SMTP adapter
  auth/ admin/ portal/ dashboards/ requisitions/ positions/ approvals/ budget/ adverts/ recruitment/
  onboarding/ travel/                                    one Flask blueprint each
  templates/      pages, emails (email/) and letters (documents/)
  static/         the one stylesheet (style.css), images, js/ (the document viewer) and forms/ (the blank
                  forms candidates download; HR Admin can replace them)
migrations/       Alembic migrations (flask db upgrade)
run.py            development server and the WSGI app for gunicorn (run:app)
```

## How the ATS score works (`app/services/ats.py`)

| Component | Standard weight | How it's measured |
|---|---|---|
| Required skills | 45% | Share of the advert's required skills found in the CV, the skills and the job title |
| Preferred skills | 15% | Share of the preferred skills found |
| Experience | 20% | Stated years (or years found in the CV) against the minimum |
| Education | 10% | Highest qualification (stated or found in the CV) against the minimum |
| Job-description fit | 10% | Overlap with the key terms of the job title and description |

Each JD in the library can set its own weights (they must add up to 100; 0 leaves a part out), and adverts drafted
from it use them. Parts that don't apply to an advert are skipped and the rest are rescaled to 100%.

Skills match their common variants and synonyms (for example "Office 365" and "Microsoft 365"), and a skill of two
to four words also counts when its words appear close together in one sentence or line. Requirements written as
sentences (pasted from a JD) are split into separate requirements. Scanned CVs with no text can't be read (there's
no OCR).

## Security and data protection (POPIA)

- **Sign-in:** argon2-hashed passwords, rate-limited sign-in attempts, and every failed sign-in in the audit log.
  Sign-in will move to Microsoft single sign-on (Entra ID), which also provides two-step verification.
- **Sessions and forms:** sessions time out after 30 minutes idle, and every form is protected against CSRF.
- **Encryption:** ID numbers, bank details and the Take-On form are encrypted at rest with `FERNET_KEY`. Without
  that key they can't be read, so back it up.
- **Files** are stored under random names on disk or in a private S3 bucket. Only PDF, DOCX, XLSX, JPG and PNG up
  to 10 MB are accepted, and permission is checked on every download.
- **Employment-equity details** asked of applicants are voluntary ("Prefer not to say"), never used in scoring and
  not shown to shortlisting or the interview panel.
- **Consent:** applicants consent to POPIA when applying, and candidates consent separately to background checks.
- **Audit log:** append-only. It records sign-ins, every change (before and after), approvals, file access and
  configuration changes.
- **Secrets** come only from `.env`, which is never committed.
- **Hosting:** keep the application, database, files and backups in South Africa (AWS `af-south-1`).
- **Backups:** database snapshots with point-in-time recovery (RPO ≤ 1 hour, RTO ≤ 4 hours), S3 versioning on the
  files bucket, and the `.env` secrets in a vault. Test a restore every quarter.
