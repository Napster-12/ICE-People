"""Generate realistic dummy data for testing the portal.

    python seed_dummy.py              # 100 jobs + 1000 applicants (with PDF CVs)
    python seed_dummy.py --jobs 20 --applicants 200
    python seed_dummy.py --clear      # remove ALL dummy data, keep real records

Every generated job and candidate is flagged is_demo = 1, so --clear never
touches real jobs or real applicants. Dummy applicants only apply to dummy jobs.
"""
import argparse
import json
import random
import secrets
import sqlite3
from datetime import date, datetime, timedelta

import app as portal
import ats

FIRST = ("Thandiwe Sipho Lerato Nomvula Themba Ayanda Zanele Bongani Precious Mandla Nokuthula Kagiso "
         "Lindiwe Sibusiso Naledi Thabo Zinhle Mpho Palesa Lwazi Ntombi Andile Khanyisile Siyabonga "
         "Nompumelelo Jabulani Busisiwe Tshepo Refilwe Musa Anele Hlengiwe Priya Rajesh Michelle Jason "
         "Fatima Yusuf Chantelle Pieter Annelie Ruan Sanele Nonhlanhla Mlungisi Thulani Phumzile Sizwe "
         "Nandi Lungile Kwanele Ziyanda Xolani Asanda Bheki Nosipho Vusi Dineo Karabo Tumelo Keabetswe "
         "Amahle Lethabo Minenhle Snethemba Ashwin Kavitha Shireen Bradley Candice Johan").split()
LAST = ("Dlamini Ndlovu Zulu Mkhize Ngcobo Khumalo Mthembu Nkosi Cele Shabalala Buthelezi Mokoena Nkuna "
        "Molefe Naidoo Pillay Govender Botha Smith Mahlangu Maseko Sithole Gumede Hadebe Zungu Mabaso "
        "Ntuli Mazibuko Ngubane Majola Msomi Mchunu Xaba Radebe Mofokeng Masilela Chetty Moodley Reddy "
        "Pretorius Nel Jacobs Williams Hlongwane Shezi Mnguni Zondi Khoza Biyela Mngomezulu").split()
LOCATIONS = ["Durban, KwaZulu-Natal"] * 6 + [
    "Pietermaritzburg, KwaZulu-Natal", "Richards Bay, KwaZulu-Natal", "Newcastle, KwaZulu-Natal",
    "Ladysmith, KwaZulu-Natal", "Port Shepstone, KwaZulu-Natal", "Vryheid, KwaZulu-Natal",
    "Johannesburg, Gauteng", "Pretoria, Gauteng", "Soweto, Gauteng", "East London, Eastern Cape",
    "Mthatha, Eastern Cape", "Gqeberha, Eastern Cape", "Cape Town, Western Cape",
    "Polokwane, Limpopo", "Mbombela, Mpumalanga", "Bloemfontein, Free State"]
EMPLOYERS = ["Old Mutual", "Sanlam", "AVBOB", "Doves Group", "Clientele", "Hollard", "Shoprite Group",
             "Telkom", "eThekwini Municipality", "Standard Bank", "Capitec", "Dimension Data",
             "Netcare", "Pick n Pay", "Vodacom", "Tongaat Hulett", "Transnet", "Mr Price Group",
             "a regional funeral parlour", "a national retail chain", "a BPO contact centre"]
SCHOOLS = {1: "National Senior Certificate (Matric)", 2: "Higher Certificate", 3: "National Diploma",
           4: "Bachelor's Degree", 5: "Honours Degree", 6: "Master's Degree", 7: "PhD"}
INSTITUTIONS = ["University of KwaZulu-Natal", "Durban University of Technology", "Mangosuthu University of Technology",
                "UNISA", "University of Johannesburg", "Tshwane University of Technology",
                "Nelson Mandela University", "Walter Sisulu University", "Richfield Graduate Institute",
                "Boston City Campus", "Damelin", "Elangeni TVET College"]
FILLER_SKILLS = ["teamwork", "time management", "communication", "problem solving", "isiZulu",
                 "english", "attention to detail", "customer focus", "presentation skills"]

# (title, department, required, preferred, min years, min education, field of study, duties)
ROLES = [
    ("Funeral Policy Sales Consultant", "Sales", "sales, customer service, fais, communication",
     "re5, isizulu, drivers licence, crm, cold calling", 1, 1, "Sales & Marketing",
     ["Sold funeral and life policies to walk-in and field clients", "Met monthly new-business targets",
      "Built referral networks with churches and burial societies"]),
    ("Sales Team Leader", "Sales", "sales, team leadership, fais, coaching, reporting",
     "re5, crm, excel, drivers licence", 4, 2, "Business Management",
     ["Led a team of 12 consultants to exceed targets", "Coached consultants on FAIS-compliant selling",
      "Compiled weekly sales reporting for management"]),
    ("Branch Administrator", "Operations", "administration, ms office, filing, customer service",
     "excel, data capturing, sage, isizulu", 2, 1, "Office Administration",
     ["Processed policy applications and amendments", "Managed branch filing and records",
      "Handled client queries at the front desk"]),
    ("Branch Manager", "Operations", "branch management, people management, budgeting, customer service, reporting",
     "funeral services, fais, excel, drivers licence", 5, 3, "Business Management",
     ["Managed daily branch operations and staff of 15", "Owned branch budget and cost control",
      "Drove service levels and complaint resolution"]),
    ("Claims Assessor", "Insurance", "claims, assessment, insurance, attention to detail, ms office",
     "fraud detection, excel, re5, nqf 5", 2, 2, "Insurance",
     ["Assessed and validated funeral claims", "Detected and escalated fraudulent claims",
      "Liaised with clients and undertakers on claim documents"]),
    ("Underwriter", "Insurance", "underwriting, risk assessment, insurance, excel",
     "actuarial, re5, reinsurance, sql", 3, 4, "Actuarial Science",
     ["Assessed risk on new group schemes", "Priced funeral schemes within guidelines",
      "Reviewed policy wording with compliance"]),
    ("Call Centre Agent", "Customer Service", "customer service, call centre, communication, computer literacy",
     "isizulu, sales, crm, retention", 0, 1, "General",
     ["Handled 80+ inbound calls per day", "Resolved policy and premium queries",
      "Retained clients wanting to cancel"]),
    ("Customer Service Supervisor", "Customer Service", "customer service, supervision, call centre, reporting, coaching",
     "crm, excel, workforce management, quality assurance", 4, 2, "Business Management",
     ["Supervised a team of 20 agents", "Monitored call quality and service levels",
      "Produced daily performance reports"]),
    ("Funeral Director", "Funeral Services", "funeral services, arrangements, customer care, compassion",
     "embalming, drivers licence, isizulu, grief counselling", 3, 1, "Funeral Services",
     ["Arranged and conducted funerals with dignity", "Guided families through arrangements",
      "Coordinated with mortuary, transport and venues"]),
    ("Mortuary Attendant", "Funeral Services", "mortuary, hygiene, health and safety, physical fitness",
     "embalming, drivers licence, first aid", 1, 1, "General",
     ["Prepared deceased according to procedure", "Maintained mortuary hygiene standards",
      "Kept accurate body register records"]),
    ("Hearse Driver", "Fleet & Transport", "drivers licence, prdp, defensive driving, punctuality",
     "code 10, vehicle maintenance, first aid", 2, 1, "General",
     ["Transported deceased and families safely", "Completed vehicle checks before trips",
      "Kept trip logs accurate"]),
    ("Fleet Coordinator", "Fleet & Transport", "fleet management, scheduling, vehicle maintenance, excel",
     "tracking systems, drivers licence, procurement", 3, 2, "Logistics",
     ["Scheduled a fleet of 40 vehicles", "Managed services and repairs with suppliers",
      "Tracked fuel usage and costs"]),
    ("HR Business Partner", "Human Resources", "employee relations, labour relations, performance management, recruitment, excel",
     "sage, payroll, coaching, ccma", 5, 4, "Human Resource Management",
     ["Advised managers on disciplinary and grievance matters", "Ran performance management cycles",
      "Represented the company at the CCMA"]),
    ("HR Administrator", "Human Resources", "hr administration, recruitment, onboarding, ms office",
     "sage, payroll, leave management, popia", 2, 3, "Human Resource Management",
     ["Captured new employees and terminations", "Coordinated interviews and onboarding",
      "Maintained personnel files"]),
    ("Payroll Administrator", "Human Resources", "payroll, sage, excel, attention to detail",
     "sars, uif, leave management, vip payroll", 3, 3, "Payroll Administration",
     ["Processed monthly payroll for 600 staff", "Submitted EMP201 and UIF returns",
      "Reconciled payroll to the general ledger"]),
    ("Accountant", "Finance", "accounting, reconciliations, ifrs, excel, month end",
     "sage, pastel, tax, saipa", 3, 4, "Accounting",
     ["Prepared monthly management accounts", "Performed balance sheet reconciliations",
      "Supported external audit"]),
    ("Debtors Clerk", "Finance", "debtors, reconciliations, excel, attention to detail",
     "pastel, sage, collections, debit orders", 1, 2, "Accounting",
     ["Allocated premium receipts", "Followed up on unpaid debit orders", "Reconciled debtors ledger"]),
    ("Data Analyst", "Finance", "sql, power bi, excel, data analysis",
     "python, actuarial, insurance, dax", 3, 4, "Statistics",
     ["Built Power BI dashboards for executives", "Analysed lapse and claims data",
      "Automated reporting with SQL"]),
    ("Systems Analyst", "ICT", "systems analysis, business analysis, requirements, functional specification, sql, sdlc, agile",
     "visio, erp, crm, jira, itil", 3, 1, "Information Technology",
     ["Gathered and documented business requirements", "Wrote functional specifications for developers",
      "Coordinated user acceptance testing"]),
    ("IT Support Technician", "ICT", "hardware, help desk, troubleshooting, windows, networking, comptia a+",
     "m365, active directory, itil, drivers licence, vpn", 2, 2, "Information Technology",
     ["Supported 300 users across 12 branches", "Imaged and deployed laptops",
      "Resolved network and printer issues"]),
    ("Software Developer", "ICT", "c#, .net, sql, javascript, git",
     "azure, react, api, agile, devops", 3, 4, "Computer Science",
     ["Built internal policy administration features", "Developed REST APIs in .NET",
      "Maintained SQL Server databases"]),
    ("Network Administrator", "ICT", "networking, firewalls, vpn, ccna, troubleshooting",
     "fortinet, sophos, wifi, linux", 3, 3, "Information Technology",
     ["Managed branch WAN and VPN links", "Configured firewalls and switches", "Monitored network uptime"]),
    ("Marketing Coordinator", "Marketing", "marketing, social media, content creation, communication",
     "canva, adobe, events, community engagement", 2, 3, "Marketing",
     ["Ran Facebook and Instagram campaigns", "Organised community activations",
      "Created marketing material with Canva"]),
    ("Compliance Officer", "Legal & Compliance", "compliance, fais, popia, risk management, reporting",
     "fica, policyholder protection rules, audit, llb", 4, 4, "Law",
     ["Monitored FAIS and POPIA compliance", "Reported to the FSCA", "Trained staff on compliance"]),
    ("Receptionist", "Operations", "reception, switchboard, customer service, ms office",
     "isizulu, admin, diary management", 1, 1, "Office Administration",
     ["Managed switchboard and visitors", "Booked meeting rooms and diaries", "Handled courier logs"]),
    ("Facilities Officer", "Operations", "facilities management, maintenance, health and safety, procurement",
     "ohs act, contractors, budgeting, drivers licence", 3, 2, "Facilities Management",
     ["Coordinated building maintenance", "Managed cleaning and security contractors",
      "Ran health and safety inspections"]),
]
LEVELS = [("", 0), ("Junior ", -2), ("Senior ", 3)]


def pdf_bytes(lines):
    """A minimal single-page PDF with real text (so the ATS can read it)."""
    def esc(s):
        return s.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    y, ops = 800, ["BT"]
    for text, size in lines:
        if y < 50:
            break
        ops.append(f"/F{2 if size > 11 else 1} {size} Tf 1 0 0 1 50 {y} Tm ({esc(text)}) Tj")
        y -= size + 5
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return bytes(out)


def wrap(text, width=95):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return out + [line] if line else out


def build_jobs(rng, n):
    today = date.today()
    jobs = []
    for i in range(n):
        title, dept, req, pref, yrs, edu, _field, duties = ROLES[i % len(ROLES)]
        prefix, delta = rng.choice(LEVELS) if i >= len(ROLES) else ("", 0)
        if title.startswith(("Branch Manager", "HR Business", "Compliance", "Sales Team", "Customer Service Sup")):
            prefix, delta = "", 0  # already senior titles
        status = "Closed" if rng.random() < 0.2 else "Open"
        created = today - timedelta(days=rng.randint(3, 120))
        closing = (today - timedelta(days=rng.randint(1, 60)) if status == "Closed"
                   else today + timedelta(days=rng.randint(5, 60)))
        location = rng.choice(LOCATIONS)
        desc = (f"Icebolethu Group is looking for a {prefix}{title} to join our {dept} team in {location}.\n\n"
                "RESPONSIBILITIES\n" + "\n".join(f"• {d}." for d in duties) +
                "\n\nREQUIREMENTS\n"
                f"• {ats.EDUCATION_LABELS[edu] if edu else 'Matric'} or higher.\n"
                f"• At least {max(0, yrs + delta)} years of relevant experience.\n"
                f"• Key skills: {req}.\n\n"
                "Icebolethu embraces the principles of the Employment Equity Act.")
        jobs.append({
            "title": f"{prefix}{title}", "department": dept, "location": location,
            "job_type": rng.choices(portal.JOB_TYPES, weights=[80, 4, 10, 3, 3])[0],
            "description": desc, "required_skills": req, "preferred_skills": pref,
            "min_experience": max(0, yrs + delta), "min_education": edu,
            "closing_date": closing.isoformat(), "status": status,
            "created_at": datetime.combine(created, datetime.min.time()).replace(hour=rng.randint(8, 16)).isoformat(),
            "is_demo": 1, "_role": ROLES[i % len(ROLES)],
        })
    return jobs


def build_candidate(rng, n, role, used_emails):
    title, _dept, req, pref, yrs, edu, field, duties = role
    tier = rng.choices(["strong", "medium", "weak"], weights=[25, 45, 30])[0]
    req_s, pref_s = ats.split_skills(req), ats.split_skills(pref)
    keep = {"strong": (0.85, 1.0, 0.6), "medium": (0.45, 0.75, 0.3), "weak": (0.0, 0.3, 0.0)}[tier]
    skills = rng.sample(req_s, round(len(req_s) * rng.uniform(keep[0], keep[1])))
    skills += [s for s in pref_s if rng.random() < keep[2]]
    if tier == "weak":
        other = rng.choice(ROLES)
        skills += rng.sample(ats.split_skills(other[2]), 2)
    skills += rng.sample(FILLER_SKILLS, 3)
    years = {"strong": rng.randint(max(yrs, 1), yrs + 8), "medium": rng.randint(max(0, yrs - 2), yrs + 3),
             "weak": rng.randint(0, max(1, yrs))}[tier]
    edu_level = max(1, min(7, edu + {"strong": rng.randint(0, 2), "medium": rng.randint(-1, 1),
                                     "weak": rng.randint(-3, 0)}[tier]))

    first, last = rng.choice(FIRST), rng.choice(LAST)
    email = f"{first}.{last}{n}@example.com".lower()
    used_emails.add(email)
    location = rng.choice(LOCATIONS)
    current = title if tier != "weak" else rng.choice(["Cashier", "General Worker", "Sales Assistant",
                                                       "Admin Clerk", "Security Officer", "Intern"])
    employers = rng.sample(EMPLOYERS, 2)
    grad_year = date.today().year - years - rng.randint(0, 3)

    lines = [(f"{first} {last}", 18), (f"{current} | {location}", 11),
             (f"{email} | 0{rng.choice([6,7,8])}{rng.randint(1,9)} {rng.randint(100,999)} {rng.randint(1000,9999)}", 10),
             ("", 6), ("PROFILE", 13)]
    summary = (f"{current} with {years} years of experience. Skilled in {', '.join(skills[:4])}. "
               "Reliable, hard-working and committed to excellent service.")
    lines += [(l, 10) for l in wrap(summary)]
    lines += [("", 6), ("EXPERIENCE", 13)]
    if years:
        start = date.today().year - years
        split = max(1, years // 2)
        lines += [(f"{current} - {employers[0]} ({start + split} - present)", 11)]
        lines += [(f"- {d}" if tier != "weak" else f"- General duties and {skills[-1]}", 10) for d in duties[:3]]
        lines += [(f"{'Assistant ' if tier != 'strong' else ''}{current} - {employers[1]} ({start} - {start + split})", 11),
                  (f"- Applied {', '.join(skills[:3])} daily", 10)]
    else:
        lines += [("Recent graduate seeking a first opportunity.", 10)]
    lines += [("", 6), ("EDUCATION", 13),
              (f"{SCHOOLS[edu_level]}{' in ' + field if edu_level >= 2 else ''} - "
               f"{rng.choice(INSTITUTIONS) if edu_level >= 2 else 'Local High School'} ({grad_year})", 10)]
    if edu_level >= 2:
        lines.append((f"National Senior Certificate (Matric) ({grad_year - 3})", 10))
    lines += [("", 6), ("SKILLS", 13)] + [(l, 10) for l in wrap(", ".join(s.title() for s in skills))]
    lines += [("", 6), ("REFERENCES", 13), ("Available on request.", 10)]

    data = pdf_bytes(lines)
    return {
        "full_name": f"{first} {last}", "email": email, "phone": f"0{rng.randint(60, 84)}{rng.randint(1000000, 9999999)}",
        "location": location, "current_title": current, "years_experience": years,
        "education_level": edu_level, "skills": ", ".join(skills[:8]),
        "cv_filename": f"{first}_{last}_CV.pdf".replace(" ", "_"), "cv_mimetype": "application/pdf",
        "cv_data": data, "cv_text": ats.extract_text("cv.pdf", data), "consent": 1, "is_demo": 1,
    }


def pick_status(rng, score, job):
    closed = job["status"] == "Closed"
    if score >= 75:
        opts = (["Shortlisted", "Interview", "Offer", "Hired", "Rejected"], [30, 30, 12, 13, 15]) if closed else \
               (["New", "Screening", "Shortlisted", "Interview", "Offer"], [30, 20, 25, 20, 5])
    elif score >= 50:
        opts = (["Screening", "Shortlisted", "Rejected"], [30, 15, 55]) if closed else \
               (["New", "Screening", "Shortlisted", "Rejected"], [45, 30, 10, 15])
    else:
        opts = (["Rejected"], [1]) if closed else (["New", "Screening", "Rejected"], [45, 10, 45])
    return rng.choices(*opts)[0]


def insert(db, table, row):
    cols = ", ".join(row)
    return db.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())).lastrowid


def seed(n_jobs, n_applicants, seed_value):
    rng = random.Random(seed_value)
    portal.init_db()
    db = sqlite3.connect(portal.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    refs = {r[0] for r in db.execute("SELECT reference FROM applications")}

    def ref():
        while True:
            r = "ICE-" + secrets.token_hex(4).upper()
            if r not in refs:
                refs.add(r)
                return r

    jobs = build_jobs(rng, n_jobs)
    for job in jobs:
        role = job.pop("_role")
        job["id"] = insert(db, "jobs", job)
        job["_role"] = role
    by_role = {}
    for job in jobs:
        by_role.setdefault(job["_role"][0], []).append(job)

    used, n_apps = set(), 0
    start_n = db.execute("SELECT COALESCE(MAX(id), 0) FROM candidates").fetchone()[0] + 1
    for i in range(n_applicants):
        role = rng.choice([r for r in ROLES if r[0] in by_role])
        cand = build_candidate(rng, start_n + i, role, used)
        first_applied = min(datetime.fromisoformat(j["created_at"]) for j in by_role[role[0]])
        applied_at = first_applied + timedelta(days=rng.randint(0, 20), hours=rng.randint(0, 9))
        applied_at = min(applied_at, datetime.now() - timedelta(hours=1))
        cand["created_at"] = cand["updated_at"] = applied_at.isoformat(timespec="seconds")
        cand["id"] = insert(db, "candidates", cand)

        # Most apply to 1 matching job; some to 2; ~15% also apply to an unrelated job.
        targets = rng.sample(by_role[role[0]], min(len(by_role[role[0]]), rng.choice([1, 1, 1, 2])))
        if rng.random() < 0.15:
            targets.append(rng.choice(jobs))
        for job in {j["id"]: j for j in targets}.values():
            score, breakdown = ats.score_candidate(job, cand)
            status = pick_status(rng, score, job)
            insert(db, "applications", {
                "reference": ref(), "candidate_id": cand["id"], "job_id": job["id"],
                "cover_note": rng.choice(["", "", f"I am passionate about {job['department'].lower()} and would love to grow with Icebolethu.",
                                          "I am available immediately and willing to relocate."]),
                "score": score, "breakdown": json.dumps(breakdown), "status": status,
                "notes": "Strong interview, references checked." if status in ("Offer", "Hired") else "",
                "source": "Applied", "created_at": cand["created_at"], "updated_at": cand["created_at"]})
            n_apps += 1
        insert(db, "applications", {
            "reference": ref(), "candidate_id": cand["id"], "job_id": None, "score": 0, "breakdown": "{}",
            "status": "New", "source": "Talent pool", "created_at": cand["created_at"], "updated_at": cand["created_at"]})
        if (i + 1) % 200 == 0:
            print(f"  {i + 1} applicants…")
    db.commit()
    print(f"Added {len(jobs)} dummy jobs, {n_applicants} dummy applicants and {n_apps} job applications.")


def clear():
    portal.init_db()
    db = sqlite3.connect(portal.DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    c = db.execute("DELETE FROM candidates WHERE is_demo = 1").rowcount
    j = db.execute("DELETE FROM jobs WHERE is_demo = 1").rowcount
    db.commit()
    db.execute("VACUUM")
    print(f"Removed {j} dummy jobs and {c} dummy applicants (and their applications).")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jobs", type=int, default=100)
    p.add_argument("--applicants", type=int, default=1000)
    p.add_argument("--seed", type=int, default=2026, help="random seed, for repeatable data")
    p.add_argument("--clear", action="store_true", help="remove all dummy data")
    a = p.parse_args()
    clear() if a.clear else seed(a.jobs, a.applicants, a.seed)
