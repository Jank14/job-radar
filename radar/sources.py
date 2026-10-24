"""Job sources. Every fetcher returns a list of RawJob dicts with a common schema:

    company, title, url, locations[list[str]], posted_at (epoch seconds or None),
    description (plain text, may be ""), salary (str or ""), source (str),
    hints (dict: level / sponsorship / degrees from curated lists)

Fetchers never raise: failures are recorded in the returned SourceResult so one
broken board can't take down the whole run.
"""
from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "job-radar/1.0 (personal job alert; contact via repo)"}
TIMEOUT = 30


@dataclass
class SourceResult:
    name: str
    tag: str = ""          # matches job["source"] for jobs from this result
    ok: bool = True
    jobs: list = field(default_factory=list)
    error: str = ""


def _get(url, **kw):
    r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _iso(ts: str | None):
    if not ts:
        return None
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


# ───────────────────────────── ATS boards ─────────────────────────────

def fetch_greenhouse(slug: str, company: str):
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}).json()
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        locs = [l.strip() for l in re.split(r"[;|]", loc) if l.strip()] or [loc]
        out.append(dict(
            company=company, title=j.get("title", "").strip(), url=j.get("absolute_url", ""),
            locations=locs, posted_at=_iso(j.get("first_published") or j.get("updated_at")),
            description=strip_html(j.get("content", "")), salary="", source=f"greenhouse:{slug}", hints={},
        ))
    return out


def fetch_lever(slug: str, company: str):
    data = _get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}).json()
    if not isinstance(data, list):
        raise ValueError("lever: unexpected payload")
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location") or ""]
        desc = j.get("descriptionPlain") or ""
        for block in j.get("lists") or []:
            desc += "\n" + block.get("text", "") + "\n" + strip_html(block.get("content", ""))
        sal = j.get("salaryRange") or {}
        salary = f"${sal['min']//1000}k–${sal['max']//1000}k" if sal.get("min") and sal.get("max") else ""
        if cat.get("commitment") and re.search(r"intern", cat["commitment"], re.I):
            continue
        out.append(dict(
            company=company, title=j.get("text", "").strip(), url=j.get("hostedUrl", ""),
            locations=[l for l in locs if l], posted_at=(j.get("createdAt") or 0) // 1000 or None,
            description=desc, salary=salary, source=f"lever:{slug}", hints={},
        ))
    return out


def fetch_ashby(slug: str, company: str):
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}).json()
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        if j.get("employmentType") in ("Intern", "Internship"):
            continue
        locs = [j.get("location") or ""]
        for s in j.get("secondaryLocations") or []:
            locs.append(s.get("location", ""))
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        if country and country not in " ".join(locs):
            locs[0] = f"{locs[0]}, {country}".strip(", ")
        if j.get("isRemote"):
            locs.append("Remote")
        comp = (j.get("compensation") or {}).get("scrapeableCompensationSalarySummary") or ""
        out.append(dict(
            company=company, title=j.get("title", "").strip(), url=j.get("jobUrl", ""),
            locations=[l for l in locs if l], posted_at=_iso(j.get("publishedAt")),
            description=j.get("descriptionPlain") or "", salary=comp, source=f"ashby:{slug}", hints={},
        ))
    return out


ATS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def fetch_company(c: dict, ats_cache: dict) -> SourceResult:
    name, slug, ats = c["name"], c["slug"], c.get("ats", "auto")
    res = SourceResult(name=f"{name} ({ats}:{slug})")
    order = [ats] if ats != "auto" else ([ats_cache[name]] if name in ats_cache else ["greenhouse", "ashby", "lever"])
    last_err = ""
    for a in order:
        try:
            jobs = ATS[a](slug, name)
            if ats == "auto" and not jobs and name not in ats_cache:
                last_err = f"{a}: empty"
                continue
            res.jobs = jobs
            res.name, res.tag = f"{name} ({a}:{slug})", f"{a}:{slug}"
            if ats == "auto":
                ats_cache[name] = a
            return res
        except Exception as e:  # noqa: BLE001
            last_err = f"{a}: {type(e).__name__}: {str(e)[:120]}"
    res.ok, res.error = False, last_err or "not found"
    return res


# ───────────────────────────── curated lists ─────────────────────────────

SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"


def fetch_simplify() -> SourceResult:
    res = SourceResult(name="SimplifyJobs/New-Grad-Positions", tag="simplify")
    try:
        data = _get(SIMPLIFY_URL).json()
    except Exception as e:  # noqa: BLE001
        res.ok, res.error = False, str(e)[:200]
        return res
    for j in data:
        if not j.get("active") or not j.get("is_visible", True):
            continue
        if j.get("category") not in ("AI/ML/Data", "Data Science, AI & Machine Learning", "Software", "Software Engineering"):
            continue
        res.jobs.append(dict(
            company=j.get("company_name", ""), title=j.get("title", ""), url=j.get("url", ""),
            locations=j.get("locations") or [], posted_at=j.get("date_posted"), description="", salary="",
            source="simplify", hints={"level": "new_grad", "sponsorship": j.get("sponsorship", ""),
                                      "degrees": j.get("degrees") or []},
        ))
    return res


SPEEDY_URLS = [
    "https://raw.githubusercontent.com/speedyapply/2027-AI-College-Jobs/main/NEW_GRAD_USA.md",
]
_AGE = re.compile(r"^(\d+)\s*(h|d|w|mo|y)")


def parse_speedyapply(md: str, now: float | None = None):
    now = now or time.time()
    jobs, section = [], ""
    for line in md.splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
        if not line.startswith("| <a"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        m = re.search(r"<strong>(.*?)</strong>", cells[0])
        company = html.unescape(m.group(1)) if m else strip_html(cells[0])
        hrefs = re.findall(r'href="([^"]+)"', cells[-2])
        age = _AGE.match(cells[-1])
        posted = None
        if age:
            n, u = int(age.group(1)), age.group(2)
            posted = int(now - n * {"h": 3600, "d": 86400, "w": 604800, "mo": 2592000, "y": 31536000}[u])
        salary = cells[3] if len(cells) == 6 and "$" in cells[3] else ""
        jobs.append(dict(
            company=company, title=html.unescape(strip_html(cells[1])), url=hrefs[0] if hrefs else "",
            locations=[strip_html(cells[2])], posted_at=posted, description="", salary=salary,
            source="speedyapply", hints={"level": "new_grad", "section": section},
        ))
    return jobs


def fetch_speedyapply() -> SourceResult:
    res = SourceResult(name="speedyapply/2027-AI-College-Jobs", tag="speedyapply")
    try:
        for u in SPEEDY_URLS:
            res.jobs += parse_speedyapply(_get(u).text)
    except Exception as e:  # noqa: BLE001
        res.ok, res.error = False, str(e)[:200]
    return res


# ───────────────────────────── HN Who's Hiring ─────────────────────────────

def fetch_hn() -> SourceResult:
    """Top-level comments in the latest 'Ask HN: Who is hiring?' thread.
    Convention: first line is 'Company | Role | Location | ...'."""
    res = SourceResult(name="HN Who is hiring", tag="hn")
    try:
        s = _get("https://hn.algolia.com/api/v1/search_by_date",
                 params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 5}).json()
        story = next(h for h in s["hits"] if "who is hiring" in h["title"].lower())
        sid = story["objectID"]
        item = _get(f"https://hn.algolia.com/api/v1/items/{sid}").json()
    except Exception as e:  # noqa: BLE001
        res.ok, res.error = False, str(e)[:200]
        return res
    for c in item.get("children", []):
        text = strip_html(c.get("text") or "")
        if not text:
            continue
        first = text.split("\n", 1)[0][:300]
        parts = [p.strip() for p in first.split("|")]
        if len(parts) < 2:
            continue
        res.jobs.append(dict(
            company=parts[0][:60], title=" | ".join(parts[1:3])[:140],
            url=f"https://news.ycombinator.com/item?id={c['id']}", locations=[" ".join(parts[1:])[:200]],
            posted_at=c.get("created_at_i"), description=text[:4000], salary="", source="hn", hints={},
        ))
    return res


def fetch_yc_names() -> set[str]:
    try:
        data = _get("https://yc-oss.github.io/api/companies/all.json").json()
        return {d["name"].strip().lower() for d in data if d.get("name")}
    except Exception:  # noqa: BLE001
        return set()


# ───────────────────────────── Workday (Snap, NVIDIA, Adobe …) ─────────────────────────────
_WD_AGE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def _wd_posted(text: str, now: float):
    m = _WD_AGE.search(text or "")
    if not m:
        return None
    if m.group(1).lower() == "today":
        return int(now)
    if m.group(1).lower() == "yesterday":
        return int(now - 86400)
    return int(now - int(m.group(2)) * 86400)


def fetch_workday(t: dict, queries: list[str], title_filter, max_details: int = 40) -> SourceResult:
    """Public Workday 'cxs' JSON endpoints (what the career site itself calls)."""
    res = SourceResult(name=f"{t['name']} (workday)", tag=f"workday:{t['tenant']}")
    base = f"https://{t['host']}/wday/cxs/{t['tenant']}/{t['site']}"
    prefix = t.get("url_prefix") or f"https://{t['host']}/en-US/{t['site']}"
    now, seen, details = time.time(), set(), 0
    try:
        for q in queries:
            for offset in (0, 20, 40):
                r = requests.post(f"{base}/jobs", headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT,
                                  json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q})
                r.raise_for_status()
                posts = r.json().get("jobPostings") or []
                for p in posts:
                    path = p.get("externalPath") or ""
                    if not path or path in seen:
                        continue
                    seen.add(path)
                    title = p.get("title", "")
                    job = dict(company=t["name"], title=title, url=prefix + path,
                               locations=[p.get("locationsText") or ""], posted_at=_wd_posted(p.get("postedOn", ""), now),
                               description="", salary="", source=res.tag, hints={})
                    if title_filter(title) and details < max_details:   # description only for plausible matches
                        details += 1
                        try:
                            info = _get(base + path).json().get("jobPostingInfo") or {}
                            job["description"] = strip_html(info.get("jobDescription", ""))
                            if info.get("startDate"):
                                job["posted_at"] = _iso(info["startDate"] + "T12:00:00+00:00") or job["posted_at"]
                            if info.get("location"):
                                job["locations"] = [info["location"]] + (info.get("additionalLocations") or [])
                        except Exception:  # noqa: BLE001
                            pass
                    res.jobs.append(job)
                if len(posts) < 20:
                    break
    except Exception as e:  # noqa: BLE001
        res.ok, res.error = bool(res.jobs), f"{type(e).__name__}: {str(e)[:150]}"
    return res


# ───────────────────────────── Amazon ─────────────────────────────

def fetch_amazon(queries: list[str]) -> SourceResult:
    res = SourceResult(name="Amazon (amazon.jobs)", tag="amazon")
    seen = set()
    try:
        for q in queries:
            data = _get("https://www.amazon.jobs/en/search.json",
                        params={"base_query": q, "country": "USA", "result_limit": 100, "sort": "recent"}).json()
            for j in data.get("jobs", []):
                if j.get("id_icims") in seen:
                    continue
                seen.add(j.get("id_icims"))
                posted = None
                try:
                    posted = int(datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").replace(tzinfo=timezone.utc).timestamp())
                except ValueError:
                    pass
                desc = "\n".join(strip_html(j.get(k, "")) for k in ("description", "basic_qualifications", "preferred_qualifications"))
                res.jobs.append(dict(
                    company="Amazon", title=j.get("title", ""), url="https://www.amazon.jobs" + j.get("job_path", ""),
                    locations=[j.get("normalized_location") or j.get("location") or ""], posted_at=posted,
                    description=desc, salary="", source="amazon", hints={}))
    except Exception as e:  # noqa: BLE001
        res.ok, res.error = bool(res.jobs), f"{type(e).__name__}: {str(e)[:150]}"
    return res
