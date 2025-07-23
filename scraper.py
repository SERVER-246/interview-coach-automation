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
import urllib.parse

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
            logger.info(f"Service account loaded for: {data.get('client_email','<unknown>')}")
    except Exception as e:
        logger.error(f"Service account error: {e}")

def safe_request(url: str, **kwargs):
    """Perform one GET + raise_for_status, return response or None."""
    try:
        logger.info(f"Requesting URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        r = requests.get(url, headers=headers, timeout=15, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        logger.error(f"Request failed ({url}): {e}")
        return None

def get_question_hash(q: str) -> str:
    return hashlib.md5(q.lower().encode()).hexdigest()

def extract_questions(soup: BeautifulSoup, src_url: str, selector: str):
    """
    Returns list of dicts with 'text' and optional 'link'.
    Falls back to <li> items if selector yields nothing.
    """
    items = []
    for el in soup.select(selector):
        text = el.get_text(strip=True)
        if '?' not in text or len(text) < 10:
            continue
        a = el.find('a', href=True)
        link = urllib.parse.urljoin(src_url, a['href']) if a else None
        items.append({'text': text, 'link': link})
    if not items:
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if '?' not in text or len(text) < 10:
                continue
            items.append({'text': text, 'link': None})
    return items

def extract_answer(link: str | None, question_text: str) -> str:
    """
    If link provided, scrape that page for an answer. Otherwise, or on failure,
    fall back to Google search of the question_text.
    """
    if link:
        resp = safe_request(link)
        if resp:
            sub = BeautifulSoup(resp.text, 'html.parser')
            # 1) InterviewBit
            ans = sub.select_one('div.answer-text')
            if ans and ans.get_text(strip=True):
                return ans.get_text("\n", strip=True)
            # 2) GeeksforGeeks
            cont = sub.select_one('div.content')
            if cont:
                paras = cont.find_all(['p','pre'])
                if paras:
                    return "\n\n".join(p.get_text(strip=True) for p in paras)
            # 3) Generic article
            art = sub.find('article')
            if art:
                return art.get_text("\n", strip=True)
    # 4) Google fallback
    return search_google(question_text)

def search_google(question_text: str) -> str:
    """
    Scrape the first organic snippet from Google search.
    Tries multiple selectors and logs which one succeeds.
    """
    query = urllib.parse.quote_plus(question_text)
    url = f"https://www.google.com/search?q={query}&hl=en&num=5"
    resp = safe_request(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, 'html.parser')

    snippet_selectors = [
        ('div.VwiC3b', 'VwiC3b'),
        ('div.IsZvec', 'IsZvec'),
        ('span.aCOpRe', 'aCOpRe'),
    ]

    for sel, name in snippet_selectors:
        node = soup.select_one(sel)
        if node:
            text = node.get_text(" ", strip=True)
            if text and not any(marker in text for marker in ("Ad ", "Sponsored")):
                logger.info(f"Google fallback picked using selector {name}")
                return text
            else:
                logger.info(f"Selector {name} found but text was empty or ad-like")

    # No snippet matched
    preview = soup.get_text(" ", strip=True)[:200]
    logger.warning(f"No Google snippet matched; page text preview: {preview!r}")
    return ""

def update_database() -> bool:
    logger.info("===== Starting database update =====")
    log_system_info()

    # Google Sheets authentication
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("InterviewCoach_DB").sheet1
        rows = sheet.get_all_records()
        df = pd.DataFrame(rows)
        logger.info(f"Loaded {len(rows)} existing records")
        existing_hashes = set(df['question'].apply(get_question_hash)) if 'question' in df else set()
    except Exception as e:
        logger.critical(f"Sheets access failed: {e}")
        return False

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

    all_qs = []
    for src in sources:
        resp = safe_request(src["url"])
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        qs = extract_questions(soup, src["url"], src["selector"])
        logger.info(f"Found {len(qs)} questions at {src['url']}")
        all_qs.extend(qs)
        time.sleep(2)

    added = 0
    # Dedupe by question text + link
    for text, link in { (q['text'], q['link']) for q in all_qs }:
        h = get_question_hash(text)
        if h in existing_hashes:
            continue
        answer = extract_answer(link, text)
        try:
            sheet.append_row([
                f"scraped-{int(time.time())}",
                text,
                answer,
                "Tech",          # industry
                "all",           # experience
                "auto-generated",# tags
                "scraped",       # source
                datetime.now().strftime("%Y-%m-%d")
            ])
            logger.info(f"Added Q&A: {text[:50]}...")
            existing_hashes.add(h)
            added += 1
            time.sleep(1)  # avoid rate limits
        except Exception as e:
            logger.error(f"Append failed: {e}")

    logger.info(f"Total new Q&A pairs added: {added}")
    return True

if __name__ == "__main__":
    try:
        update_database()
        logger.info("===== Scraper completed (no critical errors) =====")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Uncaught exception: {e}")
        sys.exit(1)
