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
            logger.info(f"Service account loaded for: {data.get('client_email', '<unknown>')}")
    except Exception as e:
        logger.error(f"Service account error: {e}")


def safe_request(url, **kwargs):
    try:
        logger.info(f"Requesting URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        return requests.get(url, headers=headers, timeout=15, **kwargs).raise_for_status() or requests.get(url, headers=headers, timeout=15, **kwargs)
    except Exception as e:
        logger.error(f"Request failed ({url}): {e}")
        return None


def get_question_hash(q: str) -> str:
    return hashlib.md5(q.lower().encode()).hexdigest()


def extract_questions(soup: BeautifulSoup, src_url: str, selector: str):
    results = []
    for el in soup.select(selector):
        text = el.get_text(strip=True)
        if '?' not in text or len(text) < 10:
            continue
        a = el.find('a', href=True)
        link = urllib.parse.urljoin(src_url, a['href']) if a else None
        results.append({"text": text, "link": link})
    if not results:
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if '?' not in text or len(text) < 10:
                continue
            results.append({"text": text, "link": None})
    return results


def extract_answer(url: str) -> str:
    if url:
        resp = safe_request(url)
        if resp:
            sub = BeautifulSoup(resp.text, 'html.parser')
            # InterviewBit
            ans = sub.select_one('div.answer-text')
            if ans:
                return ans.get_text("\n", strip=True)
            # GfG
            container = sub.select_one('div.content')
            if container:
                paras = container.find_all(['p', 'pre'])
                if paras:
                    return "\n\n".join(p.get_text(strip=True) for p in paras)
            # generic
            article = sub.find('article')
            if article:
                return article.get_text("\n", strip=True)
    # fallback to Google search
    return search_google(url_query=url or "")


def search_google(url_query: str) -> str:
    """Scrape Google search result snippets for the question text."""
    query = urllib.parse.quote_plus(url_query)
    search_url = f"https://www.google.com/search?q={query}&hl=en&num=5"
    resp = safe_request(search_url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, 'html.parser')

    for g in soup.select('div.g'):
        # skip “People also ask” or knowledge panels
        if g.select_one('div[data-attrid]'):
            continue
        # organic snippet
        snippet = g.select_one('div.VwiC3b')
        if snippet:
            text = snippet.get_text(separator=" ", strip=True)
            # filter out ads
            if "Ad " in text or "Sponsored" in text:
                continue
            return text
    return ""


def update_database() -> bool:
    logger.info("===== Starting database update =====")
    log_system_info()

    # — Sheets setup —
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("InterviewCoach_DB").sheet1
        existing = sheet.get_all_records()
        df_existing = pd.DataFrame(existing)
        logger.info(f"Loaded {len(existing)} existing records")
        used_hashes = set(df_existing['question'].apply(get_question_hash)) if not df_existing.empty else set()
    except Exception as e:
        logger.critical(f"Google Sheets access failed: {e}")
        return False

    sources = [
        {"url": "https://www.interviewbit.com/data-science-interview-questions/", "selector": "div.markdown-content h2, div.markdown-content h3"},
        {"url": "https://www.geeksforgeeks.org/python-interview-questions/",      "selector": "div.content h2, div.content h3"},
        {"url": "https://www.interviewbit.com/python-interview-questions/",         "selector": "div.markdown-content h3"}
    ]

    all_new = []
    for src in sources:
        resp = safe_request(src["url"])
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        qs = extract_questions(soup, src["url"], src["selector"])
        logger.info(f"Found {len(qs)} questions at {src['url']}")
        all_new.extend(qs)
        time.sleep(2)

    added = 0
    for text, link in { (q["text"], q["link"]) for q in all_new }:
        h = get_question_hash(text)
        if h in used_hashes:
            continue
        answer = extract_answer(link or text)
        try:
            sheet.append_row([
                f"scraped-{int(time.time())}",
                text,
                answer,
                "Tech", "all", "auto-generated", "scraped",
                datetime.now().strftime("%Y-%m-%d")
            ])
            logger.info(f"Added Q&A: {text[:50]}...")
            used_hashes.add(h)
            added += 1
            time.sleep(1)  # avoid write‑rate limits
        except Exception as e:
            logger.error(f"Failed to append: {e}")

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
