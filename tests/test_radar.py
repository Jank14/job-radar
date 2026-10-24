"""Offline tests: parsers use payload shapes captured from the live APIs (Oct 2026)."""
import time
from pathlib import Path

import yaml

from radar import classify as C, sources as S, store

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())
NOW = time.time()


class R:
    def __init__(self, data=None, text=""):
        self._d, self.text = data, text
    def json(self):
        return self._d
    def raise_for_status(self):
        pass


GH = {"jobs": [
    {"absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/5390811008",
     "location": {"name": "San Francisco, CA | New York City, NY"}, "id": 5390811008,
     "updated_at": "2026-09-04T11:26:23-04:00", "first_published": "2026-09-04T11:26:23-04:00",
     "title": "Applied AI, Research Engineer ", "content": "&lt;p&gt;You have 2+ years of experience building ML systems.&lt;/p&gt;"},
    {"absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/1", "location": {"name": "London, UK"},
     "first_published": "2026-10-01T00:00:00Z", "title": "Research Engineer, Interpretability", "content": ""},
    {"absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/2", "location": {"name": "San Francisco, CA"},
     "first_published": "2026-10-01T00:00:00Z", "title": "Account Executive, Startups", "content": ""},
    {"absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/3", "location": {"name": "Remote-Friendly, United States"},
     "first_published": "2026-10-01T00:00:00Z", "title": "Machine Learning Engineer, Safeguards",
     "content": "Requires 6+ years of industry experience"},
]}
ASHBY = {"jobs": [
    {"id": "240d", "title": "Research Engineer", "employmentType": "FullTime", "location": "San Francisco",
     "secondaryLocations": [], "publishedAt": "2025-04-05T00:03:20.653+00:00", "isListed": True,
     "address": {"postalAddress": {"addressCountry": "United States"}},
     "jobUrl": "https://jobs.ashbyhq.com/openai/240d", "descriptionPlain": "Have strong programming skills",
     "compensation": {"scrapeableCompensationSalarySummary": "$250K - $445K"}},
    {"id": "x", "title": "Forward Deployed Engineer", "employmentType": "FullTime", "location": "New York City",
     "secondaryLocations": [{"location": "Seattle"}], "publishedAt": "2026-10-20T00:00:00Z", "isListed": True,
     "jobUrl": "https://jobs.ashbyhq.com/openai/x", "descriptionPlain": "Must be a U.S. citizen. 1+ years experience."},
    {"id": "i", "title": "Research Engineer Intern", "employmentType": "Intern", "location": "SF", "isListed": True,
     "jobUrl": "u", "descriptionPlain": ""},
]}
LEVER = [{"text": "Perception Engineer, New Grad", "hostedUrl": "https://jobs.lever.co/zoox/abc",
          "categories": {"location": "Foster City, CA", "allLocations": ["Foster City, CA"], "commitment": "Full-time"},
          "createdAt": int(NOW * 1000) - 3600_000, "descriptionPlain": "Computer vision.", "lists": [],
          "salaryRange": {"min": 150000, "max": 200000}}]


def test_greenhouse(monkeypatch):
    monkeypatch.setattr(S, "_get", lambda url, **k: R(GH))
    jobs = S.fetch_greenhouse("anthropic", "Anthropic")
    assert jobs[0]["locations"] == ["San Francisco, CA", "New York City, NY"]
    assert "2+ years" in jobs[0]["description"]
    got = [C.classify(j, CFG, set(), NOW) for j in jobs]
    assert got[0]["tier"] == "frontier_lab" and got[0]["yoe_min"] == 2 and got[0]["level"] == "mid"
    assert got[1] is None   # London only
    assert got[2] is None   # sales
    assert got[3] is None   # 6+ yrs > max 4


def test_ashby(monkeypatch):
    monkeypatch.setattr(S, "_get", lambda url, **k: R(ASHBY))
    jobs = S.fetch_ashby("openai", "OpenAI")
    assert len(jobs) == 2  # intern dropped
    a, b = (C.classify(j, CFG, set(), NOW) for j in jobs)
    assert a["level"] == "unspecified" and a["salary"] == "$250K - $445K" and "San Francisco, United States" in a["locations"]
    assert b is None  # "Must be a U.S. citizen" → dropped, she needs sponsorship


def test_lever(monkeypatch):
    monkeypatch.setattr(S, "_get", lambda url, **k: R(LEVER))
    j = C.classify(S.fetch_lever("zoox", "Zoox")[0], CFG, set(), NOW)
    assert j["level"] == "new_grad" and "Computer Vision" in j["families"] and j["salary"] == "$150k–$200k"
    assert j["priority"] == "P1"


def test_auto_resolve(monkeypatch):
    calls = []
    def fake(url, **k):
        calls.append(url)
        if "greenhouse" in url:
            raise RuntimeError("404")
        return R(ASHBY) if "ashby" in url else R(LEVER)
    monkeypatch.setattr(S, "_get", fake)
    cache = {}
    res = S.fetch_company({"name": "Foo", "slug": "foo", "ats": "auto"}, cache)
    assert res.ok and cache == {"Foo": "ashby"} and res.tag == "ashby:foo"


def test_speedyapply():
    md = ('### FAANG+\n| Company | Position | Location | Salary | Posting | Age |\n|---|---|---|---|---|---|\n'
          '| <a href="https://www.tiktok.com"><strong>TikTok</strong></a> | Research Scientist Graduate - 2027 Start | Seattle, WA | $202k/yr | '
          '<a href="https://lifeattiktok.com/search/1"><img src="x" alt="Apply" width="70"/></a> | 9d |\n'
          '### Other\n| <a href="https://x.com"><strong>Acme</strong></a> | ML Engineer | Remote | '
          '<a href="https://acme/apply"><img/></a> | 2d |\n')
    jobs = S.parse_speedyapply(md, NOW)
    assert jobs[0]["url"] == "https://lifeattiktok.com/search/1" and jobs[0]["salary"] == "$202k/yr"
    assert abs(jobs[0]["posted_at"] - (NOW - 9 * 86400)) < 2 and jobs[1]["url"] == "https://acme/apply"


def test_titles():
    keep = ["Machine Learning Engineer", "Research Engineer, Pretraining", "Software Engineer, ML Infrastructure",
            "Computer Vision Engineer I", "Forward Deployed Engineer", "AI Engineer - New Grad",
            "Applied Scientist", "Member of Technical Staff", "Perception Engineer", "LLM Inference Engineer"]
    drop = ["Senior Machine Learning Engineer", "Staff Research Scientist", "ML Engineering Manager",
            "Machine Learning Intern", "Data Analyst", "Applied AI Architect", "Software Engineer, Frontend",
            "Research Scientist - Economist", "Video Producer", "Account Executive, AI Native", "ML Engineer III"]
    mk = lambda t: dict(company="X", title=t, url="u", locations=["New York, NY"], posted_at=NOW, description="",
                        salary="", source="t", hints={})
    assert all(C.classify(mk(t), CFG, set(), NOW) for t in keep), [t for t in keep if not C.classify(mk(t), CFG, set(), NOW)]
    assert not any(C.classify(mk(t), CFG, set(), NOW) for t in drop), [t for t in drop if C.classify(mk(t), CFG, set(), NOW)]


def test_us():
    assert C.is_us(["Remote-Friendly, United States"]) and C.is_us(["Pittsburgh, PA"])
    assert not C.is_us(["Toronto, ON, Canada"]) and not C.is_us(["Remote - Canada"]) and not C.is_us(["Bengaluru, India"])
    assert C.is_us(["London, UK", "New York, NY"]) and C.is_us(["Remote"])


def test_dedupe_and_state(tmp_path):
    base = dict(company="Acme AI", title="ML Engineer", locations=["NYC"], posted_at=NOW, salary="", flags=[],
                families=["ML Engineer"], level="new_grad", yoe_min=None, tier="other", score=60, priority="P2")
    a = dict(base, url="https://jobs.ashbyhq.com/acme/1", source="ashby:acme")
    b = dict(base, company="Acme", url="https://simplify/x", source="simplify", score=55, priority="P2")
    d = store.dedupe([b, a])
    assert len(d) == 1 and d[0]["url"].startswith("https://jobs.ashbyhq") and set(d[0]["sources"]) == {"ashby:acme", "simplify"}
    p = tmp_path / "jobs.json"
    jobs, new = store.merge_state(p, d, {"ashby:acme", "simplify"}, NOW)
    store.save(p, jobs, {})
    assert len(new) == 1
    jobs, new = store.merge_state(p, [], {"simplify"}, NOW + 100)       # ashby failed → stays active
    assert jobs[0]["active"] and not new
    jobs, new = store.merge_state(p, [], {"simplify", "ashby:acme"}, NOW + 200)  # both ok, gone → closed
    assert jobs[0]["active"] is False


def _mk(title, **kw):
    return dict(dict(company="Meta", title=title, url="u", locations=["Menlo Park, CA"], posted_at=NOW - 3600,
                     description="", salary="", source="simplify", hints={"level": "new_grad"}), **kw)


def test_cv_beats_research_scientist():
    cv = C.classify(_mk("Computer Vision Engineer, New Grad"), CFG, set(), NOW)
    rs = C.classify(_mk("Research Scientist, New Grad"), CFG, set(), NOW)
    rs_cv = C.classify(_mk("Research Scientist, Computer Vision - New Grad"), CFG, set(), NOW)
    assert cv["score"] > rs_cv["score"] > rs["score"] and cv["priority"] == "P1"
    assert rs_cv["priority"] == "P2" and rs["priority"] == "P3"


def test_phd_only_dropped():
    assert C.classify(_mk("Research Engineer Graduate - 2027 Start - PhD"), CFG, set(), NOW) is None
    assert C.classify(_mk("Research Engineer Graduate - 2027 Start (BS/MS/PhD)"), CFG, set(), NOW)
    assert C.classify(_mk("ML Engineer", hints={"level": "new_grad", "degrees": ["PhD"]}), CFG, set(), NOW) is None


def test_fresh_boost():
    new = C.classify(_mk("Machine Learning Engineer"), CFG, set(), NOW)
    old = C.classify(_mk("Machine Learning Engineer", posted_at=NOW - 20 * 86400), CFG, set(), NOW)
    assert new["score"] - old["score"] == 20


def test_dispatch_ist(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from radar import main, notify
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda s, b: sent.append(s) or "ok")
    monkeypatch.setattr(notify, "send_chat", lambda js, d, k="digest": [])
    ist = ZoneInfo("Asia/Kolkata")
    t = lambda h, m=20: datetime(2026, 10, 23, h, m, tzinfo=ist).timestamp()
    ncfg = CFG["notify"]
    job = lambda i, p: dict(id=i, company="A", title="ML Eng", url="u", locations=[], families=["ML Engineer"],
                            level="new_grad", flags=[], priority=p, score={"P1": 90, "P2": 60, "P3": 40}[p], active=True)
    st = {}
    jobs = [job("a", "P2")]
    main.dispatch(ncfg, jobs, st, t(7), True, False)          # first run → welcome mail at any hour
    assert len(sent) == 1 and "live" in sent[0]
    jobs += [job("b", "P1"), job("c", "P2")]
    main.dispatch(ncfg, jobs, st, t(8, 10), False, False)      # 08:10 IST: P1 alert only, no digest yet
    assert len(sent) == 2 and sent[1].startswith("Apply now")
    main.dispatch(ncfg, jobs, st, t(9, 25), False, False)      # 09:25 IST digest → only "c"
    assert len(sent) == 3 and "1 new" in sent[2]
    main.dispatch(ncfg, jobs, st, t(10), False, False)         # nothing due
    assert len(sent) == 3
    jobs.append(job("d", "P1"))
    main.dispatch(ncfg, jobs, st, t(2) + 86400, False, False)  # 02:20 IST next day: outside alert window → waits…
    assert len(sent) == 4 and "digest" not in sent[3].lower()   # …but the missed 22:00 slot catches up as a digest


def test_workday(monkeypatch):
    listing = {"total": 2, "jobPostings": [
        {"title": "Machine Learning Engineer, Generative ML, Level 4", "externalPath": "/job/Palo-Alto/MLE-GenML_R1",
         "locationsText": "Palo Alto, California", "postedOn": "Posted 3 Days Ago"},
        {"title": "Account Executive", "externalPath": "/job/NY/AE_R2", "locationsText": "New York", "postedOn": "Posted Today"}]}
    detail = {"jobPostingInfo": {"jobDescription": "<p>2+ years of experience with diffusion models and LoRA fine-tuning.</p>",
                                 "startDate": "2026-10-20", "location": "Palo Alto, California"}}
    import requests as rq
    monkeypatch.setattr(rq, "post", lambda *a, **k: R(listing))
    monkeypatch.setattr(S, "_get", lambda url, **k: R(detail))
    t = {"name": "Snap", "host": "wd1.myworkdaysite.com", "tenant": "snapchat", "site": "snap",
         "url_prefix": "https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap"}
    res = S.fetch_workday(t, ["machine learning"], lambda title: "Machine" in title)
    assert res.ok and len(res.jobs) == 2
    j = res.jobs[0]
    assert j["url"] == "https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/Palo-Alto/MLE-GenML_R1"
    assert "diffusion" in j["description"] and j["posted_at"] == S._iso("2026-10-20T12:00:00+00:00")
    c = C.classify(dict(j, posted_at=NOW), CFG, set(), NOW)
    assert c["level"] == "mid" and c["tier"] == "big_tech" and "sync" in c["fit"] and "reward" in c["fit"]


def test_amazon(monkeypatch):
    data = {"jobs": [{"id_icims": "1", "title": "Applied Scientist, Computer Vision", "job_path": "/en/jobs/1/x",
                      "normalized_location": "Seattle, Washington, USA", "posted_date": "October 20, 2026",
                      "description": "3D reconstruction and object detection", "basic_qualifications": "MS degree",
                      "preferred_qualifications": ""}]}
    monkeypatch.setattr(S, "_get", lambda url, **k: R(data))
    j = S.fetch_amazon(["computer vision"]).jobs[0]
    assert j["url"] == "https://www.amazon.jobs/en/jobs/1/x" and j["posted_at"]
    c = C.classify(j, CFG, set(), NOW)
    assert "Computer Vision" in c["families"] and set(c["fit"]) >= {"slot4d", "eccv"}


def test_evidence_no_false_av():
    from radar.classify import match_evidence
    ev = CFG["candidate"]["evidence"]
    assert "cvit" not in [m[0] for m in match_evidence("Software Engineer", "Available now, average pay", ev)]


def test_company_identity_and_off_domain():
    assert C.same_company("Snap Inc.", "Snap") and C.same_company("Amazon Web Services", "Amazon")
    assert not C.same_company("Snap Finance", "Snap")
    gen = C.classify(_mk("Machine Learning Engineer, Generative Video"), CFG, set(), NOW)
    sec = C.classify(_mk("Machine Learning Engineer, Security"), CFG, set(), NOW)
    assert gen["score"] - sec["score"] >= 12
