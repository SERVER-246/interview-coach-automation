# answer_filler.py

import os
import sys
import time
import json
import logging
import hashlib
import urllib.parse

import requests
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup

# ——— Logging Setup ———
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AnswerFiller")

# ——— Config from env/secrets ———
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_CX      = os.environ.get("GOOGLE_CX")
BING_API_KEY   = os.environ.get("BING_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

# ——— HTTP helper ———
def safe_request(url, headers=None, **kwargs):
    try:
        hdrs = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        resp = requests.get(url, headers=hdrs, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.debug(f"Request failed ({url}): {e}")
        return None

# ——— 1) Source‑page scrape ———
def scrape_source(link):
    if not link:
        return None
    r = safe_request(link)
    if not r:
        return None
    s = BeautifulSoup(r.text, "html.parser")
    # InterviewBit
    el = s.select_one("div.answer-text")
    if el and el.get_text(strip=True):
        return el.get_text("\n", strip=True).strip()
    # GeeksforGeeks
    cont = s.select_one("div.content")
    if cont:
        paras = cont.find_all(["p","pre"])
        text = "\n\n".join(p.get_text(strip=True) for p in paras if p.get_text(strip=True))
        if text:
            return text.strip()
    # Generic article
    art = s.find("article")
    if art and art.get_text(strip=True):
        return art.get_text("\n", strip=True).strip()
    return None

# ——— 2) Google Custom Search API ———
def google_search(q):
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return None
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key":GOOGLE_API_KEY,"cx":GOOGLE_CX,"q":q,"num":1}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["items"][0]["snippet"].strip()
    except Exception as e:
        logger.debug(f"Google API failed: {e}")
        return None

# ——— 3) Bing Web Search API ———
def bing_search(q):
    if not BING_API_KEY:
        return None
    url = "https://api.bing.microsoft.com/v7.0/search"
    headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY}
    params = {"q":q,"count":1}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        snippet = data.get("webPages",{}).get("value",[])[0].get("snippet")
        return snippet.strip() if snippet else None
    except Exception as e:
        logger.debug(f"Bing API failed: {e}")
        return None

# ——— 4) OpenAI fallback ———
def openai_answer(q):
    if not OPENAI_API_KEY:
        return ""
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
              {"role":"system","content":"You are a concise, factual assistant."},
              {"role":"user","content":f"Q: {q}\nA:"}
            ],
            max_tokens=200,
            temperature=0.2,
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.debug(f"OpenAI call failed: {e}")
        return ""

# ——— Master extractor ———
def extract_answer(link, qtext):
    # 1) Try source page
    ans = scrape_source(link)
    if ans:
        logger.info("Answer from source page")
        return ans

    # 2) Try Google Custom Search
    ans = google_search(qtext)
    if ans:
        logger.info("Answer from Google API")
        return ans

    # 3) Try Bing Search
    ans = bing_search(qtext)
    if ans:
        logger.info("Answer from Bing API")
        return ans

    # 4) OpenAI fallback
    ans = openai_answer(qtext)
    if ans:
        logger.info("Answer from OpenAI")
        return ans

    logger.warning("All methods failed; leaving blank")
    return ""

# ——— Main: fill the sheet ———
def fill_answers():
    # Auth
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds  = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
    client = gspread.authorize(creds)
    sheet  = client.open("InterviewCoach_DB").sheet1

    # Locate columns
    headers = sheet.row_values(1)
    q_col = headers.index("question")+1
    a_col = headers.index("answer")+1
    link_col = headers.index("link")+1 if "link" in headers else None

    records = sheet.get_all_records()
    for idx, row in enumerate(records, start=2):
        if row.get("answer","").strip():
            continue  # already answered

        qtext = row["question"]
        link  = row.get("link") if link_col else None

        logger.info(f"Filling row {idx}: {qtext[:50]}...")
        answer = extract_answer(link, qtext)
        if not answer:
            logger.warning(f"No answer found for row {idx}")
            continue

        try:
            sheet.update_cell(idx, a_col, answer)
            logger.info(f"Row {idx} updated")
            time.sleep(1)  # avoid rate limits
        except Exception as e:
            logger.error(f"Failed to update row {idx}: {e}")

if __name__ == "__main__":
    fill_answers()
