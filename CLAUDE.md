# ICE People Administration System (Icebolethu Group)

## Requirements
The build specification is [docs/SPEC.md](docs/SPEC.md) (HR Automation System, from BRD v1.0).
§15 (added 28 Oct 2026) holds the IcePeople infographic requirements (portals, approved positions, careers
eligibility check, one identity, AI assistant, Performance Management, Sage 300, WhatsApp, release plan).
Its §15.12 open decisions must be settled before the phases they affect.
Read it in full before any build work and follow its §0 process:
- Work one phase at a time, in the §12.1 order (by release).
- Before each phase, read the code, run the tests, give a plan, and wait for approval.
- Finish each phase with passing tests and the §14 definition of done.
- Don't add anything outside the spec without asking.

## Current state
- Phases 1–5 are done (Phase 5: job adverts, JD library and publishing, 29 Oct 2026). Phase 6 (careers page,
  candidate accounts, applications, shortlisting, interviews and scorecards, §12.1) is next; §15.12 decision 3
  (candidate sign-in) must be settled first. Its shortlist review was built first, on 1 Nov 2026 at the user's
  request (`app/services/shortlisting.py`): HR sets applications to Shortlisted and sends them
  (`send_to_department_manager`) to the Department Manager of the advert's requisition department, who picks
  who goes to interview on `/recruitment/shortlists/<id>` (picked → Interview, the rest → "Not selected"); HR is
  notified and emails interview invitations (date, time, venue) or regrets (→ Rejected) from
  `/recruitment/jobs/<id>/messages`, using the editable templates `candidate_interview_invite` and
  `candidate_regret`. Models: `ShortlistReview`, `CandidateMessage`.
  Interview panels and scorecards were next (1 Nov 2026, approved plan; `app/services/interviews.py`): one panel
  per advert (`InterviewPanel`), starting with the Department Manager; HR invites managers only (`PANEL_ROLES`: Line
  Manager, Department Manager, HR Manager, Group HR, GCOO, Exco) on `/recruitment/jobs/<id>/panel`, sets each
  Interview candidate's slot (`InterviewSlot`, with the .ics from the calendar adapter) and the criteria (1–8,
  weights total 100, locked once scoring starts), then sends the invitations (panel notification + email; candidates
  get the invitation email from their slot). Panellists (any role, membership checked) score on
  `/recruitment/interviews/<app_id>` (1–5 per criterion, comment, recommendation; one `Scorecard` each, final) and
  see the others' scores only after submitting; HR always sees them. Results rank by the panel's average weighted
  score; HR is notified when the whole panel has scored a candidate. Still to come in Phase 6: offers, references and
  screening, candidate accounts.
- The app factory is `app/__init__.py`, with one blueprint per module.
- Business rules live in `app/services/`. Reuse these rather than adding parallel versions:
  - `workflow.py`: the generic approval engine. New workflow types call `workflow.register(...)`.
  - `errors.py`: `StateMachine` and `DomainError`.
  - `audit.record`, `notifications.notify` and `files.store_bytes` / `files.register_access`.
  - `calendar.add_business_days` and `refs.next_reference`.
  - `positions.py`: the approved positions register. Every requisition is raised from a vacant position
    (`positions.requisition_problems`); position status moves automatically through `start_recruitment`,
    `stop_recruitment` and `employee_changed`. Later phases set Filled on offer acceptance (Phase 7) and
    Vacant on exit (Phase 11) through the same functions.
    Ad-hoc position chains (31 Oct 2026, at the user's request; replaces §15.3's line manager → Finance → Group HR →
    Exco): raised by a manager, Finance → GCOO/Exco; raised by HR (`user.is_hr`), Department Manager → Finance →
    GCOO/Exco. The workflow context carries `raised_by` ("HR"/"Manager"), and the first rule's condition is
    `raised_by == "HR"`. The Department Manager (`@department_manager`) is the head of the position's department
    (`Department.hod`).
    The organisation has Line Managers and Department Managers, not HODs: the role formerly named "HOD" is
    "Department Manager" since 31 Oct 2026 (the constant is still `HOD` in code; migration `d91f5b3c7e20`). In this
    organisation a Department Manager reports to a Line Manager, and Line Managers report to Exco. Only Department
    Managers and HR raise requisitions (`requisitions.CREATE_ROLES`); Line Managers see and approve them, and their
    portal home shows "Team requisitions" instead of "Raise a requisition".
    A Department Manager's ad-hoc request (non-HR, `positions.ad_hoc_department`) is pre-filled and locked
    (`ad_hoc_defaults`): department locked to theirs (the service rejects others); cost centre their own;
    job family the department default (`Department.job_family_id`, set on the Departments page); "Reports to"
    locked to their own position (`ad_hoc_reports_to`, forced server-side; blank until they hold a position on the
    register). HR chooses all of these freely. The requisition form's position summary shows the job family.
  - Job grades (31 Oct 2026, at the user's request): Intern, Junior, Senior, Manager, Exco (`JobGrade.grade` is the
    rank 1–5, used in routing conditions; screens show the name). Grades carry **no salary**: the band columns,
    the Salary Bands page and the `casual_default_hours` setting are gone (migration `e2a7c9d14b38`; old grades
    mapped 1–3 Junior, 4–7 Senior, 8–11 Manager, 12 Exco). `budget.calculate_ctc(position, …)` costs a
    requisition from the position's `budgeted_ctc` (Contract pro-rated by months; Permanent and Casual as is) and
    refuses a position with none. The demo seed prices its positions with `DEMO_CTC` by grade.
    Exception (31 Oct 2026, the user's choice): an **unbudgeted ad-hoc position** (`budget.is_unbudgeted`: ad hoc,
    no budgeted CTC, approved by Finance as such) gets `calculate_ctc` = None; its requisition has `ctc` None, is
    never over budget, commits nothing (`budget.commit` skips it), and the form shows `budget.UNBUDGETED_NOTE`.
    HR (`positions.EDIT_ROLES`) can edit a position's job grade and budgeted CTC at any stage except Abolished /
    Rejected, an ad-hoc request in approval included (`positions.HR_EDITABLE`); department and cost centre stay
    fixed once approved. The regrade approval still exists for a formal regrade.
    "Reports to" defaults to the department's Department Manager: `positions.department_manager_position`
    (the position held by `Department.hod`) fills an empty reports-to on create_planned and HR's ad-hoc requests,
    and the position form selects it when the department changes (HR may override). It needs the Department
    Manager to hold a position on the register (none do in the current dev DB yet). The form also picks a
    department's only cost centre and its default job family.
    Requisition chain (31 Oct 2026, migration `a6c1e4f87d23`): 1 Department manager (`@department_manager`, only
    when `raised_by == "HR"`) → 2 Line manager (`@department_line_manager`: the manager of the department's
    Department Manager, else the originator's manager) → 3 Finance → 4 Group HR Manager → 5 GCOO / Exco. The context
    carries `raised_by`. A step with no approver goes to HR Admin, or, when HR Admin raised it, to the originator's
    manager. REQ-2026-00001 was re-routed to this chain (round 2) on 31 Oct 2026. Test fixtures follow the org order:
    employee → hod (Department Manager) → linemanager → gcoo.
    The finance role is "Finance" (`FINANCE`), renamed from the spec's "Finance / Budget Controller" on 31 Oct 2026:
    the organisation has no budget controller. Use "Finance" in new rules, steps and text.
  - `adverts.py`: job adverts. A `Job` with a `reference` (ADV-…) is an advert; jobs imported from the old portal
    have none. Only Approved requisitions can be advertised (`draft_from_requisition`, one active advert each),
    drafted from the position and the JD library (`JobDescriptionTemplate`, matched by title then job family).
    Draft/Returned → In Approval (workflow type `advert`, default rule: HR Manager) → Open (`publish`: careers
    site plus mock job-portal channels as `AdvertPosting` rows; requisition → Advertised) → Closed (`close`,
    `close_expired`) → Draft again via `readvertise` (cycle + 1). ATS weights per JD (1 Nov 2026, at the user's
    request): `JobDescriptionTemplate.ats_weights` (None = standard `ats.WEIGHTS`; validated by `ats.parse_weights`,
    total 100, 0 drops a part) is copied to `Job.ats_weights` when the advert is drafted; `ats.score_candidate` uses
    `ats.weights_for(job)`. Saves keep `AdvertVersion`s. Careers links
    tagged `?src=<channel>` count views and applications per channel and set `Application.source`.
- **ICT owns system admin** (29 Oct 2026, at the user's request): the sidebar's "ICT" group (Approvals Dashboard,
  Users & Roles, Routing Rules, Settings with holidays and templates, Assets, Audit Log, Integration Log) is for the
  IT role only; HR Admin and HR Manager lost it. Compliance keeps Audit Log. HR Admin keeps Departments and Org Structure.
  Assets (`/admin/assets`, built early at the user's request) is the asset register: IT issues, edits and marks assets
  Returned or Lost (`ASSET_STATUSES`), audited as `asset.saved`. Each asset can carry a signed asset allocation form
  (a `StoredFile` with entity type `asset_allocation`, IT-only download; the latest upload is current, earlier ones are kept). The employee record keeps a read-only list. Phase 11's
  asset recovery should build on this register, with IT in the Asset Controller's place.
- Every staff route uses `@roles_required` from `app/auth/decorators.py`.
  `tests/test_auth.py` fails if a staff route has no decorator.
- The original portal is archived, unchanged, in `legacy/`. Its features now live in:
  - `app/recruitment/careers.py`: public careers site
  - `app/recruitment/routes.py`: ATS, at `/recruitment`
  - `app/services/ats.py`: scoring

  The `Job`, `Candidate` and `Application` models are what Phase 6 applications should build on. Advert
  minimum requirements come from the position (`ApprovedPosition.minimum_requirements`). New openings come only
  from adverts (`/adverts`); `/recruitment/jobs/new` redirects there and the old job form edits imported jobs only.
- **Name:** the system is "ICE People Administration System" (`system_name` in templates). The
  public careers site keeps the "Icebolethu Group" name.
- **Sign-in:** no two-step verification (removed 24 Oct 2026) and no account lockout (removed 25 Oct
  2026), both at the user's request, overriding spec §3. Failed sign-ins are audited and rate-limited. Microsoft SSO (Entra ID) is planned and will provide MFA. Until then, users sign in with
  username *or* email plus password (`auth.routes.find_user`), so user emails must be unique.
- **Landing pages:** each audience has a simple landing page (picture, title, one line, Sign in
  button) that leads to its own sign-in page. Since 28 Oct 2026 the sign-in pages follow a reference screenshot the user supplied:
  the landing layout (picture left, footer) with the form column holding the logo, title,
  "Sign in to the …" line, a disabled "Continue with Microsoft" button, an "or sign in with username and password" rule, and
  the form (password show/hide eye, flat orange Sign in button). The pages are: `/login` → `/login/sign-in`
  (HR admin), `/login/staff` → `/login/staff/sign-in`, `/login/manager` → `/login/manager/sign-in`.
  Templates are `auth/landing.html` and `auth/login.html`; titles and text are `auth.routes.LANDINGS`.
  Users may only sign in on their own page (`User.landing`: admin roles, then Line Manager/Department Manager,
  then staff). The wrong page sends them to theirs, and sign-out returns them to their landing page.
  Onboarding pages wait for Phase 7.
- **Portal homes** (`/dashboard`, 28 Oct 2026, at the user's request; ahead of Phase 13's full dashboards): laid
  out like infographic pp. 8, 10 and 11 inside the existing sidebar and header. `dashboards/routes.py` builds one
  home per `User.landing`: admin (figures plus one tile per module), manager ("My tasks", "My team at a glance"
  and action tiles) and staff (tiles; a Sage 300 "Leave and payslips" tile). Modules not built yet show as faded
  "Coming soon" tiles. Update them as phases land. The AI assistant panel is left out until §15.12 decision 4.
- **Careers eligibility check** (built early on 28 Oct 2026, at the user's request; the rest of Phase 6 still waits):
  applying takes two pages. `/jobs/<id>` asks 5 yes/no questions (`careers.eligibility_questions`): the
  position's minimum requirements (one per line) first, then the advert's minimum education, experience
  and skills, then standard questions. Passing opens `/jobs/<id>/apply`, gated by `session["eligible_jobs"]`.
  Any "No" goes to `/talent-pool` with the reasons. The user chose this over §15.4's "can't apply yet"
  page. Answers are never stored.
- **Styling:** since 31 Oct 2026, at the user's request, the layout, design and colours of the IGSP admin
  area (`static/css/icebolethu.css` and `templates/admin_base.html` in the IGSP project). Don't change the
  layout or swap the palette without asking.
  - `app/static/style.css` is the one stylesheet for every page, the careers site included. The
    spec's Bootstrap 5 is deliberately not used.
  - Palette: logo colours only. Black #231F20, orange #F08422, deep orange #F26522 (`--primary`) and
    yellow #FDD56E. Green #28a745 means approved and red #dc3545 means declined, nothing else.
  - Look (IGSP): Montserrat (Google Fonts, loaded in `base.html`; Segoe UI fallback), 15px body and 14px in the
    staff area, flat orange buttons (radius 10; `--gradient` is now just `--primary`), white cards with a 1px border and
    no shadow (radius 14), grey sentence-case table headers, pill tabs with a black active tab, and status badges as
    sentence-case pills with a dot.
  - Staff layout (`templates/admin/base.html`, after IGSP's `admin_base.html`, `ig-` classes): a white sidebar with the
    logo, plain links (active: orange tint with a left bar), group headings, "My account" links and the account
    block with Sign out at the bottom; then the page title, `crumb`, `subheading`, search, `actions` and the
    animated IGSP bell on the grey background, then the content. Below 900px the sidebar becomes a top bar with a
    Menu button.
  - Careers (resized and re-laid out 1 Nov 2026, at the user's request, because it read as zoomed in): 14px base
    and a 1200px page (`body.site` sets `--container`/`--gutter`), a white hero with an orange-tint badge and, on the
    home page, the vacancy search inside it ("search-first"); flat cards with a thin border (no thick orange edge)
    in a 3-column grid; "How to apply" as one slim strip (`.steps-strip`); and a black footer with orange text.
    These overrides are in the "CAREERS SITE: size and layout" block of `style.css`. Every file in `app/static/` is used: `page_hero(photo=...)` puts `login-bg.jpg`
    (talent pool, thank-you) beside the hero text (`office.jpg` was removed at the user's request); sunbursts (more of
    them since 31 Oct 2026, at the user's request, as the careers site was too plain): three per hero (large orange,
    yellow, small orange), one before each section title, one in each vacancy and step card's corner (alternate step
    cards yellow), orange and yellow in the talent-pool band, and `sunburst-yellow.svg` in the footer. The three landing
    pictures and `logo.png` are used by the sign-in pages and layouts. The browser-tab icon is the handshake-and-sun
    mark copied from IGSP (1 Nov 2026): `favicon.ico`, `favicon.png` and `apple-touch-icon.png`, linked in
    `base.html` (so every page) and served at `/favicon.ico`.
  - Shared macros are in `templates/_ui.html`. Add new components to `style.css` using its variables.
- **Data:**
  - **Reset on 31 Oct 2026, at the user's request:** `instance/hr.db` was rebuilt with `flask db upgrade` and
    `python seed.py --department-accounts`. The test users are gone. It holds 35 accounts (password SEED_PASSWORD,
    emails `<username>@icebolethu.co.za`): `exco` (GCOO + Exco), `hradmin`, `grouphr` (Group HR Manager, added
    31 Oct 2026), `finance`, `it`, and per department a
    Line Manager `lm.<dept>` (grade 10, reporting to exco) and a Department Manager `dm.<dept>` (role Department
    Manager, grade 7, set as the department's head, reporting to the lm). `dm.hr` also holds the HR Manager role
    (1 Nov 2026, at the user's request), so it approves job adverts and signs in on the admin page (`/login`). It also has departments, cost centres, the org structure and reference
    data (roles, grades, holidays, approval chains, templates, settings). It has no budgets, positions, requisitions, adverts, JD library, jobs, candidates,
    applications or uploads, and the old portal was not re-imported. Don't re-add demo data unless asked.
    Exception, at the user's request (1 Nov 2026): `python seed_ict_demo.py` added dummy ICT recruitment data, 30 open
    ICT adverts (ADV-2026-00002 to -00031, each with an In-recruitment position and an Advertised requisition raised
    by dm.ict), 150 applicants (`is_demo`, @example.com) and 385 ATS-scored applications (the first 10 adverts have
    3 Shortlisted each); `python seed_ict_demo.py --remove` deletes exactly that. The
    pre-reset database and uploads are in `instance/backup-before-reset-2026-10-31/`. The notes below describe the
    full demo seed (`python seed.py`), which is still available.
  - The full demo database is created with `flask db upgrade`, `python seed.py` and
    `flask import-legacy`. A fresh seed builds the full register (a filled position per test user with
    reporting lines, vacant and frozen seats, an ad-hoc request at Finance). The existing dev DB was migrated
    in place on 28 Oct 2026 (its old positions split into seats); its pre-Phase-4 copy is
    `instance/hr.db.before-phase4`. It was upgraded and re-seeded for Phase 5 on 29 Oct 2026 (JD library and the
    live ADV-2026-00001 with eight applicants); its pre-Phase-5 copy is `instance/hr.db.before-phase5`.
    On 29 Oct 2026, at the user's request, the seed gained 11 departments (Catering, Burials, ICT, Facilities,
    Fleet, Security, Marketing, Foundations, Cleaning, Risk & Compliance, iTravel; GCOO stands in as their Department Manager)
    and one `lm.<dept>` Line Manager test user per department, HR and Finance included. `seed_positions` now
    gives a filled position to any test user without one on re-runs, so new test users can be added to `USERS`.
  - `portal.db` is the old portal's data and is only read by `import-legacy`.
  - A new migration needs `import app.models.base` for `EncryptedString`. The migration template
    already adds it.
- **Tests:** run `python -m pytest --cov=app/services`. 206 tests pass, with 91% coverage on
  services. Fixtures are in `tests/conftest.py` (`login(client, "finance")`, `make_position`, `make_requisition`; each test requisition gets its own
  vacant position).
- **Scheduled jobs:** `flask run-sla-checks` (hourly), `flask close-expired-adverts` and `flask remind-jd-reviews`
  (daily).
- **Not done yet:** UI strings aren't wrapped with Flask-Babel. Only flash messages and auth forms
  use `_()`. Wrap the remaining strings in Phase 14.
