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
  per advert (`InterviewPanel`), starting with the Department Manager and (8 Nov 2026, at the user's request) the
  **Talent Acquisition Specialist, who also scores** (`interviews.ensure_talent_specialist`: the one who sent the
  shortlist or drafted the advert, else the first active one; added at invitation time to older panels; neither can be
  removed, `FIXED_ROLES`; the TA also scores blind: `can_see_scores` hides others' scores from any panellist until
  they submit, and the TA home has an "Interviews to score" tile); HR invites managers or another TA (`PANEL_ROLES`:
  Line Manager, Department Manager, HR Manager, Group HR, GCOO, Exco, Talent Acquisition Specialist) on `/recruitment/jobs/<id>/panel`, sets each
  Interview candidate's slot (`InterviewSlot`, with the .ics from the calendar adapter; the scorecard's "Add to Teams calendar" button
  opens a prefilled Teams meeting via `interviews.teams_link`, not an .ics download, with no attendees so it only
  adds to the user's own calendar and sends no invites; 3 Nov 2026 at the user's request), then sends the
  invitations (panel notification + email; candidates get the invitation email from their slot), which need at least
  one interview question.
  **Interview questions replace criteria and rating scales** (8 Nov 2026, at the user's request; migration
  `d6b2e9f4a718` dropped `jd_templates.interview_criteria` / `rating_scale` and the panel's criteria and scale,
  turned old panels' criteria names into questions and deleted old scorecards). The **Department Manager types the
  questions** (1–15, each up to 300 characters, different) on the shortlist review when returning it
  (`shortlisting.complete_review(..., questions)` → `interviews.save_questions`; required); the **Talent Acquisition
  Specialist (HR) edits them** on the panel page ("Interview questions"); they lock once anyone scores. Form rows:
  `question_rows` macro in `_ui.html`, `web.questions_input`, "Add another question" in `admin/base.html`. The JD
  library has no interview section any more. Panellists (any role, membership checked) score on
  `/recruitment/interviews/<app_id>`: **only the questions**, each **1–5** (`interviews.SCORES`: Poor, Below
  expectations, Meets expectations, Exceeds, Outstanding) with its own comment, then the recommendation and an optional
  overall comment (`Scorecard.answers` = [{question, score, comment}]; `total` = average ÷ 5 × 100). One `Scorecard`
  each, final; it opens only once the candidate's slot has started (`interviews.interview_started`), the ATS score
  isn't shown, and others' scores and comments (by question) show only after submitting; HR always sees them.
  The **panel invitation** lists each candidate with a **scorecard link** (`interviews.scorecard_url`, absolute via
  `PUBLIC_BASE_URL`; signing in returns to it). Results rank by the panel's average; HR is notified when the whole
  panel has scored a candidate.
  **Interview invitations** (8 Nov 2026, at the user's request): detailed and congratulatory ("Congratulations! …
  Good luck!"). `InterviewSlot.platform` ("In person" or "Microsoft Teams", `INTERVIEW_PLATFORMS`; migration
  `a9d3e6f2c871`) plus `meeting_id` and `passcode`; for Teams the `venue` holds the joining link (must be https).
  Both the panel's slot table and the invitations page (`job_messages.html`) have the format choice, toggled by
  `[data-platform]` / `[data-online]` / `[data-offline]` in `admin/base.html`. `shortlisting.interview_details`
  validates and formats them (date as "Tuesday, 17 November 2026", duration); online invitations get a "Join the
  meeting" button, and `emails.linkify` makes links in email text clickable.
  **Offers and onboarding, owned by HR Admin** (8 Nov 2026, at the user's request; pulls forward part of Phase 7 and
  Phase 8's contracts; `app/services/onboarding.py`, `app/onboarding/routes.py` at `/onboarding`, migration
  `b7e4c1d9a352`): (1) once the whole panel has scored, HR marks a candidate **successful** on the panel's Results
  (`interviews.mark_successful`): application → Offer, requisition → Offer, HR Admin notified (`interview_passed`).
  (2) HR Admin prepares the `Offer` (OFR-…; CTC from the requisition's costed CTC, start date, employment type,
  contract end, conditions, expiry); above the costed CTC (or none) it goes to **Finance** (workflow type `offer`)
  before it can be sent. (3) Sending emails `candidate_offer` with the offer letter PDF attached (emails now take
  `attachments`) and a secure link `/offer/<token>` (careers blueprint, public) to accept (tick box) or decline.
  (4) Acceptance: application Hired, the advert's other open applicants "Not selected" (HR sends regrets), requisition
  and position Filled, budget consumed at the offer CTC, advert closed, an `Employee` (Pre-boarding) with the **next
  ICE number** (`onboarding.next_employee_number`, editable by HR Admin on the case; the new-employee form suggests it
  too) and an `OnboardingCase` (ONB-…); HR Admin and the TA notified, the candidate welcomed. Decline/expiry
  (`flask expire-offers`)/withdrawal sends the requisition back to Interviewing. (5) HR Admin generates the
  **contract** PDF for the employment type and uploads the **signed copy** (`employment_contract` files). Offer letter
  and contract wording are `DocumentTemplate`s HR Admin edits under Onboarding → Letter and contract templates
  (`app/services/documents.py`, xhtml2pdf, `templates/documents/letter.html` letterhead). Edit: HR Admin only; view:
  HR Admin, HR Manager, Group HR; Finance sees offers sent to it. Still to come: references and screening, candidate
  accounts, the new-starter portal (documents, e-sign, IT access), induction.
  **Letter layout follows Icebolethu's current offer letter** (8 Nov 2026, the user's example, "Codnell Chablala
  Offer letter.pdf"): logo and orange/grey rule, STRICTLY CONFIDENTIAL, date, the candidate's address, "Dear Mr …",
  underlined "# RE: Conditional employment offer letter", **bold** values, "1. Remuneration" with 1.1 CTC per annum,
  1.1.1 basic salary per month, 1.2 probation in words ("six (6) months"), "Yours sincerely", [signature], the
  signatory's name and title, and a page-2 acceptance section that, on the copy kept at acceptance
  (`Offer.accepted_file`), shows who accepted online and when. Every page's footer: page number, contact line
  (`documents.LETTERHEAD`: both phone numbers, Durban and Randburg addresses, www.icebolethugroup.co.za) and the
  orange band; footer images in `static/documents/` from `tools/make_letterhead.py` (needs Chrome). Offers carry
  `salutation`, `candidate_address`, `work_location` and `probation_months` (migration `c4f8a2e6d913`; probation
  defaults to the `probation_months` setting for Permanent). The signatory (`letter_signatory_name` / `_title`
  settings, kept off IT's Settings page) and an optional signature image (`document_signature` file, HR Admin only)
  are set on the templates page. Dates on letters and offer emails are long ("01 July 2026", `documents.long_date`).
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
  - Job grades are the **occupational levels** (5 Nov 2026, at the user's request, replacing 31 Oct's Intern, Junior,
    Senior, Manager, Exco rank for rank; migration `b4e1f7a93c52`): 1 Support / Unskilled Staff, 2 Skilled Staff /
    Technical / Junior Management / Supervisor, 3 Professional / Experienced / Specialists / Mid-Management, 4 Senior
    Management (HODs, Regional Managers), 5 Top Management (CEOs, EXCO, Directors, Founders). Names are only in
    `reference_data.GRADES`; screens label the field "Occupational level" (the code keeps `job_grade`). Seeds and
    tests look grades up by rank (`JobGrade.grade`, 1–5, also used in routing conditions), never by name; the
    positions CSV takes the rank or the full name. Grades carry **no salary**: the band columns,
    the Salary Bands page and the `casual_default_hours` setting are gone (migration `e2a7c9d14b38`; old grades
    mapped 1–3 Junior, 4–7 Senior, 8–11 Manager, 12 Exco). `budget.calculate_ctc(position, …)` costs a
    requisition from the position's `budgeted_ctc` (Contract pro-rated by months; Permanent and Casual as is) and
    refuses a position with none. The demo seed prices its positions with `DEMO_CTC` by grade rank.
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
    **The positions register is approved by the Finance Department Manager** (8 Nov 2026, at the user's request), then
    the Group HR Manager: the special approver `@finance_department_manager` (`FINANCE_DEPARTMENT_MANAGER`) is the head
    of the Finance department (code `FIN`, `dm.finance` in the dev DB), else the Finance role; the dev DB's rule was
    updated in place. The other Finance steps (requisitions, ad-hoc positions, position changes, offers) still use the
    Finance role.
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
    `ats.weights_for(job)`. Saves keep `AdvertVersion`s. **Skill matching** (8 Nov 2026, at the user's request, as CVs' skills were missed):
    `ats.has_skill` accepts the skill's variants (`ats._variants`: ms/microsoft prefix, reactjs/react.js/react,
    html5/html, British/American spellings) and its synonym group (`ats.SYNONYMS`, e.g. office 365 = microsoft 365,
    service desk = help desk / first-line support, active directory = azure ad / entra id; extend the list as needed),
    and a 2–4-word skill also matches when its words (any order, stemmed by `ats._stem`) are within 6 words in one
    sentence or line (`ats._near`). `ats.clean_text` tidies extracted text (ligatures, hyphenated line breaks,
    letter-spaced headings). Scanned (image-only) CVs have no text: there is no OCR, and HR sees "No readable text"
    on the breakdown. **Sentence-style requirements** (8 Nov 2026): a Required/Preferred skills box pasted from a JD
    (`ats._is_sentences`: "such as", or comma parts over 5 words) is split into requirements on full stops, lines and
    semicolons (`ats.requirement_items`), each one's skills are pulled out (`requirement_terms`; C#/.NET → c#, net),
    and it's met when the CV has any of them ("such as / or / at least one / e.g.") or else at least half
    (`requirement_met`); the breakdown chips show a short name, the skills found and the full text on hover. A
    plain comma list ("sql, python") works as before. `flask reprocess-cvs` re-reads every CV and rescores every
    application (run after ATS changes; done on 8 Nov 2026). Tests: `tests/test_ats.py`. Careers links
    tagged `?src=<channel>` count views and applications per channel and set `Application.source`.
- **Talent Acquisition Specialist** (5 Nov 2026, at the user's request): the role formerly "Recruiter" (constant
  still `RECRUITER`; migration `c7a2d9e4f186`) is a recruitment-only profile. It is **not** in `HR_ROLES`;
  `RECRUITMENT_ROLES` (HR_ROLES plus it) guards adverts, the JD library and `/recruitment`, and `User.can_recruit`
  replaces `is_hr` in recruitment checks (shortlists, scorecards, candidate files). It reads approved requisitions
  only (`requisitions.RECRUITMENT_STAGES`, detail page only, no Requisitions menu), has no Employees, positions,
  ad-hoc or budget access, signs in on the admin page, and (`User.recruitment_only`) gets
  `dashboards._recruitment_home` (recruitment figures and tiles). Tests: `tests/test_talent_acquisition.py`.
- **ICT owns system admin** (29 Oct 2026, at the user's request): the sidebar's "ICT" group (Approvals Dashboard,
  Users & Roles, Routing Rules, Settings with holidays and templates, Assets, Audit Log, Integration Log) is for the
  IT role only; HR Admin and HR Manager lost it. Compliance keeps Audit Log. HR Admin keeps Departments and Org Structure.
  **HR Admin has no Talent or Budget** (8 Nov 2026, at the user's request): `nav.HIDDEN_MENUS` drops those sidebar
  groups for HR Admin, and `_admin_home` (via `nav.sees_menu`) drops the talent, positions and budget figures and
  tiles, showing onboarding figures instead. Someone who also holds a role that sees them (e.g. dm.hr, HR Manager)
  keeps them. Only the menus and home page changed: the pages and HR Admin's fallback approver role still work.
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
  Everyone is staff (1 Nov 2026, at the user's request): `User.portals` is the user's own portal(s) plus "staff",
  so anyone may sign in on the staff page and get the staff home; the manager and admin pages still need those
  roles (the wrong page sends users to `User.landing`). The portal signed in on is `session["portal"]`
  (`app/auth/portals.current_portal`); users with more than one switch from the sidebar's "Portals"
  (`/portal/<name>`), the home page follows it, and sign-out returns to that portal's landing page.
  The staff Onboarding pages exist since 8 Nov 2026 (HR Admin, see Current state); new-starter sign-in waits.
- **Portal homes** (`/dashboard`, 28 Oct 2026, at the user's request; ahead of Phase 13's full dashboards): laid
  out like infographic pp. 8, 10 and 11 inside the existing sidebar and header. `dashboards/routes.py` builds one
  home per `User.landing`: admin (figures plus one tile per module), manager ("My tasks", "My team at a glance"
  and action tiles) and staff (tiles; a Sage 300 "Leave and payslips" tile that opens the `sage_self_service_url` setting, https://online.sage.co.za/U36476/#/signin, in a new tab; IT can change it under Settings). Modules not built yet show as faded
  "Coming soon" tiles. Each tile has an icon from `_icons.html` (`_tile(icon, …)`; 3 Nov 2026 replaced the letter
  badges, matching the sidebar's icon for the same module). Update them as phases land. The AI assistant panel is left out until §15.12 decision 4.
- **Careers eligibility check** (built early on 28 Oct 2026, at the user's request; the rest of Phase 6 still waits):
  applying takes two pages. `/jobs/<id>` asks the advert's yes/no questions (`careers.eligibility_questions`).
  **Typed per advert** (6 Nov 2026, at the user's request; the generated questions are gone): the Talent Acquisition
  Specialist types 1–10 questions on the advert form, each with the answer that qualifies ("yes" or "no"), stored
  in `Job.eligibility_questions` (migration `e8c4a2f71b39`; `adverts.parse_eligibility`). A new draft starts with
  none, `adverts.problems` blocks approval until one is typed, and `readvertise` clears them so each cycle types its
  own. The advert page shows them to the approving HR Manager. The 33 adverts live on 6 Nov kept their old generated
  questions (saved onto each). A job with none (imported) skips the check. Passing opens `/jobs/<id>/apply`, gated
  by `session["eligible_jobs"]`. A wrong answer goes to `/talent-pool` with the questions it failed. The user chose
  this over §15.4's "can't apply yet" page. Answers are never stored.
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
  - Staff layout (`templates/admin/base.html`, after IGSP's `admin_base.html`, `ig-` classes): a white sidebar whose brand block (redesigned 3 Nov 2026 at
    the user's request) is centred: the handshake-and-sun mark (`favicon.png`, 44px; replaced the wordmark logo), then
    "ICE People" (`.ig-wordmark`: 18px, 800 weight, "ICE" black, "People" deep orange), then "Administration System"
    in grey, with a divider above the menu (a row with icon left on phones), plain links (active: orange tint with a left bar), group headings, "My account" links and the account
    card at the bottom (redesigned 3 Nov 2026 at the user's request: name and email, the user's department as one
    orange-tint pill (8 Nov 2026; it listed every role, "Employee" included, before),
    then a full-width "Sign out" button; no avatar); then the page title, `crumb`, `subheading`, search, `actions` and the
    animated IGSP bell on the grey background, then the content. Below 900px the sidebar becomes a top bar with a
    Menu button.
  - Careers (resized and re-laid out 1 Nov 2026, at the user's request, because it read as zoomed in): 14px base
    and a 1200px page (`body.site` sets `--container`/`--gutter`), a white hero with an orange-tint badge and, on the
    home page, the vacancy search inside it ("search-first"); flat cards with a thin border (no thick orange edge)
    in a 3-column grid; "How to apply" as one slim strip (`.steps-strip`); and a black footer with orange text.
    These overrides are in the "CAREERS SITE: size and layout" block of `style.css`. Social media icons (8 Nov 2026, at the user's request; IGSP's icons and links in `_social.html`): small
    orange icons in the careers header before "Submit your CV" (hidden on phones) and round "Follow us" buttons in the footer. Every file in `app/static/` is used: `page_hero(photo=...)` puts `login-bg.jpg`
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
    (1 Nov 2026, at the user's request), so it approves job adverts and signs in on the admin page (`/login`).
    `ta` (Talent Acquisition Specialist, HR, reporting to dm.hr) was added on 5 Nov 2026, making 36 accounts. It also has departments, cost centres, the org structure and reference
    data (roles, grades, holidays, approval chains, templates, settings). It has no budgets, positions, requisitions, adverts, JD library, jobs, candidates,
    applications or uploads, and the old portal was not re-imported. Don't re-add demo data unless asked.
    **Cleaned on 8 Nov 2026, at the user's request ("delete all dummy data"):** the ICT demo (adverts, requisitions,
    positions, 150 applicants), the 60 dummy JDs, the user's test recruitment (ADV-2026-00001/-00032/-00033, their
    requisitions, 4 test applicants and CVs, offers OFR-2026-00001 to -00003, case ONB-2026-00001 and employee
    ICE1037) and the 152 Planned FY2026/27 positions with their draft register and budget line were deleted, with
    all notifications, panels, scorecards and approval records. The POS, REQ, ADV, OFR and ONB numbers restart at
    00001. Kept: the 36 accounts and their employee records (no longer linked to positions), departments, cost
    centres, org structure, job families, reference data, settings, templates, the "systems analyst" JD (edited by
    the user), the audit and integration logs. Backup: `instance/backup-before-cleanup-2026-11-08/` (database and
    uploads). The notes below about the ICT demo and JD library describe what the scripts add if run again.
    Exception, at the user's request (1 Nov 2026): `python seed_ict_demo.py` added dummy ICT recruitment data, 30 open
    ICT adverts (ADV-2026-00002 to -00031, each with an In-recruitment position and an Advertised requisition raised
    by dm.ict), 150 applicants (`is_demo`, @example.com) and 385 ATS-scored applications (the first 10 adverts have
    3 Shortlisted each); `python seed_ict_demo.py --remove` deletes exactly that. On 2 Nov 2026,
    `python seed_ict_demo.py --positions` added an approved ICT establishment (24 positions marked "[ICT demo]"): the
    ICT Line Manager, Department Manager and IT Administrator posts, Filled and linked to those accounts (found by
    role, as the accounts were renamed), 19 Vacant seats and 2 Frozen, reporting to the Department Manager post.
    On 6 Nov 2026, `python seed_jd_library.py` added a dummy JD library at the user's request: 60 detailed JDs
    across every department (burials, sales, catering, ICT, facilities, fleet, security, cleaning, marketing,
    foundations, risk, iTravel, HR, finance, office support). (Their interview criteria were dropped on 8 Nov 2026.)
    `--remove` deletes only those not edited since (no `updated_by`) and not used by an advert.
    The pre-reset database and uploads are in `instance/backup-before-reset-2026-10-31/`. The notes below describe the
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
- **Tests:** run `python -m pytest --cov=app/services`. 308 tests pass, with 91% coverage on
  services. Fixtures are in `tests/conftest.py` (`login(client, "finance")`, `make_position`, `make_requisition`; each test requisition gets its own
  vacant position).
- **Scheduled jobs:** `flask run-sla-checks` (hourly), `flask close-expired-adverts`, `flask remind-jd-reviews` and
  `flask expire-offers` (daily).
- **Email is live** (6 Nov 2026, at the user's request): `MAIL_PROVIDER=smtp` in `.env` selects
  `email_calendar.SmtpEmailCalendar`, using IGSP's SMTP settings (Gmail `smtp.gmail.com:587`, STARTTLS, sender and
  login `codnellsmall@gmail.com` with an app password, display name `SMTP_FROM_NAME`). The user chose live sending,
  so emails go to the real recipients (the seed accounts' `<username>@icebolethu.co.za` addresses included), and
  every email is also BCC'd to `EMAIL_COPY_TO` (codnellsmall@gmail.com) for review. **Sending is in the background**
  (8 Nov 2026, at the user's request, as pages waited seconds for Gmail): `SmtpEmailCalendar.send_email` builds the
  message in the request and queues the SMTP send on a 2-worker pool, which runs `Adapter.call` (Integration Log,
  3 attempts) in its own app context and returns `{"status": "queued"}`; a failure is only logged, never shown to the
  user. `EMAIL_ASYNC` (env, default on) turns it off; `TestingConfig`, `send-test-email` and `send-email-samples` send
  synchronously; `email_calendar.wait_for_emails()` waits for the queue. `TestingConfig` forces the mock, so tests never send.
  `flask send-test-email --to <address>` checks the settings. Calendar invites are still .ics files.
- **Application received email** (8 Nov 2026, at the user's request; spec IN-010 acknowledgement): after a job
  application or a talent-pool submission, `careers.send_application_received` emails the applicant the editable
  template `candidate_application_received` (reference, position, date) with a "Check your application status"
  button to `/status`. The automatic talent-pool copy of a job application sends nothing extra.
- **Designed emails** (6 Nov 2026, at the user's request): every email is sent as plain text plus HTML.
  `app/services/emails.py` wraps the editable template's rendered text in `templates/email/layout.html`.
  **Current design** (8 Nov 2026, at the user's request; the third one: the 6 Nov gradient/sunburst design and the
  IGSP copy were both rejected): warm grey page (#F4F2EF), one 600px white card (radius 16) with the brand header,
  a three-colour stripe (deep orange, orange, yellow), an orange uppercase label above the text, the text (no subject
  heading: the inbox shows it), a flat #F26522 button with an arrow (VML for Outlook) and, **since 8 Nov 2026 at the
  user's request, a footer inside the card** under a hairline: the "we do life with you" banner
  (`static/email/footer-banner.jpg`, cropped from the user's image, linked to `emails.WEBSITE`), "Icebolethu is a
  registered **Financial Services Provider FSP45714**" (`emails.FSP_NUMBER`) and round orange social icons
  (`static/email/social-*.png` from `tools/make_email_icons.py`, PNG because email apps don't show SVG; links in
  `emails.SOCIAL`). The old text footer (ICE People / Careers line, POPIA note, "Automated email") is gone. The embedded
  images (logo/mark, banner, icons) are sent as `Content-Disposition: inline` related parts
  (`SmtpEmailCalendar.send_email`); as "attachment" (Python's default when a filename is given) mail apps listed them
  as attachments and showed the message unstyled. **Brand by audience:** applicant emails (`candidate_*` keys) keep the Icebolethu Group logo (cid:logo) and
   staff emails show the ICE People Administration System brand
  like the sidebar (the mark, `static/email/mark.png`, a 96px copy of `favicon.png`, as cid:mark, plus the "ICE
  People" / "Administration System" wordmark in HTML text). Don't redesign it without asking.
  Blank lines make paragraphs, "Label: value" lines a details table, "- " lines bullets, "Kind regards" a sign-off;
  `META` gives each template key its label and button; status/outcome become a soft pill (green approved, red
  declined, orange otherwise) beside the label. Only the images an email uses are attached; buttons use `PUBLIC_BASE_URL`. It renders through
  `jinja_env` directly (no request or user needed), and `emails.designed` falls back to text only if it fails.
  IT previews each template at `/admin/templates/<id>/preview` (Settings → templates), and
  `flask send-email-samples --to <address>` emails one filled-in sample of every template.
- **Not done yet:** UI strings aren't wrapped with Flask-Babel. Only flash messages and auth forms
  use `_()`. Wrap the remaining strings in Phase 14.
