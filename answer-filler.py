import os
import sys
import json
import time
import logging
import hashlib
from datetime import datetime

import requests
import pandas as pd
import gspread
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials

# ——— Logging Setup ———
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('answer-filler.log')
    ]
)
logger = logging.getLogger("AnswerFiller")

# ——— System Info ———
def log_system_info():
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current directory: {os.getcwd()}")
    logger.info(f"Files in directory: {os.listdir()}")

# ——— Hashing Utility ———
def get_question_hash(q: str) -> str:
    return hashlib.md5(q.lower().encode()).hexdigest()

# ——— OpenAI Completion ———
def query_openai(prompt: str) -> str:
    try:
        import openai
        openai.api_key = os.environ.get("OPENAI_API_KEY")
        if not openai.api_key:
            raise ValueError("OPENAI_API_KEY not set.")
        logger.info("Querying OpenAI...")
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Answer concisely and professionally."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI failed: {e}")
        return ""

# ——— SerpAPI Fallback ———
def query_serpapi(question: str) -> str:
    try:
        api_key = os.environ.get("SERPAPI_KEY")
        if not api_key:
            raise ValueError("SERPAPI_KEY not set.")

        logger.info("Querying SerpAPI...")
        params = {
            "q": question,
            "api_key": api_key,
            "engine": "google",
            "num": 3
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Snippet logic
        for result in data.get("organic_results", []):
            snippet = result.get("snippet")
            if snippet:
                return snippet.strip()
    except Exception as e:
        logger.error(f"SerpAPI failed: {e}")
    return ""

# ——— Answer Filler ———
def get_answer(question: str) -> str:
    # 1. OpenAI
    answer = query_openai(question)
    if answer:
        return answer
    # 2. SerpAPI fallback
    return query_serpapi(question)

# ——— Google Sheets Setup ———
def update_sheet_with_answers():
    logger.info("===== Starting Answer Filler =====")
    log_system_info()

    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("InterviewCoach_DB").sheet1
        rows = sheet.get_all_records()
        df = pd.DataFrame(rows)
        logger.info(f"Fetched {len(df)} rows from sheet.")
    except Exception as e:
        logger.critical(f"Sheets access failed: {e}")
        return False

    filled = 0
    for i, row in df.iterrows():
        answer = row.get("answer", "").strip()
        question = row.get("question", "").strip()
        if not answer and question:
            logger.info(f"Filling missing answer for row {i+2}: {question[:60]}...")
            new_answer = get_answer(question)
            if new_answer:
                try:
                    sheet.update_cell(i + 2, 3, new_answer)  # Row index + header + col (3 = 'answer')
                    filled += 1
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Failed to update sheet for row {i+2}: {e}")

    logger.info(f"Answers filled: {filled}")
    return True

if __name__ == "__main__":
    try:
        update_sheet_with_answers()
        logger.info("===== Answer filler completed successfully =====")
    except Exception as e:
        logger.critical(f"Uncaught exception: {e}")
        sys.exit(1)
