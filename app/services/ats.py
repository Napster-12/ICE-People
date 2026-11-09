"""ATS engine: extracts text from CVs and scores candidates against a job.

The score is a weighted percentage made up of:
  - required skills matched      (45%)
  - preferred skills matched     (15%)
  - years of experience          (20%)
  - education level              (10%)
  - job-description keywords     (10%)
Components that don't apply to a job (e.g. no preferred skills listed) are
dropped and the remaining weights are rescaled so the total is still 100%.
A job can carry its own weights (`ats_weights`, copied from its JD in the library);
a component weighted 0 isn't scored.
"""
import io
import logging
import re
from datetime import date

log = logging.getLogger(__name__)

WEIGHTS = {
    "required": 45,
    "preferred": 15,
    "experience": 20,
    "education": 10,
    "keywords": 10,
}
WEIGHT_LABELS = {
    "required": "Required skills",
    "preferred": "Advantageous skills",
    "experience": "Years of experience",
    "education": "Qualification",
    "keywords": "Job-description keywords",
}


def weights_for(job):
    """The job's own ATS weights, or the standard WEIGHTS."""
    try:
        custom = job["ats_weights"]
    except (KeyError, IndexError):
        custom = None
    return dict(custom) if custom else dict(WEIGHTS)


def parse_weights(raw):
    """Weights typed on a form ({key: text}). Returns (weights, errors); weights is None when they equal the
    standard WEIGHTS, so the job follows any later change to the standard."""
    if not any(str(raw.get(key) or "").strip() for key in WEIGHT_LABELS):
        return None, []                                  # none sent (e.g. an older form): the standard weights
    weights, errors = {}, []
    for key, label in WEIGHT_LABELS.items():
        try:
            value = int(str(raw.get(key, "")).strip())
        except ValueError:
            errors.append(f"{label}: enter a whole number from 0 to 100.")
            continue
        if not 0 <= value <= 100:
            errors.append(f"{label}: enter a whole number from 0 to 100.")
        weights[key] = value
    if not errors and sum(weights.values()) != 100:
        errors.append(f"The ATS weights must add up to 100 (they add up to {sum(weights.values())}).")
    if errors:
        return None, errors
    return (None if weights == WEIGHTS else weights), []

EDUCATION_LEVELS = [
    (0, "None specified"),
    (1, "Matric / Grade 12"),
    (2, "Certificate"),
    (3, "Diploma"),
    (4, "Bachelor's Degree"),
    (5, "Honours / Postgraduate Diploma"),
    (6, "Master's Degree"),
    (7, "Doctorate / PhD"),
]
EDUCATION_LABELS = dict(EDUCATION_LEVELS)

# Highest-level patterns first so the first hit is the best qualification.
_EDU_PATTERNS = [
    (7, r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctor of\b"),
    (6, r"\bmaster'?s?\b|\bmba\b|\bm\.?sc\b|\bm\.?com\b|\bm\.?eng\b"),
    (5, r"\bhonours\b|\bhons\b|\bpostgraduate diploma\b|\bpgdip\b|\bb\.?tech\b"),
    (4, r"\bbachelor'?s?\b|\bdegree\b|\bb\.?com\b|\bb\.?sc\b|\bb\.?a\.?\b|\bllb\b|\bb\.?eng\b|\bbba\b"),
    (3, r"\bdiploma\b|\bn6\b|\bnational diploma\b"),
    (2, r"\bcertificate\b|\bnqf\s?[4-5]\b|\bcertified\b"),
    (1, r"\bmatric\b|\bgrade\s?12\b|\bnsc\b|\bnational senior certificate\b"),
]

_STOPWORDS = set("""
a about above after again all also an and any are as at be because been before
being below between both but by can could did do does doing down during each
few for from further had has have having he her here hers him his how i if in
into is it its itself just me more most my no nor not of off on once only or
other our ours out over own same she should so some such than that the their
them then there these they this those through to too under until up very was
we were what when where which while who whom why will with would you your
able ability work working role position candidate candidates job team company
must strong excellent good great well within including include includes etc
responsible responsibilities requirements required preferred minimum years year
experience knowledge skills skill using use new per key ensure provide support
""".split())


# ---------------------------------------------------------------- extraction

REQUIRED_PACKAGES = {"pypdf": "pypdf", "docx": "python-docx"}  # import name -> pip name


def missing_packages():
    """pip names of CV-reading libraries that can't be imported in this Python."""
    missing = []
    for module, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    return missing


def clean_text(text):
    """Tidy text taken out of a PDF or Word file (8 Nov 2026): ligatures (ﬁ → fi), words hyphenated across a line
    break ("trouble-\nshooting"), letter-spaced headings ("S K I L L S" → "SKILLS") and odd bullets/spaces."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)                  # hyphenated line breaks
    text = re.sub(r"(?<![\w])((?:[A-Z]{1,2} ){3,}[A-Z]{1,2})(?![\w])",       # ...in capitals: "E D U C AT I O N"
                  lambda m: m.group(1).replace(" ", ""), text)
    text = re.sub(r"(?<![\w])((?:[A-Za-z] ){3,}[A-Za-z])(?![\w])",          # letter-spaced words
                  lambda m: m.group(1).replace(" ", ""), text)
    text = re.sub(r"[■●▪•◦►▶✓✔]", " ", text)
    return text


def extract_text(filename, data):
    """Return plain text from a PDF, DOCX or TXT file's bytes.

    A missing library raises ImportError on purpose: it must never be
    mistaken for a CV that has no readable text."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                reader.decrypt("")  # many "protected" CVs only restrict editing, not opening
            return clean_text("\n".join((page.extract_text() or "") for page in reader.pages))
        except Exception as exc:
            log.warning("Could not read PDF %s: %s", filename, exc)
            return ""
    if name.endswith(".docx"):
        import docx
        try:
            document = docx.Document(io.BytesIO(data))
            parts = [p.text for p in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text for cell in row.cells))
            return clean_text("\n".join(parts))
        except Exception as exc:
            log.warning("Could not read DOCX %s: %s", filename, exc)
            return ""
    if name.endswith(".txt"):
        return clean_text(data.decode("utf-8", errors="ignore"))
    return ""


# ------------------------------------------------------------------ helpers

# Requirements written as sentences (8 Nov 2026): "Proficiency in at least one major programming language, such as
# C#/.NET, Java, Python or PHP." is one requirement, met by any of the listed languages, not seven "skills".
_ANY_OF = re.compile(r"\bsuch as\b|\be\.?g\.?|\bat least one\b|\bany\b|\bor\b|\blike\b|\bincluding\b")
_FILLER = set("""
proficiency proficient in at least one major experience experienced with building consuming strong solid sound
skills skill knowledge knowledgeable of understanding the a an good excellent ability to work modern relevant
working familiarity familiar exposure hands-on hands on practical basic advanced background demonstrated proven
version control awareness practices methodologies methodology tools tool platforms platform frameworks framework
certifications certification such as e.g eg like including etc use using other similar equivalent related
written verbal and or is are be will should must have has
""".split())
_KEEP_SLASH = re.compile(r"^[a-z]{1,3}/[a-z]{1,3}$")       # ci/cd, tcp/ip, ui/ux stay one term


def _is_sentences(value):
    """True when a skills field holds sentences (copied from a JD) rather than a short comma list."""
    parts = [p.strip() for p in re.split(r"[,;\n]", value or "") if p.strip()]
    return bool(re.search(r"\bsuch as\b|\be\.g\.", value or "", re.I)) or any(len(p.split()) > 5 for p in parts)


def requirement_items(value):
    """The separate requirements in a skills field: a short comma list stays one skill per comma; sentences split
    on full stops, line breaks and semicolons."""
    if not value:
        return []
    if not _is_sentences(value):
        return split_skills(value)
    items, seen = [], set()
    for part in re.split(r"\.\s*,\s*|\.\s*$|\.\s+(?=[a-z])|\n|;", value.strip(), flags=re.I):
        item = re.sub(r"^[\s\-•*\d.)]+", "", part).strip(" ,.")
        if item and item.lower() not in seen:
            seen.add(item.lower())
            items.append(item)
    return items


def requirement_terms(item):
    """The skills named in one requirement: "web development skills: HTML, CSS, JavaScript and a modern framework,
    such as React, Angular or Vue" -> web development, html, css, javascript, react, angular, vue."""
    text = _normalise(item).strip(" .")
    tokens = []
    for token in text.split():
        if "/" in token and not _KEEP_SLASH.match(token.strip(",.:;()")):
            tokens.append(token.replace("/", " , "))         # c#/.net -> c#, .net (two terms)
        else:
            tokens.append(token)
    text = " ".join(tokens)
    pieces = re.split(r"[,;:()]|\bsuch as\b|\be\.?g\.?|\bincluding\b|\blike\b|\bor\b|\band\b|\bwith\b|\bin\b", text)
    terms = []
    for piece in pieces:
        words = [w for w in piece.split() if w.strip(".") and w.strip(".") not in _FILLER]
        term = " ".join(words).strip(" .")
        if term and len(term.split()) <= 4 and term not in terms and (len(term) >= 2 or term in ("c", "r")):
            terms.append(term)
    return terms


def requirement_met(profile, item, plain=True):
    """(met, found terms) for one requirement. plain: the field is a short comma list, so the item is one skill.
    Otherwise a list offered as alternatives (such as / or / at least one) needs any one of the named skills, and
    any other requirement at least half of them."""
    if plain:
        found = has_skill(profile, item)
        return found, ([item] if found else [])
    terms = requirement_terms(item)
    if not terms:
        return has_skill(profile, item), []
    found = [t for t in terms if has_skill(profile, t)]
    if _ANY_OF.search(_normalise(item)):
        return bool(found), found
    return len(found) * 2 >= len(terms), found


def requirement_label(item, limit=60):
    """A short name for a requirement chip."""
    label = re.split(r",|\bsuch as\b|:", item, maxsplit=1, flags=re.I)[0].strip(" .")
    return label if len(label) <= limit else label[:limit - 1].rstrip() + "…"


def split_skills(value):
    """'Excel, SQL; Power BI' -> ['excel', 'sql', 'power bi']"""
    if not value:
        return []
    seen, out = set(), []
    for part in re.split(r"[,;\n]", value):
        skill = part.strip().lower()
        if skill and skill not in seen:
            seen.add(skill)
            out.append(skill)
    return out


def _normalise(text):
    text = (text or "").lower().replace("’", "").replace("'", "").replace("&", " and ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r" ?\n[\n ]*", "\n", text)          # keep line breaks: _near looks within one line or sentence


def has_term(text, term):
    """Whole-term match that also works for terms like 'c++' or 'node.js',
    and accepts plurals ('specification' matches 'specifications')."""
    plural = "(?:s|es)?" if term[-1:].isalpha() else ""
    pattern = (r"(?<![a-z0-9])" + re.escape(term).replace(r"\ ", r"[\s\-_/]*")
               + plural + r"(?![a-z0-9])")
    return re.search(pattern, text) is not None


# Skills that mean the same thing in a CV (8 Nov 2026: the ATS missed "Microsoft 365" for "office 365", "first-line
# support" for "service desk" and so on). Each group is matched as one skill. Lower case; add groups as needed.
SYNONYMS = [
    {"office 365", "microsoft 365", "m365", "o365", "ms 365"},
    {"service desk", "help desk", "helpdesk", "it support", "first line support", "first-line support",
     "end user support", "end-user support", "technical support", "desktop support", "it helpdesk"},
    {"ticketing", "ticketing system", "ticket", "tickets", "incident management", "servicenow", "service now",
     "jira service management", "freshdesk", "zendesk", "sysaid", "manageengine"},
    {"active directory", "azure ad", "azure active directory", "entra id", "microsoft entra", "ad ds"},
    {"power bi", "powerbi"},
    {"sql server", "mssql", "ms sql", "microsoft sql server", "t-sql", "tsql"},
    {"postgresql", "postgres"},
    {"javascript", "js", "ecmascript"},
    {"typescript", "ts"},
    {"c#", "c sharp", "csharp"},
    {"git", "github", "gitlab", "bitbucket"},
    {"rest api", "rest apis", "restful", "restful api", "restful apis", "web api", "web apis"},
    {"machine learning", "ml"},
    {"artificial intelligence", "ai"},
    {"customer service", "client service", "customer care", "client care", "customer support", "client support"},
    {"communication", "communication skills", "communicating"},
    {"team", "teamwork", "team work", "team player", "work in a team", "collaboration"},
    {"independently", "independent", "independent work", "self-motivated", "self motivated", "minimal supervision"},
    {"problem solving", "problem-solving", "troubleshooting", "trouble shooting"},
    {"networking", "network administration", "lan", "wan", "tcp/ip", "ip addressing", "ccna"},
    {"drivers licence", "drivers license", "driving licence", "driving license", "code 8", "code 10", "code 14",
     "code eb", "code c1", "code ec"},
    {"microsoft office", "ms office", "office suite", "word, excel"},
    {"excel", "spreadsheets"},
    {"data visualisation", "data visualization", "visualisations", "visualizations", "dashboards"},
    {"requirements gathering", "requirements elicitation", "gather requirements", "gathering requirements",
     "requirements analysis"},
    {"itil", "itil v3", "itil v4", "itil foundation"},
    {"etl", "extract transform load", "data pipelines"},
    {"bookkeeping", "book keeping"},
    {"funeral arrangements", "funeral arranging", "funeral services"},
]
_SYNONYM_INDEX = {term: group for group in SYNONYMS for term in group}

_STEM_SUFFIXES = ("isations", "izations", "isation", "ization", "ations", "ation", "ments", "ment", "ings", "ing", "ly",
                  "ers", "er", "ies", "ied", "es", "ed", "s")


def _stem(word):
    """A rough stem so 'gathering', 'gathered' and 'gather' (or 'requirements' and 'requirement') compare equal;
    analyse, analysed, analysis, analyst and analyze all become 'analys'."""
    m = re.match(r"^(\w{2,}?)(ys|yz)(is|es|e|ed|er|ers|ing|t|ts)?$", word)
    if m:
        return m.group(1) + "ys"
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def _variants(skill):
    """Ways a skill is written: 'ms excel' also matches 'excel', 'reactjs' matches 'react' and 'react.js', 'html5'
    matches 'html', British and American spellings, and the skill's synonym group (SYNONYMS)."""
    skill = _normalise(skill).strip()
    variants = {skill, re.sub(r"^(ms|microsoft)\s+", "", skill)}
    variants |= _SYNONYM_INDEX.get(skill, set())
    for v in list(variants):
        if v.endswith("analysis"):
            variants.add(v[:-len("analysis")] + "analyst")
        base = re.sub(r"(?<=[a-z])\.?\s?js$", "", v)                       # reactjs, react.js, react js -> react
        if base != v and len(base) >= 3:
            variants |= {base, base + ".js", base + "js"}
        variants.add(re.sub(r"(?<=[a-z]{2})\d(\.\d)?$", "", v))            # html5, css3, python3 -> html, css, python
        for a, b in (("isation", "ization"), ("ise", "ize"), ("yse", "yze"), ("modelling", "modeling"),
                     ("licence", "license"), ("programme", "program"), ("colour", "color"), ("centre", "center")):
            if a in v:
                variants.add(v.replace(a, b))
            if b in v:
                variants.add(v.replace(b, a))
    for v in list(variants):
        variants |= _SYNONYM_INDEX.get(v, set())
    return [v for v in variants if v and len(v) >= 1]


_WORD = re.compile(r"[a-z0-9][a-z0-9+#.]*")


def _near(text, skill, window=6):
    """A skill of 2–4 words also counts when all its words (in any order and form) appear within a few words of each
    other in the same sentence: "Gather and document business requirements" shows "requirements gathering"."""
    words = [_stem(w) for w in _WORD.findall(skill) if w not in _STOPWORDS or len(_WORD.findall(skill)) <= 2]
    if not 2 <= len(words) <= 4:
        return False
    for sentence in re.split(r"[.;:!?\n|•]", text):
        tokens = [_stem(t.strip(".")) for t in _WORD.findall(sentence)]
        positions = [[i for i, t in enumerate(tokens) if t == w] for w in words]
        if not all(positions):
            continue
        for start in positions[0]:
            spots = [min(p, key=lambda i: abs(i - start)) for p in positions]
            if max(spots) - min(spots) <= window:
                return True
    return False


def has_skill(text, skill):
    variants = _variants(skill)
    if any(has_term(text, v) for v in variants):
        return True
    return any(_near(text, v) for v in variants if " " in v.strip())


_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_MON = r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?|(\d{1,2})\s*/)\s*"
_RANGE = re.compile(
    rf"(?:{_MON})?((?:19|20)\d\d)\s*(?:-|–|—|to|until)\s*"
    rf"(?:(?:{_MON})?((?:19|20)\d\d)|(present|current|now|date|today))", re.I)
# Lines about studies, so the years spent studying aren't counted as work.
_EDU_LINE = re.compile(r"universit|college|school|academy|institut|tvet|campus|diploma|degree|"
                       r"bachelor|honours|matric|grade\s?12|certificate|studies|qualification", re.I)


def _month_index(name, number, year, default):
    if name:
        month = _MONTHS[name[:3].lower()]
    elif number and 1 <= int(number) <= 12:
        month = int(number)
    else:
        month = default
    return int(year) * 12 + month - 1


def experience_from_dates(text, today=None):
    """Years of work experience from employment date ranges such as
    'Apr 2023 – Apr 2025', '2019 - 2022' or '03/2020 – Present'.
    Overlapping jobs are merged and study periods are skipped."""
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    spans, previous = [], ""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if not (_EDU_LINE.search(line) or _EDU_LINE.search(previous)):
            for m in _RANGE.finditer(line):
                start = _month_index(m.group(1), m.group(2), m.group(3), 1)
                end = now if m.group(7) else _month_index(m.group(4), m.group(5), m.group(6), 12)
                end = min(end, now)
                if 0 <= end - start <= 45 * 12:
                    spans.append((start, end + 1))
        previous = line
    months, current_end = 0, None
    for start, end in sorted(spans):
        if current_end is None or start >= current_end:
            months += end - start
            current_end = end
        elif end > current_end:
            months += end - current_end
            current_end = end
    return round(months / 12, 1)


def detect_years(text):
    """Best guess at total years of experience in the CV: an explicit
    'N years of experience' phrase, or the sum of employment date ranges."""
    lowered = (text or "").lower()
    found = [int(n) for n in re.findall(
        r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}?\s+experience", lowered)]
    if not found:
        found = [int(n) for n in re.findall(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", lowered)]
    found = [n for n in found if n <= 50]
    return max([float(n) for n in found] + [experience_from_dates(text)])


def detect_education(text):
    for level, pattern in _EDU_PATTERNS:
        if re.search(pattern, text):
            return level
    return 0


def _keywords(text, limit=40):
    counts = {}
    for word in re.findall(r"[a-z][a-z+#.\-]{2,}", text):
        word = word.strip(".-")
        if len(word) < 3 or word in _STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:limit]]


# ------------------------------------------------------------------ scoring

def score_candidate(job, candidate):
    """Score a candidate against a job.

    `job` and `candidate` are mappings (e.g. sqlite3.Row) with the columns
    used below. Returns (score_percent, breakdown_dict).
    """
    cv_text = _normalise(candidate["cv_text"])
    profile = _normalise(" ".join([
        cv_text,
        candidate["skills"] or "",
        candidate["current_title"] or "",
    ]))

    components = {}

    for key, field in (("required", "required_skills"), ("preferred", "preferred_skills")):
        items = requirement_items(job[field])
        if not items:
            continue
        matched, missing, found, details = [], [], {}, {}
        plain = not _is_sentences(job[field])
        for item in items:
            met, terms = requirement_met(profile, item, plain)
            label = item if plain else requirement_label(item)
            if not plain:
                details[label] = item
            (matched if met else missing).append(label)
            if terms and not plain:
                found[label] = terms
        components[key] = {"score": 100 * len(matched) / len(items), "matched": matched, "missing": missing,
                           "found": found, "details": details}

    min_exp = job["min_experience"] or 0
    stated = candidate["years_experience"]
    # Use the higher of the applicant's answer and what the CV shows, so a
    # "0" typed on the form can't hide real experience listed in the CV.
    years = max(stated or 0, detect_years(candidate["cv_text"]))
    if min_exp > 0:
        components["experience"] = {
            "score": min(1.0, years / min_exp) * 100,
            "candidate_years": years,
            "required_years": min_exp,
        }

    min_edu = job["min_education"] or 0
    edu = max(candidate["education_level"] or 0, detect_education(cv_text))
    if min_edu > 0:
        components["education"] = {
            "score": 100 if edu >= min_edu else 100 * edu / min_edu,
            "candidate_level": EDUCATION_LABELS.get(edu, "Unknown"),
            "required_level": EDUCATION_LABELS.get(min_edu, "Unknown"),
        }

    keywords = _keywords(_normalise(f"{job['title']} {job['description']}"))
    if keywords:
        hits = [k for k in keywords if has_term(profile, k)]
        # Hitting ~60% of the job's vocabulary is treated as a full match.
        components["keywords"] = {
            "score": min(100.0, 100 * len(hits) / (len(keywords) * 0.6)),
            "matched": hits[:15],
        }

    weights = weights_for(job)
    components = {k: c for k, c in components.items() if weights.get(k, 0) > 0}
    if not components:
        return 0.0, {"components": {}, "note": "Job has no screening criteria."}

    total_weight = sum(weights[k] for k in components)
    score = sum(weights[k] * c["score"] for k, c in components.items()) / total_weight
    for key, comp in components.items():
        comp["weight"] = round(100 * weights[key] / total_weight, 1)
        comp["score"] = round(comp["score"], 1)

    breakdown = {
        "components": components,
        "detected_years": years,
        "detected_education": EDUCATION_LABELS.get(edu, "Unknown"),
        "cv_text_found": bool(cv_text.strip()),
    }
    return round(score, 1), breakdown
