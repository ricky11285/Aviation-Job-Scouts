# Dispatcher Job Scout v2

Automated aircraft dispatcher / flight follower job scout.

What it does:
- Searches configurable job sources every run
- Looks for Aircraft Dispatcher, Flight Follower, OCC, IOC, Flight Planner, Crew Scheduler keywords
- Filters for Part 121, Part 135, Part 91, cargo, charter, regional airline, corporate aviation
- Flags 0-3 years / entry-level friendly roles
- Scores each job against your resume profile
- Saves jobs to SQLite so duplicates are avoided
- Exports an Excel tracker
- Creates a basic tailored cover letter draft for each strong match
- Designed to run every 3 hours with GitHub Actions

Important:
- LinkedIn and Glassdoor often block automated scraping. Use their email alerts and paste links into `manual_links.csv`.
- Company career pages, JSfirm, Indeed RSS/search, and simpler boards work better.

## Quick Start

1. Create a GitHub repo.
2. Upload all files from this folder.
3. Add GitHub Secrets:
   - OPENAI_API_KEY, optional
   - EMAIL_FROM, optional
   - EMAIL_TO, optional
   - EMAIL_PASSWORD, optional app password
4. Run locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scout.py
```

5. Output files:
   - `output/dispatcher_jobs_tracker.xlsx`
   - `output/top_matches.txt`
   - `jobs.db`

## GitHub Actions schedule

The workflow runs every 3 hours:

```cron
0 */3 * * *
```

## Best use

Use this as the engine. Use Google Sheets later as the live tracker. Excel export stays as backup.
