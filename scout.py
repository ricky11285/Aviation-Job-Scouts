import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
OUTPUT.mkdir(exist_ok=True)

DB_PATH = BASE / "jobs.db"
SOURCES_PATH = BASE / "config" / "sources.json"
TERMS_PATH = BASE / "config" / "search_terms.json"
RESUME_PATH = BASE / "resume_profile.json"

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
        priority TEXT
    )
    """)

    conn.commit()

    return conn


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_html(url):
    try:
        with sync_playwright() as p:

            browser = p.chromium.launch(headless=True)

            page = browser.new_page()

            page.goto(url, timeout=60000)

            page.wait_for_timeout(5000)

            html = page.content()

            browser.close()

            return html

    except Exception as e:
        print(f"Playwright error: {e}")
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
        "entry level",
        "entry-level",
        "0-3",
        "0 to 3",
        "one year",
        "1 year",
        "preferred",
        "willing to train",
        "dispatcher certificate",
        "recent graduate"
    ]

    hard = [
        "5 years required",
        "five years required",
        "10 years",
        "senior dispatcher"
    ]

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
        if "dispatcher" in cert.lower():
            if "dispatcher" in text or "flight follower" in text:
                score += 10

    if "occ" in text or "ioc" in text:
        score += 8

    if "operational control" in text:
        score += 8

    if "flight follower" in text:
        score += 8

    if "part 135" in text:
        score += 8

    if "cargo" in text:
        score += 8

    if "charter" in text:
        score += 8

    if "part 121" in text:
        score += 7

    resume_fit = max(0, min(100, score))

    career_fit = max(
        0,
        min(
            100,
            score + 3 if "manager" not in text else score - 5
        )
    )

    if resume_fit >= 88:
        priority = "Very High"

    elif resume_fit >= 78:
        priority = "High"

    elif resume_fit >= 68:
        priority = "Medium"

    else:
        priority = "Low"

    return resume_fit, career_fit, priority


def parse_generic_jobs(source_name, html, source_url):

    soup = BeautifulSoup(html, "html.parser")

    results = []

    for a in soup.find_all("a", href=True):

        text = clean_text(a.get_text(" "))

        href = a["href"]

        if not text:
            continue

        if len(text) < 8:
            continue

        lower = text.lower()

        if not any(term in lower for term in [
            "dispatcher",
            "flight follower",
            "flight operations",
            "flight planner",
            "occ",
            "ioc"
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


def insert_job(conn, job):

    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO jobs (
            found_date,
            source,
            title,
            company,
            location,
            url,
            description,
            part_type,
            experience_flag,
            resume_fit,
            career_fit,
            priority
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            job["priority"]
        ))

        conn.commit()

        return True

    except sqlite3.IntegrityError:

        return False


def export_excel(conn):

    df = pd.read_sql_query(
        "SELECT * FROM jobs ORDER BY found_date DESC, resume_fit DESC",
        conn
    )

    out = OUTPUT / "dispatcher_jobs_tracker.xlsx"

    with pd.ExcelWriter(out, engine="openpyxl") as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Job Tracker"
        )

        dash = pd.DataFrame({
            "Metric": [
                "Total jobs",
                "Very High priority",
                "High priority",
                "Last run UTC"
            ],
            "Value": [
                len(df),
                int((df["priority"] == "Very High").sum())
                if not df.empty else 0,

                int((df["priority"] == "High").sum())
                if not df.empty else 0,

                now_iso()
            ]
        })

        dash.to_excel(
            writer,
            index=False,
            sheet_name="Dashboard"
        )

    return out


def write_top_matches(conn):

    df = pd.read_sql_query(
        "SELECT * FROM jobs ORDER BY resume_fit DESC LIMIT 10",
        conn
    )

    out = OUTPUT / "top_matches.txt"

    lines = []

    for _, r in df.iterrows():

        lines.append(
            f"{r['resume_fit']}% | "
            f"{r['priority']} | "
            f"{r['title']} | "
            f"{r['source']} | "
            f"{r['url']}"
        )

    out.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

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

        found.extend(
            parse_generic_jobs(
                src["name"],
                html,
                src["url"]
            )
        )

    new_count = 0

    for job in found:

        combined = (
            f"{job.get('title', '')} "
            f"{job.get('description', '')}"
        )

        job["part_type"] = infer_part_type(combined)

        job["experience_flag"] = infer_experience(combined)

        (
            job["resume_fit"],
            job["career_fit"],
            job["priority"]
        ) = score_job(
            job["title"],
            job["description"],
            terms,
            resume
        )

        if insert_job(conn, job):
            new_count += 1

    excel = export_excel(conn)

    top = write_top_matches(conn)

    print(f"Run complete. New jobs added: {new_count}")

    print(f"Excel tracker: {excel}")

    print(f"Top matches: {top}")


if __name__ == "__main__":
    main()
