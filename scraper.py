import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import hashlib
import sys
import os
import json
import logging

# ——— Logging Setup ———
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraper.log')
    ]
)
logger = logging.getLogger("Scraper")

def log_system_info():
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current directory: {os.getcwd()}")
    logger.info(f"Files in directory: {os.listdir()}")
    try:
        with open('service-account.json') as f:
            data = json.load(f)
            logger.info(f"Service account loaded for: {data.get('client_email', '<unknown>')}")
    except Exception as e:
        logger.error(f"Service account error: {e}")

def safe_request(url):
    try:
        logger.info(f"Requesting URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r
    except Exception as e:
        logger.error(f"Request failed ({url}): {e}")
        return None

def get_question_hash(q: str) -> str:
    return hashlib.md5(q.lower().encode()).hexdigest()

def extract_questions(soup: BeautifulSoup, selector: str) -> list[str]:
    """Try headings first; if none found, fall back to <li> scan."""
    qs = []
    # Primary: any element matching the selector
    for el in soup.select(selector):
        text = el.get_text(strip=True)
        if '?' in text and len(text) > 10:
            qs.append(text)

    # Fallback: scan all <li> items
    if not qs:
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if '?' in text and len(text) > 10:
                qs.append(text)

    return qs

def update_database() -> bool:
    logger.info("===== Starting database update =====")
    log_system_info()

    # ——— Google Sheets Setup ———
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            'service-account.json', scope
        )
        client = gspread.authorize(creds)
        sheet = client.open("InterviewCoach_DB").sheet1
        existing = sheet.get_all_records()
        df_existing = pd.DataFrame(existing)
        logger.info(f"Loaded {len(existing)} existing records")
        used_hashes = (
            set(df_existing['question'].apply(get_question_hash))
            if not df_existing.empty and 'question' in df_existing.columns
            else set()
        )
    except Exception as e:
        logger.critical(f"Google Sheets access failed: {e}")
        return False

    # ——— Sources with updated selectors ———
    sources = [
        {
            "url": "https://www.interviewbit.com/data-science-interview-questions/",
            "selector": "div.markdown-content h2, div.markdown-content h3"
        },
        {
            "url": "https://www.geeksforgeeks.org/python-interview-questions/",
            "selector": "div.content h2, div.content h3"
        },
        {
            "url": "https://www.interviewbit.com/python-interview-questions/",
            "selector": "div.markdown-content h3"
        }
    ]

    all_new = []
    for src in sources:
        r = safe_request(src["url"])
        if not r:
            continue

        soup = BeautifulSoup(r.text, 'html.parser')
        found = extract_questions(soup, src["selector"])
        logger.info(f"Found {len(found)} questions at {src['url']}")
        all_new.extend(found)
        time.sleep(2)

    # ——— Deduplicate & Append ———
    added = 0
    for q in set(all_new):
        h = get_question_hash(q)
        if h in used_hashes:
            continue

        try:
            answer = (
                "This is an important interview question. Focus on providing a clear, "
                "structured response that highlights your relevant skills and experience."
            )
            sheet.append_row([
                f"scraped-{int(time.time())}",
                q,
                answer,
                "Tech",      # category
                "all",       # audience
                "auto-generated",
                "scraped",
                datetime.now().strftime("%Y-%m-%d")
            ])
            logger.info(f"Added question: {q[:50]}...")
            used_hashes.add(h)
            added += 1
        except Exception as e:
            logger.error(f"Failed to append to sheet: {e}")

    logger.info(f"Total new questions added: {added}")

    # Always succeed unless a critical exception occurred
    return True

if __name__ == "__main__":
    try:
        update_database()
        logger.info("===== Scraper completed (no critical errors) =====")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Uncaught exception: {e}")
        sys.exit(1)
