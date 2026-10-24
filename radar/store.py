"""Persistent state: merges each run into docs/data/jobs.json (served by GitHub Pages)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

KEEP_CLOSED_DAYS = 21


def norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"\(.*?\)|-\s*20\d\d start|20\d\d", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def norm_url(u: str) -> str:
    u = u.split("?")[0].split("#")[0].rstrip("/").lower()
    return re.sub(r"/(apply|application)$", "", u)


def job_key(company: str, title: str) -> str:
    from .classify import norm_company
    return hashlib.sha1(f"{norm_company(company)}|{norm_title(title)}".encode()).hexdigest()[:12]


SOURCE_RANK = {"greenhouse": 0, "lever": 0, "ashby": 0, "speedyapply": 1, "simplify": 2, "hn": 3}


def _rank(src: str) -> int:
    return SOURCE_RANK.get(src.split(":")[0], 5)


def dedupe(jobs: list[dict]) -> list[dict]:
    """Same role from several sources → keep the most direct one, union sources/locations, earliest posted date."""
    by_key: dict[str, dict] = {}
    url_to_key: dict[str, str] = {}
    for j in jobs:
        k = url_to_key.get(norm_url(j["url"])) or job_key(j["company"], j["title"])
        cur = by_key.get(k)
        if cur is None:
            by_key[k] = dict(j, id=k, sources=[j["source"]])
        else:
            better, other = (j, cur) if _rank(j["source"]) < _rank(cur["source"]) else (cur, j)
            merged = dict(better, id=k)
            merged["sources"] = sorted(set(cur["sources"]) | {j["source"]})
            merged["locations"] = list(dict.fromkeys((better["locations"] or []) + (other["locations"] or [])))[:6]
            ps = [p for p in (cur.get("posted_at"), j.get("posted_at")) if p]
            merged["posted_at"] = min(ps) if ps else None
            merged["salary"] = better.get("salary") or other.get("salary") or ""
            merged["flags"] = sorted(set(cur.get("flags", [])) | set(j.get("flags", [])))
            merged["score"] = max(cur["score"], j["score"])
            merged["priority"] = min(cur["priority"], j["priority"])
            by_key[k] = merged
        url_to_key[norm_url(j["url"])] = k
    return list(by_key.values())


def merge_state(path: Path, fresh: list[dict], ok_sources: set[str], now: float | None = None):
    """Returns (all_jobs, new_jobs). A job missing from this run is marked closed only if
    every source it came from was fetched successfully (avoids false 'closed' on outages)."""
    now = int(now or time.time())
    old = {}
    if path.exists():
        old = {j["id"]: j for j in json.loads(path.read_text()).get("jobs", [])}
    bootstrap = not old  # first ever run: date roles by when they were posted, not "now"
    out, new = {}, []
    for j in fresh:
        prev = old.get(j["id"])
        rec = {k: v for k, v in j.items() if k not in ("description", "hints", "source")}
        rec["first_seen"] = prev["first_seen"] if prev else (min(now, j.get("posted_at") or now) if bootstrap else now)
        rec["last_seen"] = now
        rec["active"] = True
        for k in ("digested", "alerted"):          # notification bookkeeping survives re-crawls
            if prev and prev.get(k):
                rec[k] = prev[k]
        out[j["id"]] = rec
        if not prev:
            new.append(rec)
    for k, prev in old.items():
        if k in out:
            continue
        srcs_ok = all(s in ok_sources for s in prev.get("sources", []))
        if srcs_ok:
            prev = dict(prev, active=False, closed_at=prev.get("closed_at") or now)
        if prev.get("active") or now - prev.get("closed_at", now) < KEEP_CLOSED_DAYS * 86400:
            out[k] = prev
    return list(out.values()), new


def save(path: Path, jobs: list[dict], meta: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs = sorted(jobs, key=lambda j: (not j.get("active", True), -j["score"], -(j.get("posted_at") or 0)))
    path.write_text(json.dumps({"generated_at": int(time.time()), "meta": meta, "jobs": jobs},
                               ensure_ascii=False, separators=(",", ":")))
