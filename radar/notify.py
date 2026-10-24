"""Email digest (Gmail SMTP or any SMTP) + optional Discord / Telegram pings."""
from __future__ import annotations

import html
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

PCOLOR = {"P1": "#c2410c", "P2": "#2563eb", "P3": "#64748b"}
LEVEL_LABEL = {"new_grad": "New grad", "entry": "Entry", "mid": "Mid", "unspecified": "Level n/a"}


def _age(ts):
    if not ts:
        return "?"
    d = (time.time() - ts) / 86400
    return f"{int(d * 24)}h" if d < 1 else f"{int(d)}d"


def fit_html(j: dict, evidence: dict) -> str:
    labels = [evidence[i] for i in j.get("fit", []) if i in evidence]
    if not labels:
        return ""
    return ('<div style="color:#374151;font-size:12px;margin-top:2px"><b>Why she fits:</b> '
            + html.escape(" · ".join(labels)) + "</div>")


def render_email(jobs: list[dict], total_active: int, dashboard_url: str, max_jobs: int,
                 kind: str = "digest", evidence: dict | None = None) -> tuple[str, str]:
    evidence = evidence or {}
    p1 = sum(j["priority"] == "P1" for j in jobs)
    if kind == "alert":
        top = jobs[0]
        subject = f"Apply now: {top['company']} — {top['title']}" + (f" (+{len(jobs) - 1} more P1)" if len(jobs) > 1 else "")
    elif kind == "welcome":
        subject = f"Job Radar is live: {len(jobs)} open ML roles to start with" + (f" ({p1} P1)" if p1 else "")
    else:
        subject = f"Job Radar: {len(jobs)} new ML roles" + (f" ({p1} P1)" if p1 else "")
    rows = []
    for j in jobs[:max_jobs]:
        meta = " · ".join(filter(None, [
            LEVEL_LABEL.get(j["level"], j["level"]),
            ", ".join(j["families"]),
            f"{j['yoe_min']}+ yrs" if j.get("yoe_min") is not None else "",
            j.get("salary", ""),
            f"posted {_age(j.get('posted_at'))} ago",
        ]))
        flags = "".join(f'<span style="background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 6px;'
                        f'margin-left:6px;font-size:11px">{html.escape(f)}</span>' for f in j.get("flags", []))
        rows.append(f"""
<tr><td style="padding:10px 0;border-bottom:1px solid #e5e7eb;vertical-align:top;width:44px">
  <span style="background:{PCOLOR[j['priority']]};color:#fff;border-radius:4px;padding:2px 6px;font:600 12px sans-serif">{j['priority']}</span></td>
<td style="padding:10px 0 10px 8px;border-bottom:1px solid #e5e7eb;font:14px/1.4 -apple-system,Segoe UI,sans-serif">
  <a href="{html.escape(j['url'])}" style="color:#111827;font-weight:600;text-decoration:none">{html.escape(j['title'])}</a>{flags}<br>
  <span style="color:#374151">{html.escape(j['company'])}</span> <span style="color:#6b7280">— {html.escape('; '.join(j['locations'][:2]))}</span><br>
  <span style="color:#6b7280;font-size:12px">{html.escape(meta)}</span>
  {fit_html(j, evidence)}
  <div style="margin-top:6px;font:600 12px sans-serif"><a href="{html.escape(j['url'])}" style="color:#2445d1">Apply</a>{(' &nbsp;·&nbsp; <a href="' + html.escape(dashboard_url.rstrip('/') + '/#job-' + j['id']) + '" style="color:#2445d1">Apply kit (email, LinkedIn note, referral ask)</a>') if dashboard_url else ''}</div></td></tr>""")
    more = len(jobs) - max_jobs
    footer = (f'<p style="font:13px sans-serif">+{more} more new roles. ' if more > 0 else '<p style="font:13px sans-serif">')
    if dashboard_url:
        footer += f'<a href="{html.escape(dashboard_url)}">Open the dashboard</a> to filter, sort and track applications. '
    footer += f"{total_active} active matching roles tracked overall.</p>"
    body = f"""<div style="max-width:680px;margin:auto">
<h2 style="font:600 18px sans-serif;margin:0 0 4px">{ {"alert": "Just posted. Apply within the next few hours, then send the cold email from the apply kit.", "welcome": f"{len(jobs)} open roles to start with"}.get(kind, f"{len(jobs)} new roles since the last digest") }</h2>
<p style="font:13px sans-serif;color:#6b7280;margin:0 0 12px">Sorted by priority score (company tier + role fit + level + freshness).</p>
<table style="border-collapse:collapse;width:100%">{''.join(rows)}</table>{footer}</div>"""
    return subject, body


def send_email(subject: str, body: str) -> str:
    user, pw, to = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("EMAIL_TO")
    if not (user and pw and to):
        return "email skipped (SMTP_USER / SMTP_PASS / EMAIL_TO not set)"
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(body, "html", "utf-8"))
    host, port = os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return f"email sent to {to}"


def send_chat(jobs: list[dict], dashboard_url: str, kind: str = "digest") -> list[str]:
    log = []
    top = jobs[:10]
    text = "\n".join(f"{j['priority']} · {j['company']} — {j['title']} ({LEVEL_LABEL.get(j['level'])})\n{j['url']}"
                     for j in top)
    head = ("🚨 Just posted — apply now" if kind == "alert" else f"🛰 {len(jobs)} new ML roles") + (f" — dashboard: {dashboard_url}" if dashboard_url else "")
    if hook := os.getenv("DISCORD_WEBHOOK"):
        try:
            requests.post(hook, json={"content": (head + "\n\n" + text)[:1990]}, timeout=20).raise_for_status()
            log.append("discord sent")
        except Exception as e:  # noqa: BLE001
            log.append(f"discord failed: {e}")
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": (head + "\n\n" + text)[:4000],
                                "disable_web_page_preview": True}, timeout=20).raise_for_status()
            log.append("telegram sent")
        except Exception as e:  # noqa: BLE001
            log.append(f"telegram failed: {e}")
    return log
