import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
OUTPUT.mkdir(exist_ok=True)

DB_PATH = BASE / "jobs.db"
SOURCES_PATH = BASE / "config" / "sources.json"
TERMS_PATH = BASE / "config" / "search_terms.json"
RESUME_PATH = BASE / "resume_profile.json"
MANUAL_LINKS = BASE / "manual_links.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 DispatcherJobScout/2.0"
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        found_date TEXT,
        source TEXT,
        title TEXT,
        company TEXT,
        location TEXT,
        url TEXT UNIQUE,
        description TEXT,
        part_type TEXT,
        experience_flag TEXT,
        resume_fit INTEGER,
        career_fit INTEGER,
        priority TEXT,
        status TEXT DEFAULT 'New',
        application_date TEXT,
        cover_letter TEXT
    )
    """)
    conn.commit()
    return conn

def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()

def fetch_html(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code >= 400:
            return ""
        return r.text
    except Exception:
        return ""

def infer_part_type(text):
    t = text.lower()
    parts = []
    if "part 121" in t:
        parts.append("Part 121")
    if "part 135" in t:
        parts.append("Part 135")
    if "part 91" in t:
        parts.append("Part 91")
    if "cargo" in t:
        parts.append("Cargo")
    if "charter" in t:
        parts.append("Charter")
    if not parts:
        return "Unknown"
    return ", ".join(parts)

def infer_experience(text):
    t = text.lower()
    friendly = [
        "entry level", "entry-level", "0-3", "0 to 3", "one year", "1 year",
        "preferred", "willing to train", "dispatcher certificate", "recent graduate"
    ]
    hard = ["5 years required", "five years required", "10 years", "senior dispatcher"]
    if any(x in t for x in hard):
        return "Likely too senior"
    if any(x in t for x in friendly):
        return "0-3 friendly or preferred experience"
    return "Review manually"

def score_job(title, description, terms, resume):
    text = f"{title} {description}".lower()
    score = 45

    for kw in terms["positive_keywords"]:
        if kw.lower() in text:
            score += 4

    for kw in terms["negative_keywords"]:
        if kw.lower() in text:
            score -= 8

    for cert in resume["certifications"]:
        if "dispatcher" in cert.lower() and ("dispatcher" in text or "flight follower" in text):
            score += 10

    if "occ" in text or "ioc" in text or "operational control" in text:
        score += 8

    if "flight follower" in text:
        score += 8

    if "part 135" in text or "cargo" in text or "charter" in text:
        score += 8

    if "part 121" in text:
        score += 7

    resume_fit = max(0, min(100, score))
    career_fit = max(0, min(100, score + 3 if "manager" not in text else score - 5))

    if resume_fit >= 88:
        priority = "Very High"
    elif resume_fit >= 78:
        priority = "High"
    elif resume_fit >= 68:
        priority = "Medium"
    else:
        priority = "Low"

    return resume_fit, career_fit, priority

def make_cover_letter(job, resume):
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    return f"""Dear Hiring Team,

I am applying for {title} with {company}. I hold an FAA Aircraft Dispatcher Certificate and bring a strong operations background built around real-time decision making, safety, compliance, and coordination across teams.

My background includes leading 24/7 operations environments, managing large teams, improving service reliability, and responding to time-sensitive operational issues. I also bring aviation-specific training, FAR knowledge, private pilot experience, and a clear focus on dispatcher and flight operations work.

What interests me about this role is the opportunity to support safe, reliable flight operations while building direct experience in airline, cargo, charter, or corporate aviation operations. I understand my transition point clearly: I am new to direct dispatch release work, but I bring mature operational judgment, communication discipline, and a strong safety mindset.

I would welcome the opportunity to contribute to your operation and grow within your flight operations team.

Sincerely,
Ricky
"""

def parse_generic_jobs(source_name, html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Generic link-driven extraction. This works as a broad first pass.
    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" "))
        href = a["href"]

        if not text or len(text) < 8:
            continue

        lower = text.lower()
        if not any(term in lower for term in [
            "dispatcher", "flight follower", "flight operations", "flight planner", "occ", "ioc"
        ]):
            continue

        if href.startswith("/"):
            parsed = urlparse(source_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"

        results.append({
            "source": source_name,
            "title": text[:150],
            "company": "",
            "location": "",
            "url": href,
            "description": text
        })

    return results

def read_manual_links():
    rows = []
    if not MANUAL_LINKS.exists():
        return rows
    try:
        df = pd.read_csv(MANUAL_LINKS)
        for _, r in df.iterrows():
            url = str(r.get("url", "")).strip()
            if url and url.lower() != "nan":
                rows.append({
                    "source": str(r.get("source", "Manual")),
                    "title": "Manual review needed",
                    "company": "",
                    "location": "",
                    "url": url,
                    "description": str(r.get("notes", "Manual link"))
                })
    except Exception:
        pass
    return rows

def insert_job(conn, job):
    cur = conn.cursor()
    try:
        cur.execute("""
        INSERT INTO jobs (
            found_date, source, title, company, location, url, description,
            part_type, experience_flag, resume_fit, career_fit, priority, cover_letter
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_iso(),
            job["source"],
            job["title"],
            job.get("company", ""),
            job.get("location", ""),
            job["url"],
            job.get("description", ""),
            job["part_type"],
            job["experience_flag"],
            job["resume_fit"],
            job["career_fit"],
            job["priority"],
            job["cover_letter"]
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def export_excel(conn):
    df = pd.read_sql_query("SELECT * FROM jobs ORDER BY found_date DESC, resume_fit DESC", conn)
    out = OUTPUT / "dispatcher_jobs_tracker.xlsx"

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Job Tracker")

        dash = pd.DataFrame({
            "Metric": [
                "Total jobs",
                "Very High priority",
                "High priority",
                "New jobs",
                "Last run UTC"
            ],
            "Value": [
                len(df),
                int((df["priority"] == "Very High").sum()) if not df.empty else 0,
                int((df["priority"] == "High").sum()) if not df.empty else 0,
                int((df["status"] == "New").sum()) if not df.empty else 0,
                now_iso()
            ]
        })
        dash.to_excel(writer, index=False, sheet_name="Dashboard")

    return out

def write_top_matches(conn):
    df = pd.read_sql_query("SELECT * FROM jobs ORDER BY resume_fit DESC LIMIT 10", conn)
    out = OUTPUT / "top_matches.txt"
    lines = []
    for _, r in df.iterrows():
        lines.append(f"{r['resume_fit']}% | {r['priority']} | {r['title']} | {r['source']} | {r['url']}")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out

def main():
    sources = load_json(SOURCES_PATH)["sources"]
    terms = load_json(TERMS_PATH)
    resume = load_json(RESUME_PATH)
    conn = init_db()

    found = []

    for src in sources:
        if not src.get("enabled", True):
            continue
        html = fetch_html(src["url"])
        if not html:
            continue
        found.extend(parse_generic_jobs(src["name"], html, src["url"]))

    found.extend(read_manual_links())

    new_count = 0
    for job in found:
        combined = f"{job.get('title','')} {job.get('description','')}"
        job["part_type"] = infer_part_type(combined)
        job["experience_flag"] = infer_experience(combined)
        job["resume_fit"], job["career_fit"], job["priority"] = score_job(job["title"], job["description"], terms, resume)
        job["cover_letter"] = make_cover_letter(job, resume)

        if insert_job(conn, job):
            new_count += 1

    excel = export_excel(conn)
    top = write_top_matches(conn)

    print(f"Run complete. New jobs added: {new_count}")
    print(f"Excel tracker: {excel}")
    print(f"Top matches: {top}")

if __name__ == "__main__":
    main()
