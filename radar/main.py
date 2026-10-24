"""Entry point:  python -m radar.main [--no-notify] [--only-lists]"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import notify, sources, store
from .classify import EXCLUDE_TITLE, FAMILY_RE, classify

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
PRIO = {"P1": 1, "P2": 2, "P3": 3}


def run(no_notify=False, only_lists=False):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    src_cfg = cfg.get("sources", {})
    cache_path = DATA / "ats_cache.json"
    ats_cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    results: list[sources.SourceResult] = []
    if src_cfg.get("company_boards", True) and not only_lists:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results += list(ex.map(lambda c: sources.fetch_company(c, ats_cache), cfg.get("companies", [])))
    title_ok = lambda t: any(r.search(t) for r in FAMILY_RE.values()) and not EXCLUDE_TITLE.search(t)
    if src_cfg.get("workday", True) and not only_lists:
        for t in cfg.get("workday", []):
            results.append(sources.fetch_workday(t, cfg.get("workday_queries", ["machine learning"]), title_ok))
    if src_cfg.get("amazon", True) and not only_lists:
        results.append(sources.fetch_amazon(cfg.get("amazon_queries", ["machine learning"])))
    if src_cfg.get("simplify_new_grad", True):
        results.append(sources.fetch_simplify())
    if src_cfg.get("speedyapply_ai", True):
        results.append(sources.fetch_speedyapply())
    if src_cfg.get("hn_whos_hiring", True) and not only_lists:
        results.append(sources.fetch_hn())
    yc = sources.fetch_yc_names() if src_cfg.get("yc_tags", True) and not only_lists else set()

    raw = [j for r in results for j in r.jobs]
    ok_sources = {r.tag for r in results if r.ok and r.tag}

    now = time.time()
    matched = [m for j in raw if (m := classify(j, cfg, yc, now))]
    deduped = store.dedupe(matched)
    all_jobs, new = store.merge_state(DATA / "jobs.json", deduped, ok_sources, now)

    failed = [f"{r.name}: {r.error}" for r in results if not r.ok]
    meta = {
        "run_at": int(now), "raw": len(raw), "matched": len(matched), "unique": len(deduped), "new": len(new),
        "sources_ok": sum(r.ok for r in results), "sources_failed": failed,
        "yc_companies": len(yc),
        "profile": (cfg.get("candidate") or {}).get("profile") or {},
        "evidence": [{k: e.get(k) for k in ("id", "label", "short", "text")} for e in (cfg.get("candidate") or {}).get("evidence", [])],
        "history": cfg.get("history") or [],
    }
    store.save(DATA / "jobs.json", all_jobs, meta)
    cache_path.write_text(json.dumps(ats_cache, indent=1, sort_keys=True))

    print(f"raw={len(raw)} matched={len(matched)} unique={len(deduped)} new={len(new)} "
          f"active={sum(j.get('active', True) for j in all_jobs)}")
    for f in failed:
        print("  ! source failed:", f)

    notify_state_path = DATA / "notify_state.json"
    first_run = not notify_state_path.exists()
    nstate = json.loads(notify_state_path.read_text()) if not first_run else {}
    evidence = {e["id"]: e.get("label", e["id"]) for e in (cfg.get("candidate") or {}).get("evidence", [])}
    log = dispatch(cfg.get("notify", {}), all_jobs, nstate, now, first_run, no_notify, evidence)
    for line in log:
        print(line)
    # bookkeeping flags were set on all_jobs in place → save again
    store.save(DATA / "jobs.json", all_jobs, meta)
    if not no_notify:
        notify_state_path.write_text(json.dumps(nstate))
    return meta


def latest_slot(now: float, tz: ZoneInfo, hours: list[int]) -> float:
    """Timestamp of the most recent digest hour (local time) at or before now."""
    local = datetime.fromtimestamp(now, tz)
    cands = []
    for back in (0, 1):
        d = (local - timedelta(days=back)).date()
        for h in hours:
            t = datetime(d.year, d.month, d.day, h % 24, tzinfo=tz).timestamp()
            if t <= now:
                cands.append(t)
    return max(cands) if cands else 0


def dispatch(ncfg: dict, jobs: list[dict], nstate: dict, now: float, first_run: bool, dry: bool,
             evidence: dict | None = None) -> list[str]:
    tz = ZoneInfo(ncfg.get("timezone", "Asia/Kolkata"))
    hour = datetime.fromtimestamp(now, tz).hour
    dash = ncfg.get("dashboard_url", "")
    cap = ncfg.get("max_jobs_in_email", 40)
    total = sum(j.get("active", True) for j in jobs)
    rank = lambda js: sorted(js, key=lambda j: (PRIO[j["priority"]], -j["score"]))
    pending = [j for j in jobs if j.get("active", True) and not j.get("digested")]
    log = []

    def send(js, kind):
        subj, body = notify.render_email(js, total, dash, cap, kind, evidence)
        if dry:
            log.append(f"[dry run] would send {kind}: {subj}")
            return
        try:
            log.append(notify.send_email(subj, body))
        except Exception as e:  # noqa: BLE001
            log.append(f"email failed: {e}")
        log.extend(notify.send_chat(js, dash, kind))

    # 1) instant alerts for top roles, inside the local-time window
    ip = ncfg.get("instant_priority") or ""
    lo, hi = (ncfg.get("instant_window") or [0, 24])[:2]
    if ip and not first_run and lo <= hour < hi:
        urgent = rank([j for j in pending if not j.get("alerted") and PRIO[j["priority"]] <= PRIO[ip]])
        if urgent:
            send(urgent, "alert")
            for j in urgent if not dry else []:
                j["alerted"] = j["digested"] = int(now)

    # 2) digest at the configured local hours (catches up if GitHub starts the job late)
    slot = latest_slot(now, tz, ncfg.get("digest_hours", [9, 13, 18, 22]))
    if first_run or slot > nstate.get("last_digest_slot", 0):
        thr = PRIO.get(ncfg.get("min_priority", "P2"), 2)
        batch = rank([j for j in jobs if j.get("active", True) and not j.get("digested") and PRIO[j["priority"]] <= thr])
        if batch or ncfg.get("send_when_empty"):
            send(batch, "welcome" if first_run else "digest")
        else:
            log.append("digest slot reached; nothing new above threshold")
        for j in jobs if not dry else []:
            if j.get("active", True) and not j.get("digested"):
                j["digested"] = int(now)   # P3s are marked too, so they don't pile up
        nstate["last_digest_slot"] = slot or now
    else:
        log.append(f"no digest due (local hour {hour}); {len(pending)} roles waiting")
    return log


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-notify", action="store_true", help="update data but send nothing")
    ap.add_argument("--only-lists", action="store_true", help="skip company boards (offline/quick test)")
    a = ap.parse_args()
    run(no_notify=a.no_notify, only_lists=a.only_lists)
