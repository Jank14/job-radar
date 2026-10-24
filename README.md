# Job Radar

A free, self-running job tracker for ML new grads. Three times a day it:

1. **Pulls** open roles directly from ~100 company career boards (Greenhouse / Lever / Ashby public APIs: Anthropic, OpenAI, xAI, Perplexity, Scale, Palantir, Waymo, Figure, Anysphere/Cursor, Harvey and more), plus the two biggest curated new-grad lists ([SimplifyJobs](https://github.com/SimplifyJobs/New-Grad-Positions) and [speedyapply AI](https://github.com/speedyapply/2027-AI-College-Jobs), which cover Google, Meta, Apple, Amazon, Microsoft, NVIDIA and TikTok through their Workday-style portals), and the monthly HN "Who is hiring?" thread.
2. **Filters** for Computer Vision, ML Engineer, GenAI/LLM, Research Engineer and Forward Deployed roles (Research Scientist kept at low priority; PhD-only roles dropped, since she's finishing an MS) at new grad, entry and mid level in the US. It reads each job description to estimate the minimum years of experience and drops anything asking for more than 4. Senior, staff, manager and intern roles are removed.
3. **Ranks** every role with a 0–100 priority score → P1 / P2 / P3:

   | Component | Points |
   |---|---|
   | Company tier: frontier lab / big tech / top AI startup / YC / other | 30 / 25 / 20 / 18 / 10 |
   | Role fit: computer vision 30, MLE 24, GenAI 22, research engineer 22, FDE 20, research scientist 6, data science 4 | up to 33 |
   | Skill match: her resume keywords found in the JD, 2 each | up to 10 |
   | Level: new grad 20, entry 18, not stated 10, mid 8 | up to 20 |
   | Freshness: ≤6 h 20, ≤24 h 15, ≤3 d 10, ≤7 d 6, ≤14 d 3, >45 d −8 | −8 to 20 |
   | Citizenship / clearance / no-sponsorship · PhD required | −5 · −10 |

   P1 ≥ 72, P2 ≥ 56, P3 below that. All weights are in `config.yaml`.
4. **Remembers** what it has already seen, so the **email only contains roles that are new since the last run**. It records when each role was first seen, when it was posted, and when it closed.
5. **Publishes a dashboard** on GitHub Pages: search, filters, sorting, and an application tracker (Saved → Applied → OA → Interviewing → Offer) with notes.

Everything runs on GitHub Actions. It costs nothing and needs no server (see **What it costs** below).

---

## Tuned for Vaishnavi (MS Computer Vision, CMU RI, Dec 2026)

- **Roles**: computer vision first, then ML engineer, GenAI, research engineer, forward-deployed. Research scientist is low priority: topical ones (CV / generative / 3D) cap at P2, others at P3, and they never trigger instant alerts.
- **Level**: new grad, entry and mid (L3/L4 type, up to 5 years asked). Senior, staff and L5+ are excluded.
- **Visa**: F-1 → OPT → future sponsorship, so roles requiring US citizenship or clearance, or saying they won't sponsor, are removed.
- **Fit with her CV**: each job description is matched against 9 proof points from her CV (Sync Labs VLM, ECCV 2026, Slot4D, reward-tilted sampling, Bhashini/Triton, CVIT/IROS/WACV/patent, Gaussian splatting, robot pose, C++). Matches add up to 14 points and appear as "Why she fits".
- **Off-domain ML** (security, recsys/ads, fraud, chip design…) loses 15 points unless the job description clearly matches her CV.
- **Sources**: ~95 company boards (70+ slugs taken from job links in her own search), Snap / NVIDIA / Adobe Workday sites, amazon.jobs, the new-grad lists and HN.
- **Apply kit** on every role: cold email, ≤300-character LinkedIn note, LinkedIn message, referral ask, form answers (work authorization), and LinkedIn people searches (recruiters, team engineers, CMU alumni). Drafts only use the `evidence` text in `config.yaml`. The one thing left for her to write is the line about why that company, which is what makes a cold email work.
- **History tags**: `history:` in `config.yaml` marks companies where she's in process or recently closed (Snap, Eventual, Apple, Tesla, Waymo, Applied Intuition). Keep it current.

---

## Setup (about 10 minutes, once)

1. **Create the repo.** On github.com create a new repository (private is fine; GitHub Pages on a private repo needs a paid plan, so make it public if you want the dashboard on a free account). Upload the contents of this folder, including the hidden `.github` folder. Or from a terminal: `git init && git add . && git commit -m init && git remote add origin <url> && git push -u origin main`
2. **Email secrets.** Use a Gmail account with 2-Step Verification on, and create an **App Password** at <https://myaccount.google.com/apppasswords>. Then in the repo go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   | Secret | Value |
   |---|---|
   | `SMTP_USER` | the Gmail address that sends |
   | `SMTP_PASS` | the 16-character app password |
   | `EMAIL_TO` | where the digest goes; comma-separate several, e.g. `sister@cmu.edu,you@gmail.com` |
   | `DISCORD_WEBHOOK` *(optional)* | a Discord channel webhook URL, for phone pings |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` *(optional)* | for Telegram pings |
3. **Allow the workflow to commit.** Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save.
4. **Turn on the dashboard.** Settings → Pages → Source: **Deploy from a branch** → Branch `main`, folder **`/docs`** → Save. Your URL will be `https://<username>.github.io/<repo>/`. Paste it into `notify.dashboard_url` in `config.yaml` so emails link to it.
5. **First run.** Actions tab → **job-radar** → **Run workflow**. It takes about 2 minutes and sends a one-time "Job Radar is live" email with the best roles open right now. After that it runs hourly by itself.

### Schedule: hourly crawl, IST notifications
- **Crawl: every hour, 24/7** (`.github/workflows/radar.yml`). US companies post during US working hours, which is roughly **6:30 PM to 3:30 AM IST**. A crawler that only ran in Indian daytime would see most postings 10+ hours late. Hourly crawling catches each one within about an hour.
- **Notifications follow IST** (`config.yaml → notify`):
  - **Instant "Apply now" alert** for any new **P1** role between **08:00 and 24:00 IST**, the moment it's found. P1s found overnight wait for the 9 AM digest.
  - **Digest emails at 9:00, 13:00, 18:00 and 22:00 IST** with every new P2+ role since the previous digest. If GitHub starts a run late, the digest still goes out on the next run.
  - The very first run sends a one-time "Job Radar is live" email with what's open right now.
- Change any of these hours in `config.yaml`. No cron editing needed.

## Tuning it (`config.yaml`)

- **Visa:** if she'll need H-1B sponsorship after OPT, set `needs_sponsorship: true`. Citizenship-only, clearance and "no sponsorship" roles are then dropped instead of flagged.
- **Experience ceiling:** `max_years_experience: 4`. Lower it to 2 to focus on true entry roles.
- **Add a company:** open its careers page, click any job, and read the URL:
  `job-boards.greenhouse.io/`**`acme`** → `{name: Acme, ats: greenhouse, slug: acme}`
  `jobs.lever.co/`**`acme`** / `jobs.ashbyhq.com/`**`acme`** → same, with `lever` / `ashby`.
  If you're unsure, use `ats: auto`. It tries all three and caches the one that works.
- **Change priorities:** move companies between `frontier_lab`, `big_tech` and `top_startup` under `tiers`.
- **Fewer emails:** `notify.min_priority: P1`.
- Boards that failed or weren't found are listed at the bottom of the dashboard and in the Actions log. Usually it's a wrong slug, or the company uses Workday, which is covered via the curated lists instead.

### Run locally
```bash
pip install -r requirements.txt
python -m radar.main --no-notify      # crawl + update docs/data/jobs.json, no email
python -m pytest -q tests             # offline tests
cd docs && python -m http.server      # open http://localhost:8000
```

---

## What it costs
**Nothing, as set up here.**
| Piece | Cost |
|---|---|
| GitHub Actions (the hourly crawler) | **Public repo: free, unlimited.** Private repo: 2,000 free minutes/month; hourly runs use ~750–1,500, so it still fits. To be safe on private, change the cron to every 2 hours (`17 */2 * * *`). |
| GitHub Pages (the dashboard) | Free on public repos (private repos need a paid plan for Pages). |
| Gmail sending | Free. |
| Company job APIs / curated lists | Free, public, no keys. |
| Claude | **None to run it.** Once it's on GitHub it doesn't talk to Claude at all. Chats with Claude to tune it or draft emails are covered by your normal Claude plan. |

Recommended: a **public** repo. It's job listings plus a config file, with nothing sensitive in it. Keep resume details out of `config.yaml` if the repo is public; a short pitch line is fine.

## Applying fast and cold emails
- Each role in the email and on the dashboard links straight to the company's **apply page**. Applying on day 0 is the single biggest edge, which is why fresh roles get +20 points.
- **Email draft** button on every role: a short cold email to a recruiter or an engineer on the team, pre-filled from `candidate.profile` (name, degree, pitch, highlights, links). Edit the bracketed bits, then copy.
- Find the right person: on LinkedIn, search `"<Company>" recruiter university` or `"<Company>" computer vision engineer`, prefer CMU alumni, and send a connection note or InMail. Many companies use `first@company.com` or `first.last@company.com`, and a verifier such as Hunter.io's free tier can confirm it.
- Not built in on purpose: **auto-applying**. Mass auto-submission gets flagged by ATS systems, breaks on custom questions, and produces worse applications than 10 tailored ones a day. The [Simplify extension](https://simplify.jobs) autofills forms in one click while she still reviews each one.

## Why not scrape LinkedIn?
LinkedIn forbids automated scraping in its terms. It blocks bots aggressively and can restrict the account doing it, which is the last thing you want during a job hunt. The good news is that almost every role on LinkedIn is a re-post of a company's own career page, and this radar reads those pages directly, usually hours earlier. For LinkedIn itself, use its built-in alerts, which are free and reliable:

> Jobs → search `("machine learning engineer" OR "research engineer" OR "applied scientist" OR "computer vision engineer" OR "forward deployed engineer")` → Location: United States → Experience level: **Entry level + Associate** → Date posted: **Past 24 hours** → toggle **Set alert** (daily, email + app).

Make a second alert with "new grad 2026" and "new grad 2027". Also check "Job seeker → Open to work → recruiters only".

## Where application tracking is stored
Statuses and notes live in the browser's local storage on whichever device opens the dashboard. Use **My pipeline → Copy backup** now and then, and **Restore** on another device.

## More resources
Each of these is also on the dashboard's Resources tab.

- **Curated lists:** [SimplifyJobs New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions), [speedyapply 2027-AI-College-Jobs](https://github.com/speedyapply/2027-AI-College-Jobs), [Simplify DS/AI/ML new-grad list](https://simplify.jobs/l/New-Grad-Data-Science-AI-ML), [GitHub topic: new-grad-jobs](https://github.com/topics/new-grad-jobs)
- **Career-page search engines:** [HiringCafe](https://hiring.cafe) (free AI talent agent), [Jobright.ai](https://jobright.ai), [TrueUp](https://trueup.io), [Wellfound](https://wellfound.com/jobs), [YC Work at a Startup](https://www.workatastartup.com)
- **People posting roles:** [HN Who's Hiring](https://news.ycombinator.com/submitted?id=whoishiring), [80,000 Hours job board](https://jobs.80000hours.org) (AI safety), Handshake via CMU
- **Newsletters:** [Data Science Weekly](https://www.datascienceweekly.org) (has a jobs section), [Deep Learning Weekly](https://www.deeplearningweekly.com), [Import AI](https://importai.substack.com), [The Batch](https://www.deeplearning.ai/the-batch/)
- **DIY scrapers others built:** [python-jobspy](https://pypi.org/project/python-jobspy/) (LinkedIn/Indeed/Glassdoor; fragile, so use at your own risk)
