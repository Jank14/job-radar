"""Role / level / location classification and priority scoring.

Everything here is pure functions so it can be unit-tested without network.
"""
from __future__ import annotations

import re
import time

# ───────────────────────────── role families ─────────────────────────────
# Matched against the TITLE. Order = display order.
FAMILIES = {
    "Computer Vision": r"computer vision|\bcv\b|perception|\bvision\b|3d (vision|reconstruction|perception)|neural rendering|gaussian splat|imaging|image (generation|understanding|processing|models?)|video (generation|understanding|models?|ai|ml)|multimodal|multi-modal|vlm|visual (generation|understanding|search|ai|intelligence)|robot learning|embodied|autonomy|\bslam\b|lidar|camera|geospatial|remote sensing",
    "ML Engineer": r"machine[- ]learning|\bml\b|\bmle\b|\bai/ml\b|\bml/ai\b|deep[- ]learning|\bai (software )?engineer|applied ai|applied scientist|ai infrastructure|ml (infra|platform|systems)|inference|model (training|serving|optimization)|\bai\b.*\bengineer\b|\bengineer\b.*\b(ai|ml)\b",
    "GenAI / LLM": r"generative|gen[- ]?ai|\bllms?\b|large language|language model|\bnlp\b|natural language|foundation model|diffusion|post[- ]training|pre[- ]training|\brl\b|reinforcement learning|ai agents?|agentic|speech|audio (ml|ai|models?|generation|research)",
    "Research Engineer": r"research engineer|member of (the )?technical staff|\bmts\b|ai resident|residency|research fellow|fellows? program|\bfellow\b",
    "Forward Deployed": r"forward[- ]deployed|\bfde\b|deployed engineer|deployment strategist|applied ai engineer|solutions? engineer.*\b(ai|ml)\b",
    "Research Scientist": r"research scientist|(?<!applied )(?<!data )\bscientist\b|\bresearcher\b",
    "Data Science": r"data scien|quantitative research",
}
FAMILY_RE = {k: re.compile(v, re.I) for k, v in FAMILIES.items()}
# Defaults; config.yaml → candidate.role_weights overrides. Tuned for an MS in computer vision.
DEFAULT_ROLE_WEIGHTS = {"Computer Vision": 30, "ML Engineer": 24, "GenAI / LLM": 22, "Research Engineer": 22,
                        "Forward Deployed": 20, "Research Scientist": 6, "Data Science": 4}

# titles that are never wanted (seniority, non-eng functions, internships)
EXCLUDE_TITLE = re.compile(
    r"\b(?:senior|sr\.?|(?<!technical )staff|principal|lead|leader|manager|director|head of|vp|vice president|chief|"
    r"distinguished|architect|intern|internship|co-?op|apprentice|"
    r"recruit\w*|sales|marketing|account (executive|manager)|counsel|attorney|accountant|"
    r"analyst|designer|writer|editor|technician|operator|specialist|coordinator|economist|summer|"
    r"manufacturing|mechanical|electrical|civil|firmware|hardware|asic|fpga|frontend|front-end|ios|android|"
    r"iii|iv|v|level [5-9]|l[5-9]|e[5-9]|ic[4-9])(?!\w)",
    re.I,
)
# generic SWE titles allowed in only if they mention ML-ish words (handled via FAMILIES)

# ───────────────────────────── level ─────────────────────────────
NEW_GRAD = re.compile(r"new (college )?grad|\bncg\b|university grad|recent grad|graduate\b|early[- ]career|"
                      r"20(26|27) start|campus|class of 20(26|27)|residen(t|cy)|fellow", re.I)
ENTRY = re.compile(r"\b(entry|junior|jr\.?|associate|engineer i|scientist i|level 1|l3|e3|ic1|ic2|"
                   r"engineer 1|scientist 1)\b|\bi$", re.I)
MID = re.compile(r"\b(ii|2|mid|l4|e4|ic3|intermediate|level [34])\b", re.I)

YOE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)(?:\s+of)?[^.\n]{0,60}?"
    r"(?:experience|industry|professional|working|building|engineering|software|research)",
    re.I,
)
PHD = re.compile(r"\bph\.?d\b", re.I)
CITIZEN = re.compile(r"u\.?s\.? citizen|united states citizen|security clearance|\bclearance\b|ts/sci|"
                     r"secret clearance|us person|u\.s\. person|itar|green card holder", re.I)
NO_SPONSOR = re.compile(r"(not|unable to|cannot|won't|will not)\s+(provide |offer )?(visa )?sponsor", re.I)


def min_years(desc: str) -> int | None:
    if not desc:
        return None
    vals = [int(m.group(1)) for m in YOE.finditer(desc[:12000]) if 0 <= int(m.group(1)) <= 20]
    return min(vals) if vals else None


def level_of(title: str, hints: dict, yoe: int | None) -> str:
    if NEW_GRAD.search(title) or hints.get("level") == "new_grad":
        return "new_grad"
    if ENTRY.search(title):
        return "entry"
    if MID.search(title):
        return "mid"
    if yoe is not None:
        return "entry" if yoe <= 1 else "mid" if yoe <= 4 else "senior"
    return "unspecified"


# ───────────────────────────── location ─────────────────────────────
STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
          "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
US_RE = re.compile(
    r"united states|\bU\.?S\.?A?\b|america|\bremote\b(?!.{0,25}\b(canada|uk|united kingdom|europe|emea|india|apac|"
    r"germany|france|ireland|poland|mexico|brazil|japan|singapore|australia|latam)\b)|"
    r"san francisco|bay area|silicon valley|palo alto|mountain view|menlo park|sunnyvale|san jose|santa clara|"
    r"cupertino|redwood city|san mateo|oakland|berkeley|los angeles|san diego|irvine|seattle|bellevue|redmond|"
    r"kirkland|new york|nyc|brooklyn|boston|cambridge, ma|austin|dallas|houston|denver|boulder|chicago|"
    r"pittsburgh|atlanta|miami|washington|arlington|philadelphia|raleigh|durham|salt lake|portland|phoenix|"
    r"ann arbor|detroit|minneapolis|columbus|nashville|princeton|"
    r",\s*(" + "|".join(STATES) + r")\b",
    re.I,
)
NON_US = re.compile(r"\b(canada|toronto|vancouver|montreal|ontario|london|uk\b|united kingdom|dublin|ireland|paris|"
                    r"france|berlin|munich|germany|zurich|switzerland|amsterdam|tel aviv|israel|india|bangalore|"
                    r"bengaluru|mumbai|hyderabad|singapore|tokyo|japan|seoul|korea|sydney|australia|warsaw|poland|"
                    r"mexico|brazil|sao paulo|beijing|shanghai|china|taipei)\b", re.I)


def is_us(locs: list[str]) -> bool:
    if not locs or all(not l.strip() for l in locs):
        return True  # unknown → keep, user can judge
    for l in locs:
        if US_RE.search(l):
            # "Cambridge, UK" / "Washington" ambiguity: if the same string is clearly non-US and has no US marker
            if NON_US.search(l) and not re.search(r"united states|\bUSA?\b|,\s*(" + "|".join(STATES) + r")\b", l):
                continue
            return True
    return False


# ───────────────────────────── scoring ─────────────────────────────
TIER_POINTS = {"frontier_lab": 30, "big_tech": 30, "top_startup": 22, "yc": 18, "other": 10}
LEVEL_POINTS = {"new_grad": 20, "entry": 18, "unspecified": 10, "mid": 8}
P1_MIN, P2_MIN = 78, 62


def freshness_points(posted_at, now=None):
    """Applying in the first hours matters most, so very fresh roles get a big boost."""
    if not posted_at:
        return 6
    h = ((now or time.time()) - posted_at) / 3600
    return (20 if h <= 6 else 15 if h <= 24 else 10 if h <= 72 else 6 if h <= 168 else 3 if h <= 336
            else 0 if h <= 1080 else -8)


def norm_company(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|technologies|labs?|ai|industries)\b\.?", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


SAME_CO_SUFFIX = {"", "inc", "platforms", "webservices", "research", "usds", "usa", "us", "global"}


def same_company(company: str, name: str) -> bool:
    """'Snap Inc' == 'Snap', 'Amazon Web Services' == 'Amazon', but 'Snap Finance' != 'Snap'."""
    nc, nn = norm_company(company), norm_company(name)
    return bool(nn) and nc.startswith(nn) and nc[len(nn):] in SAME_CO_SUFFIX


def tier_of(company: str, tiers: dict, yc: set) -> str:
    for t in ("frontier_lab", "big_tech", "top_startup"):
        if any(same_company(company, name) for name in tiers.get(t, [])):
            return t
    if company.strip().lower() in yc:
        return "yc"
    return "other"


PHD_ONLY_TITLE = re.compile(r"\bph\.?d\b", re.I)
NON_PHD_DEGREE = re.compile(r"\b(ms|m\.s\.|master'?s?|bs|b\.s\.|bachelor'?s?)\b", re.I)


def match_evidence(title: str, desc: str, evidence: list[dict]) -> list[tuple[str, int]]:
    """Which of her proof points this job asks for. Returns [(evidence_id, strength)] strongest first.
    A keyword in the title counts 3, in the description 1 (each keyword counted once)."""
    t, d = title.lower(), desc.lower()
    out = []
    for ev in evidence:
        s = 0
        for k in ev.get("keywords", []):
            pat = r"(?<![a-z0-9])" + re.escape(k.lower()) + (r"(?![a-z0-9])" if len(k) <= 3 else "")
            if re.search(pat, t):
                s += 3
            elif d and re.search(pat, d):
                s += 1
        if s:
            out.append((ev["id"], s))
    return sorted(out, key=lambda x: -x[1])


def fit_points(matches: list[tuple[str, int]]) -> int:
    """Up to 14: rewards matching several distinct proof points, not keyword spam."""
    strong = [m for m in matches if m[1] >= 3]
    return min(14, 4 * len(strong) + (2 if len(matches) > len(strong) else 0))


def classify(job: dict, cfg: dict, yc: set, now=None) -> dict | None:
    """Return enriched job dict or None if it should be dropped."""
    cand = cfg["candidate"]
    weights = {**DEFAULT_ROLE_WEIGHTS, **(cand.get("role_weights") or {})}
    level_pts = {**LEVEL_POINTS, **(cand.get("level_points") or {})}
    title = re.sub(r"\s+", " ", job["title"]).strip()
    if not title or EXCLUDE_TITLE.search(title):
        return None
    fams = [f for f, r in FAMILY_RE.items() if r.search(title)]
    if not fams:
        return None
    if fams == ["Data Science"] and not cand.get("include_data_science", True):
        return None
    if fams == ["Computer Vision"] and not re.search(r"engineer|scientist|research", title, re.I):
        return None  # e.g. "Video Producer"
    if "Forward Deployed" not in fams and not re.search(
            r"engineer|scientist|research|developer|resident|fellow|\bmts\b|technical staff|mle", title, re.I):
        return None
    if cand.get("us_only", True) and not is_us(job["locations"]):
        return None

    hints = job.get("hints") or {}
    desc = job.get("description") or ""
    # PhD-only roles: titles like "... - PhD" (without MS/BS) or curated-list degree = PhD only
    phd_only = (PHD_ONLY_TITLE.search(title) and not NON_PHD_DEGREE.search(title)) or hints.get("degrees") == ["PhD"]
    if phd_only and cand.get("drop_phd_only", True):
        return None

    yoe = min_years(desc)
    level = level_of(title, hints, yoe)
    if level == "senior" or (yoe is not None and yoe > cand.get("max_years_experience", 4)):
        return None
    if level not in cand.get("include_levels", level_pts):
        return None

    flags = []
    hint_sp = hints.get("sponsorship", "")
    citizen = bool(CITIZEN.search(desc) or CITIZEN.search(title)) or "Citizenship" in hint_sp
    no_sponsor = bool(NO_SPONSOR.search(desc)) or hint_sp == "Does Not Offer Sponsorship"
    if citizen:
        flags.append("US citizen/clearance")
    if no_sponsor:
        flags.append("No sponsorship")
    if (citizen or no_sponsor) and (cand.get("hide_citizenship_required") or cand.get("needs_sponsorship")):
        return None
    phd_required = bool(phd_only or re.search(r"ph\.?d\.? (is |degree is )?required|must have a ph\.?d", desc, re.I))
    if phd_required:
        flags.append("PhD")

    tier = tier_of(job["company"], cfg.get("tiers", {}), yc)
    score = TIER_POINTS[tier]
    matches = match_evidence(title, desc, cand.get("evidence") or [])
    fit = fit_points(matches)
    rs_only = "Research Scientist" in fams and "Research Engineer" not in fams
    topical = any(f in fams for f in ("Computer Vision", "GenAI / LLM")) or fit >= 8
    if rs_only:  # low priority by request
        role_pts = weights["Research Scientist"] + (cand.get("research_scientist_fit_bonus", 10) if topical else 0)
    else:
        role_pts = max(weights[f] for f in fams) + (3 if len(fams) > 1 else 0)
    score += role_pts + fit
    off = cand.get("off_domain_title") or []
    if off and fit < 8 and re.search(r"(?<![a-z])(" + "|".join(map(re.escape, off)) + r")", title.lower()):
        score -= cand.get("off_domain_penalty", 12)   # ML role, but not her field (security, recsys, chip design…)
    score += level_pts[level]
    score += freshness_points(job.get("posted_at"), now)
    if citizen or no_sponsor:
        score -= 20 if cand.get("needs_sponsorship") else 5
    if phd_required and cand.get("degree", "masters") != "phd":
        score -= 10
    score = max(0, min(100, score))
    priority = "P1" if score >= P1_MIN else "P2" if score >= P2_MIN else "P3"
    if rs_only:  # research-scientist roles never trigger instant alerts: topical ones cap at P2, others at P3
        priority = max(priority, "P2" if topical else "P3")

    return dict(job, title=title, families=fams, level=level, yoe_min=yoe, flags=flags, tier=tier,
                score=score, priority=priority, fit=[m[0] for m in matches[:4]])
