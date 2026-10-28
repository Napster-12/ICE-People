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
- Phases 1–4 are done (Phase 4: approved positions register and vacancy dashboard, 28 Oct 2026). Phase 5 (job
  adverts, JD library and publishing, §12.1) is next.
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
- Every staff route uses `@roles_required` from `app/auth/decorators.py`.
  `tests/test_auth.py` fails if a staff route has no decorator.
- The original portal is archived, unchanged, in `legacy/`. Its features now live in:
  - `app/recruitment/careers.py`: public careers site
  - `app/recruitment/routes.py`: ATS, at `/recruitment`
  - `app/services/ats.py`: scoring

  The `Job`, `Candidate` and `Application` models are what Phase 5 and 6 adverts and applications
  should build on. Advert minimum requirements come from the position (`ApprovedPosition.minimum_requirements`).
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
  Users may only sign in on their own page (`User.landing`: admin roles, then Line Manager/HOD,
  then staff). The wrong page sends them to theirs, and sign-out returns them to their landing page.
  Careers and onboarding pages wait for Phases 5–6.
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
- **Styling:** Icebolethu's own brand stylesheet (supplied by the user on 25 Oct 2026), applied to
  the existing layout. Don't change the layout or swap the palette without asking.
  - `app/static/style.css` is the one stylesheet for every page, the careers site included. The
    spec's Bootstrap 5 is deliberately not used.
  - Palette: logo colours only. Black #231F20, orange #F08422, deep orange #F26522 (`--primary`) and
    yellow #FDD56E. Green #28a745 means approved and red #dc3545 means declined, nothing else.
  - Look: Montserrat (Google Fonts, loaded in `base.html` for every page; Segoe UI fallback; set 28 Oct 2026 from
    the user's updated brand stylesheet) at 13px body size, white cards (radius 16, `--shadow-md`), orange gradient buttons
    (`--gradient`), orange uppercase table headers, pill tabs, and status badges as uppercase pills.
  - Staff layout (`templates/admin/base.html`, unchanged markup): a white left sidebar whose menu
    items are orange buttons (the active one darker, with a white inset bar), then a white rounded
    header card (toolbar with search, bell and account menu, plus the `crumb`, `heading`,
    `subheading` and `actions` blocks), then the content.
  - Careers: white hero with an orange-tint badge, cards with a 6px orange left border, and a black
    footer with orange text.
  - Shared macros are in `templates/_ui.html`. Add new components to `style.css` using its variables.
- **Data:**
  - `instance/hr.db` is the dev database, created with `flask db upgrade`, `python seed.py` and
    `flask import-legacy`. A fresh seed builds the full register (a filled position per test user with
    reporting lines, vacant and frozen seats, an ad-hoc request at Finance). The existing dev DB was migrated
    in place on 28 Oct 2026 (its old positions split into seats); its pre-Phase-4 copy is
    `instance/hr.db.before-phase4`.
  - `portal.db` is the old portal's data and is only read by `import-legacy`.
  - A new migration needs `import app.models.base` for `EncryptedString`. The migration template
    already adds it.
- **Tests:** run `python -m pytest --cov=app/services`. 176 tests pass, with 90% coverage on
  services. Fixtures are in `tests/conftest.py` (`login(client, "finance")`, `make_position`, `make_requisition`; each test requisition gets its own
  vacant position).
- **Not done yet:** UI strings aren't wrapped with Flask-Babel. Only flash messages and auth forms
  use `_()`. Wrap the remaining strings in Phase 14.
