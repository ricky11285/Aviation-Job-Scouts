import imaplib
import email
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header
from urllib.parse import urlparse

from dotenv import load_dotenv


load_dotenv()


EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_DAYS_BACK = int(os.getenv("EMAIL_DAYS_BACK", "7"))


KEYWORDS = [
    "aircraft dispatcher",
    "flight dispatcher",
    "flight follower",
    "dispatcher",
    "operations control",
    "occ",
    "ioc",
    "load control",
    "crew scheduler",
]


SOURCES = {
    "indeed": "Indeed",
    "glassdoor": "Glassdoor",
    "monster": "Monster",
    "linkedin": "LinkedIn",
    "jsfirm": "JSfirm",
}


def decode_mime_text(value):
    if not value:
        return ""

    parts = decode_header(value)
    decoded = ""

    for text, encoding in parts:
        if isinstance(text, bytes):
            decoded += text.decode(encoding or "utf-8", errors="ignore")
        else:
            decoded += text

    return decoded


def extract_body(msg):
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition"))

            if "attachment" in disposition:
                continue

            if content_type in ["text/plain", "text/html"]:
                payload = part.get_payload(decode=True)

                if payload:
                    body += payload.decode(errors="ignore") + "\n"
    else:
        payload = msg.get_payload(decode=True)

        if payload:
            body = payload.decode(errors="ignore")

    return body


def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_links(text):
    pattern = r"https?://[^\s\"'<>]+"
    links = re.findall(pattern, text)

    cleaned = []

    for link in links:
        link = link.replace("&amp;", "&")
        link = link.rstrip(").,;]")
        cleaned.append(link)

    return list(dict.fromkeys(cleaned))


def detect_source(subject, sender, body):
    combined = f"{subject} {sender} {body}".lower()

    for key, label in SOURCES.items():
        if key in combined:
            return label

    return "Email Alert"


def looks_relevant(text):
    lower = text.lower()
    return any(keyword in lower for keyword in KEYWORDS)


def guess_title(subject, body):
    subject = clean_text(subject)

    if looks_relevant(subject):
        return subject[:150]

    lines = body.splitlines()

    for line in lines:
        line = clean_text(line)

        if looks_relevant(line) and len(line) <= 150:
            return line[:150]

    return subject[:150] or "Job alert match"


def search_email_jobs():
    results = []

    if not EMAIL_USER or not EMAIL_PASSWORD:
        print("Email source skipped: EMAIL_USER or EMAIL_PASSWORD missing.")
        return results

    since_date = (datetime.now() - timedelta(days=EMAIL_DAYS_BACK)).strftime("%d-%b-%Y")

    queries = [
        f'(SINCE "{since_date}" SUBJECT "Indeed")',
        f'(SINCE "{since_date}" SUBJECT "Glassdoor")',
        f'(SINCE "{since_date}" SUBJECT "Monster")',
        f'(SINCE "{since_date}" SUBJECT "LinkedIn")',
        f'(SINCE "{since_date}" SUBJECT "JSfirm")',
        f'(SINCE "{since_date}" TEXT "aircraft dispatcher")',
        f'(SINCE "{since_date}" TEXT "flight dispatcher")',
        f'(SINCE "{since_date}" TEXT "flight follower")',
    ]

    try:
        mail = imaplib.IMAP4_SSL(EMAIL_HOST)
        mail.login(EMAIL_USER, EMAIL_PASSWORD)
        mail.select("inbox")

        seen_ids = set()

        for query in queries:
            status, data = mail.search(None, query)

            if status != "OK":
                continue

            ids = data[0].split()

            for msg_id in ids[-50:]:
                if msg_id in seen_ids:
                    continue

                seen_ids.add(msg_id)

                status, msg_data = mail.fetch(msg_id, "(RFC822)")

                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = decode_mime_text(msg.get("Subject", ""))
                sender = decode_mime_text(msg.get("From", ""))
                body_raw = extract_body(msg)
                body = clean_text(body_raw)

                combined = f"{subject} {sender} {body}"

                if not looks_relevant(combined):
                    continue

                links = extract_links(body_raw)

                source = detect_source(subject, sender, body)
                title = guess_title(subject, body_raw)

                job_links = []

                for link in links:
                    domain = urlparse(link).netloc.lower()

                    if any(site in domain for site in ["indeed", "glassdoor", "monster", "linkedin", "jsfirm"]):
                        job_links.append(link)

                if not job_links:
                    job_links = links[:1]

                for link in job_links[:5]:
                    results.append({
                        "source": source,
                        "title": title,
                        "company": "",
                        "location": "",
                        "url": link,
                        "description": body[:1000],
                    })

        mail.logout()

    except Exception as e:
        print(f"Email source error: {e}")

    return results