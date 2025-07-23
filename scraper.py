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


def safe_request(url: str, **kwargs) -> requests.Response | None:
    """GET + raise_for_status, return response or None."""
    try:
        logger.info(f"Requesting URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        resp = requests.get(url, headers=headers, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.error(f"Request failed ({url}): {e}")
        return None


def get_question_hash(q: str) -> str:
    return hashlib.md5(q.lower().encode()).hexdigest()


def extract_questions(soup: BeautifulSoup, src_url: str, selector: str):
    results: list[dict] = []
    for el in soup.select(selector):
        text = el.get_text(strip=True)
        if '?' not in text or len(text) < 10:
            continue
        # link if present
        a = el.find('a', href=True)
        link = urllib.parse.urljoin(src_url, a['href']) if a else None
        results.append({"text": text, "link": link})
    # fallback to <li>
    if not results:
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if '?' not in text or len(text) < 10:
                continue
            results.append({"text": text, "link": None})
    return results


def extract_answer(link: str | None, question_text: str) -> str:
    """
    If link is given, scrape that page; otherwise Google-search the question_text.
    """
    if link:
        resp = safe_request(link)
        if resp:
            sub = BeautifulSoup(resp.text, 'html.parser')
            # try InterviewBit
            ans = sub.select_one('div.answer-text')
            if ans:
                return ans.get_text("\n", strip=True)
            # try GfG
            cont = sub.select_one('div.content')
            if cont:
                paras = cont.find_all(['p','pre'])
                if paras:
                    return "\n\n".join(p.get_text(strip=True) for p in paras)
            # fallback to <article>
            art = sub.find('article')
            if art:
                return art.get_text("\n", strip=True)
    # no link or no scrapeable answer → Google fallback
    return search_google(question_text)


def search_google(question_text: str) -> str:
    """
    Hit Google, grab the first organic snippet, filtering out ads and panels.
    """
    query = urllib.parse.quote_plus(question_text)
    url = f"https://www.google.com/search?q={query}&hl=en&num=5"
    resp = safe_request(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, 'html.parser')
    for g in soup.select('div.g'):
        # skip knowledge panels / “People also ask”
        if g.select_one('[data-attrid]'):
            continue
        # organic text snippet
        snip = g.select_one('div.VwiC3b')
        if snip:
            txt = snip.get_text(" ", strip=True)
            if "Ad " in txt or "Sponsored" in txt:
                continue
            return txt
    return ""


def update_database() -> bool:
    logger.info("===== Starting database update =====")
    log_system_info()

    # — Google Sheets auth —
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
        {"url":"https://www.interviewbit.com/data-science-interview-questions/","selector":"div.markdown-content h2, div.markdown-content h3"},
        {"url":"https://www.geeksforgeeks.org/python-interview-questions/","selector":"div.content h2, div.content h3"},
        {"url":"https://www.interviewbit.com/python-interview-questions/","selector":"div.markdown-content h3"}
    ]

    all_qs: list[dict] = []
    for src in sources:
        resp = safe_request(src["url"])
        if not resp: continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        qs = extract_questions(soup, src["url"], src["selector"])
        logger.info(f"Found {len(qs)} questions at {src['url']}")
        all_qs.extend(qs)
        time.sleep(2)

    added = 0
    for q in { (item["text"], item["link"]) for item in all_qs }:
        text, link = q
        h = get_question_hash(text)
        if h in existing_hashes:
            continue
        answer = extract_answer(link, text)
        try:
            sheet.append_row([
                f"scraped-{int(time.time())}",
                text,
                answer,
                "Tech","all","auto-generated","scraped",
                datetime.now().strftime("%Y-%m-%d")
            ])
            logger.info(f"Added Q&A: {text[:50]}...")
            existing_hashes.add(h)
            added += 1
            time.sleep(1)
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
