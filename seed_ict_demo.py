"""Dummy ICT recruitment data (1 Nov 2026, at the user's request): 30 open ICT vacancies, each with its approved
position, an advertised requisition and an open advert, plus dummy applicants scored by the ATS.

    python seed_ict_demo.py            # add it (once; a second run does nothing)
    python seed_ict_demo.py --remove   # delete exactly what it added

Everything it creates is marked: adverts and candidates have is_demo set, candidate emails end in @example.com,
and positions and requisitions carry "[ICT demo]" in their justification. Needs the department accounts
(`python seed.py --department-accounts`): the requisitions are raised by dm.ict, and shortlists go to dm.ict.
Some applicants are already Shortlisted so the shortlist review can be tried straight away.
"""
import random
import sys
from datetime import timedelta
from decimal import Decimal

from app import create_app
from app.extensions import db

MARK = "[ICT demo]"
RNG = random.Random(2026)

# title, grade, minimum years, minimum education (ats.EDUCATION_LEVELS), required skills, advantageous skills,
# employment type, location
ROLES = [
    ("Service Desk Agent", "Junior", 1, 2, "service desk, windows, active directory, ticketing",
     "itil, office 365", "Permanent", "Durban, KwaZulu-Natal"),
    ("Desktop Support Technician", "Junior", 2, 2, "windows, hardware, active directory, networking",
     "a+, n+, sccm", "Permanent", "Pinetown, KwaZulu-Natal"),
    ("Senior Desktop Support Technician", "Senior", 4, 3, "windows, active directory, intune, hardware",
     "itil, office 365, powershell", "Permanent", "Johannesburg, Gauteng"),
    ("Network Administrator", "Senior", 3, 3, "networking, cisco, firewalls, vpn",
     "ccna, fortinet, wireless", "Permanent", "Durban, KwaZulu-Natal"),
    ("Network Engineer", "Senior", 5, 4, "cisco, routing, switching, firewalls, sd-wan",
     "ccnp, fortinet, bgp", "Permanent", "Johannesburg, Gauteng"),
    ("Systems Administrator", "Senior", 3, 3, "windows server, active directory, vmware, backups",
     "powershell, azure, veeam", "Permanent", "Durban, KwaZulu-Natal"),
    ("Linux Systems Administrator", "Senior", 4, 3, "linux, bash, apache, nginx",
     "ansible, docker, postgresql", "Contract", "Cape Town, Western Cape"),
    ("Cloud Engineer", "Senior", 4, 4, "azure, terraform, networking, powershell",
     "aws, kubernetes, devops", "Permanent", "Johannesburg, Gauteng"),
    ("DevOps Engineer", "Senior", 4, 4, "ci/cd, docker, kubernetes, git",
     "terraform, azure devops, python", "Permanent", "Cape Town, Western Cape"),
    ("Database Administrator", "Senior", 4, 4, "sql server, t-sql, backups, performance tuning",
     "postgresql, azure sql, ssis", "Permanent", "Durban, KwaZulu-Natal"),
    ("Junior Software Developer", "Junior", 1, 4, "c#, sql, git, javascript",
     ".net, html, css", "Permanent", "Durban, KwaZulu-Natal"),
    ("Software Developer", "Senior", 3, 4, "c#, .net, sql, rest api, git",
     "azure, angular, unit testing", "Permanent", "Umhlanga, KwaZulu-Natal"),
    ("Senior Software Developer", "Senior", 6, 4, "c#, .net, sql, microservices, rest api",
     "azure, kubernetes, mentoring", "Permanent", "Johannesburg, Gauteng"),
    ("Python Developer", "Senior", 3, 4, "python, django, sql, rest api",
     "flask, celery, postgresql", "Contract", "Cape Town, Western Cape"),
    ("Front-end Developer", "Senior", 3, 4, "javascript, react, html, css",
     "typescript, figma, accessibility", "Permanent", "Johannesburg, Gauteng"),
    ("Mobile Developer", "Senior", 3, 4, "flutter, dart, rest api, git",
     "android, ios, firebase", "Contract", "Pretoria, Gauteng"),
    ("QA Tester", "Junior", 2, 3, "manual testing, test cases, jira, sql",
     "selenium, istqb, postman", "Permanent", "Durban, KwaZulu-Natal"),
    ("Test Automation Engineer", "Senior", 3, 4, "selenium, test automation, c#, ci/cd",
     "playwright, specflow, istqb", "Permanent", "Johannesburg, Gauteng"),
    ("Business Analyst", "Senior", 4, 4, "requirements, process mapping, uml, stakeholder management",
     "agile, jira, sql", "Permanent", "Durban, KwaZulu-Natal"),
    ("Data Analyst", "Senior", 3, 4, "sql, power bi, excel, data modelling",
     "python, dax, ssrs", "Permanent", "Durban, KwaZulu-Natal"),
    ("Data Engineer", "Senior", 4, 4, "sql, python, etl, data warehousing",
     "azure data factory, spark, databricks", "Contract", "Johannesburg, Gauteng"),
    ("BI Developer", "Senior", 3, 4, "power bi, sql, ssis, data modelling",
     "dax, azure synapse, ssas", "Permanent", "Pinetown, KwaZulu-Natal"),
    ("Information Security Analyst", "Senior", 4, 4, "siem, vulnerability management, firewalls, incident response",
     "cissp, comptia security+, iso 27001", "Permanent", "Johannesburg, Gauteng"),
    ("Security Engineer", "Senior", 5, 4, "endpoint security, identity management, azure ad, firewalls",
     "cism, penetration testing, zero trust", "Permanent", "Durban, KwaZulu-Natal"),
    ("ERP Support Analyst", "Senior", 3, 3, "erp, sql, user support, business processes",
     "sage x3, sap, crystal reports", "Permanent", "Durban, KwaZulu-Natal"),
    ("Sage 300 Payroll Systems Specialist", "Senior", 4, 3, "sage 300, payroll, sql, user support",
     "sage vip, reporting, ess", "Permanent", "Durban, KwaZulu-Natal"),
    ("IT Project Manager", "Manager", 6, 4, "project management, budgets, stakeholder management, risk management",
     "pmp, prince2, agile", "Permanent", "Johannesburg, Gauteng"),
    ("Scrum Master", "Senior", 4, 4, "scrum, agile, jira, facilitation",
     "csm, kanban, safe", "Contract", "Cape Town, Western Cape"),
    ("ICT Infrastructure Manager", "Manager", 8, 4, "infrastructure, networking, vendor management, budgets",
     "itil, azure, team leadership", "Permanent", "Durban, KwaZulu-Natal"),
    ("ICT Intern", "Intern", 0, 3, "windows, networking, microsoft office",
     "a+, python, customer service", "Contract", "Durban, KwaZulu-Natal"),
]
DEMO_CTC = {"Intern": Decimal("96000"), "Junior": Decimal("216000"), "Senior": Decimal("480000"),
            "Manager": Decimal("840000")}
FIRST = ["Sipho", "Thandeka", "Lwazi", "Nomvula", "Kagiso", "Ayanda", "Lerato", "Themba", "Zanele", "Bongani",
         "Naledi", "Mpho", "Nokuthula", "Sibusiso", "Palesa", "Tshepo", "Ntombi", "Kabelo", "Priya", "Rajesh",
         "Fatima", "Yusuf", "Johan", "Annelie", "Pieter", "Michelle", "David", "Sarah", "Kevin", "Chantal",
         "Lindiwe", "Mandla", "Busisiwe", "Siyabonga", "Refilwe", "Karabo", "Thabo", "Nandi", "Musa", "Zinhle"]
LAST = ["Dlamini", "Zulu", "Ndlovu", "Mkhize", "Nkosi", "Khumalo", "Mthembu", "Ngcobo", "Shabalala", "Mokoena",
        "Molefe", "Mahlangu", "Naidoo", "Pillay", "Govender", "Moodley", "van der Merwe", "Botha", "Smith",
        "Williams", "Cele", "Buthelezi", "Gumede", "Radebe", "Sithole", "Maseko", "Nxumalo", "Hadebe"]
COMPANIES = ["a Durban logistics firm", "a national retailer", "a provincial department", "a Johannesburg bank",
             "an IT services company", "an insurance group", "a software house", "a call centre"]
SOURCES = ["Careers site"] * 5 + ["LinkedIn"] * 3 + ["PNet"] * 2 + ["Internal", "Intranet", "CareerJunction"]


def _skills(text):
    return [s.strip() for s in text.split(",") if s.strip()]


def _description(title, required, preferred):
    req = "\n".join(f"- {s.capitalize()}" for s in _skills(required))
    return (f"ABOUT THE ROLE\nIcebolethu Group's ICT team is looking for a {title} to support the Group's systems "
            f"and the people who rely on them.\n\nKEY RESPONSIBILITIES\n- Deliver and support ICT services to the "
            f"business\n- Keep systems secure, documented and available\n- Work with users and suppliers to resolve "
            f"issues quickly\n\nWHAT YOU'LL BRING\n{req}\n\nADVANTAGEOUS\n"
            + "\n".join(f"- {s.capitalize()}" for s in _skills(preferred)))


def add():
    from app.models import (AdvertPosting, ApprovedPosition, Application, Candidate, Department, Job, JobFamily,
                            JobGrade, Requisition, User)
    from app.services import ats, budget, careers
    from app.services.dates import now, today
    from app.services.refs import next_reference

    if Job.query.filter(Job.is_demo.is_(True), Job.department == "ICT").first():
        print("The ICT demo data is already there. Remove it first with: python seed_ict_demo.py --remove")
        return
    ict = Department.query.filter_by(code="ICT").one()
    manager, hr = User.query.filter_by(username="dm.ict").first(), User.query.filter_by(username="hradmin").first()
    if manager is None or hr is None:
        sys.exit("Run `python seed.py --department-accounts` first (needs dm.ict and hradmin).")
    grades = {g.name: g for g in JobGrade.query.all()}
    family = JobFamily.query.filter_by(code="ICT").first()
    fy = budget.financial_year_for(today())

    jobs = []
    for i, (title, grade, years, edu, required, preferred, etype, location) in enumerate(ROLES):
        position = ApprovedPosition(position_number=next_reference("POS"), title=title, department_id=ict.id,
                                    cost_centre_id=ict.cost_centres[0].id, job_grade_id=grades[grade].id,
                                    job_family_id=family.id if family else None, budgeted_ctc=DEMO_CTC[grade],
                                    financial_year=fy, status="In recruitment", justification=MARK,
                                    vacant_since=today() - timedelta(days=10 + 3 * i),
                                    minimum_requirements=f"{ats.EDUCATION_LABELS[edu]} or higher\n"
                                                         f"{years}+ years' relevant experience" if years
                                    else f"{ats.EDUCATION_LABELS[edu]} or studying towards it")
        db.session.add(position)
        db.session.flush()
        start = today() + timedelta(days=30 + i)
        req = Requisition(reference=next_reference("REQ"), title=title, department_id=ict.id,
                          cost_centre_id=position.cost_centre_id, job_grade_id=position.job_grade_id,
                          employment_type=etype, headcount_type="New", required_start_date=start,
                          contract_end_date=start + timedelta(days=365) if etype == "Contract" else None,
                          justification=f"{MARK} {title} needed for the ICT team's current workload.",
                          approved_position_id=position.id, status="Advertised", originator_id=manager.id,
                          version=1, submitted_at=now() - timedelta(days=20), approved_at=now() - timedelta(days=12),
                          financial_year=fy, ctc=DEMO_CTC[grade])
        db.session.add(req)
        db.session.flush()
        job = Job(reference=next_reference("ADV"), requisition_id=req.id, title=title, department="ICT",
                  location=location, job_type="Contract" if etype == "Contract" else "Full-time",
                  description=_description(title, required, preferred), required_skills=required,
                  preferred_skills=preferred, min_experience=years, min_education=edu,
                  closing_date=today() + timedelta(days=7 + i % 21), status="Open", is_demo=True,
                  channels=["Internal", "Intranet", "LinkedIn"], cycle=1, version=1, created_by_id=hr.id,
                  created_at=now() - timedelta(days=10), published_at=now() - timedelta(days=9))
        db.session.add(job)
        db.session.flush()
        for channel in ["Careers site", "Internal", "Intranet", "LinkedIn"]:
            db.session.add(AdvertPosting(job_id=job.id, cycle=1, channel=channel, status="Live",
                                         published_at=job.published_at, views=RNG.randint(10, 160)))
        jobs.append((job, ROLES[i]))

    # Applicants: each has a role they're suited to (most of its skills) and applies to it and a few others.
    candidates = []
    for n in range(150):
        first, last = RNG.choice(FIRST), RNG.choice(LAST)
        home = RNG.randrange(len(ROLES))
        title, grade, years, edu, required, preferred = ROLES[home][:6]
        skills = RNG.sample(_skills(required), k=max(1, len(_skills(required)) - RNG.randint(0, 2)))
        skills += RNG.sample(_skills(preferred), k=RNG.randint(0, 2))
        exp = max(0, years + RNG.randint(-2, 4))
        level = min(7, max(1, edu + RNG.choice([-1, 0, 0, 1])))
        where = RNG.choice(ROLES)[7]
        cv = (f"{first} {last}\n{where}\n\nPROFILE\n{title} with {exp} years of experience at "
              f"{RNG.choice(COMPANIES)}.\n\nSKILLS\n{', '.join(skills)}\n\nEDUCATION\n{ats.EDUCATION_LABELS[level]}")
        cand = Candidate(full_name=f"{first} {last}", email=f"{first}.{last}.{n}@example.com".lower().replace(" ", ""),
                         phone=f"08{RNG.randint(1, 4)} {RNG.randint(100, 999)} {RNG.randint(1000, 9999)}",
                         location=where, current_title=title, years_experience=exp, education_level=level,
                         skills=", ".join(skills), cv_text=cv, consent=True, is_demo=True)
        db.session.add(cand)
        candidates.append((cand, home))
    db.session.flush()

    applied = {job.id: [] for job, _ in jobs}
    for cand, home in candidates:
        targets = {home} | set(RNG.sample(range(len(ROLES)), k=RNG.randint(0, 3)))
        for t in targets:
            applied[jobs[t][0].id].append(cand)
    for job, _role in jobs:                                   # at least four applicants per advert
        while len(applied[job.id]) < 4:
            extra = RNG.choice(candidates)[0]
            if extra not in applied[job.id]:
                applied[job.id].append(extra)

    total = 0
    for i, (job, _role) in enumerate(jobs):
        scored = sorted(((ats.score_candidate(job, c), c) for c in applied[job.id]), key=lambda x: -x[0][0])
        for rank, ((score, breakdown), cand) in enumerate(scored):
            # The first ten adverts already have a shortlist (their top three) to try the Department Manager review.
            status = ("Shortlisted" if i < 10 and rank < 3 else "Screening" if rank < 5 and RNG.random() < .4
                      else "New")
            db.session.add(Application(reference=careers.new_reference(), candidate_id=cand.id, job_id=job.id,
                                       score=score, breakdown=breakdown, status=status,
                                       source=RNG.choice(SOURCES), cover_note=f"I'd like to apply for the {job.title} role."))
            total += 1
    db.session.commit()
    print(f"Added {len(jobs)} ICT adverts (with positions and requisitions), {len(candidates)} applicants and "
          f"{total} applications. The first 10 adverts have 3 shortlisted applicants each.")


def remove_demo():
    from app.models import ApprovedPosition, Candidate, Job, Requisition, ShortlistReview
    jobs = Job.query.filter(Job.is_demo.is_(True), Job.department == "ICT").all()
    req_ids = [j.requisition_id for j in jobs if j.requisition_id]
    reqs = Requisition.query.filter(Requisition.id.in_(req_ids)).all() if req_ids else []
    position_ids = [r.approved_position_id for r in reqs if r.approved_position_id]
    ShortlistReview.query.filter(ShortlistReview.job_id.in_([j.id for j in jobs])).delete(synchronize_session=False)
    for job in jobs:
        db.session.delete(job)                                # its applications, postings and messages go with it
    db.session.flush()
    for req in reqs:
        db.session.delete(req)
    db.session.flush()
    ApprovedPosition.query.filter(ApprovedPosition.id.in_(position_ids),
                                  ApprovedPosition.justification == MARK).delete(synchronize_session=False)
    cands = Candidate.query.filter(Candidate.is_demo.is_(True), Candidate.email.like("%@example.com")).all()
    for cand in cands:
        db.session.delete(cand)
    db.session.commit()
    print(f"Removed {len(jobs)} ICT demo adverts, {len(reqs)} requisitions, {len(position_ids)} positions and "
          f"{len(cands)} applicants.")


if __name__ == "__main__":
    app = create_app()
    app.config["MOCK_EMAIL_ECHO"] = False
    with app.app_context():
        remove_demo() if "--remove" in sys.argv[1:] else add()
