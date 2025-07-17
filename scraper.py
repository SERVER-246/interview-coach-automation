import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import re
import hashlib
import logging
import tenacity
import sys

# ---- Configure Logging ----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraper.log')
    ]
)
logger = logging.getLogger("Scraper")

# ---- Robust API Call with Backoff ----
@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    retry=tenacity.retry_if_exception_type(requests.RequestException),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING)
)
def safe_request(url):
    """Make HTTP request with retry logic"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response

# ---- Data Sanitization ----
def sanitize_text(text):
    """Clean and normalize text"""
    if not text:
        return ""
    text = re.sub(r'[^\w\s\?\.\',!-]', '', text)
    return text.strip()[:300]

# ---- Answer Quality Control ----
def is_high_quality(answer):
    """Ensure answers meet minimum standards"""
    if not answer:
        return False
    if len(answer.split()) < 15:
        return False
    if "sorry" in answer.lower() or "don't know" in answer.lower():
        return False
    return True

# ---- Duplicate Prevention ----
def get_question_hash(question):
    """Create unique hash for question"""
    return hashlib.md5(question.lower().encode()).hexdigest()

# ---- Main Scraping Function ----
def update_database():
    """Update Q&A database with new questions"""
    try:
        logger.info("Starting database update")
        
        # Google Sheets authentication
        scope = ['https://spreadsheets.google.com/feeds', 
                 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("InterviewCoach_DB").sheet1
        existing_data = sheet.get_all_records()
        existing_df = pd.DataFrame(existing_data)
        
        # Get existing question hashes
        existing_hashes = set()
        if not existing_df.empty and 'question' in existing_df.columns:
            existing_hashes = set(existing_df['question'].apply(get_question_hash))
        
        # Scrape sources
        sources = [
            {"url": "https://www.interviewbit.com/data-science-interview-questions/", "selector": ".question-title"},
            {"url": "https://www.geeksforgeeks.org/python-interview-questions/", "selector": "article h2"},
            {"url": "https://www.indeed.com/career-advice/interviewing/common-technical-interview-questions-and-answers", "selector": "h2.css-1d5dso1"}
        ]
        
        new_questions = []
        for source in sources:
            try:
                logger.info(f"Scraping: {source['url']}")
                response = safe_request(source['url'])
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract questions
                elements = soup.select(source['selector'])
                for element in elements:
                    question = sanitize_text(element.get_text())
                    if '?' in question:
                        new_questions.append(question)
                
                logger.info(f"Found {len(elements)} potential questions")
                time.sleep(2)  # Be polite to servers
                
            except tenacity.RetryError:
                logger.error(f"Failed to scrape {source['url']} after retries")
            except Exception as e:
                logger.error(f"Error scraping {source['url']}: {str(e)}")
        
        # Process new questions
        new_data = []
        for question in set(new_questions):  # Remove duplicates
            q_hash = get_question_hash(question)
            
            if q_hash not in existing_hashes:
                # Generate simple answer (production would use AI)
                answer = (
                    "This is an important interview question. Focus on providing a clear, "
                    "structured response that highlights your relevant skills and experience. "
                    "Aim for 1-2 minutes maximum."
                )
                
                if is_high_quality(answer):
                    new_data.append({
                        "id": f"scraped-{int(time.time())}",
                        "question": question,
                        "answer": answer,
                        "industry": "Tech",
                        "experience": "all",
                        "tags": "auto-generated",
                        "source": "scraped",
                        "date_added": datetime.now().strftime("%Y-%m-%d")
                    })
                    existing_hashes.add(q_hash)
                    logger.info(f"Added new question: {question[:50]}...")
                else:
                    logger.warning(f"Rejected low-quality answer for: {question[:50]}...")
        
        # Add to Google Sheets
        if new_data:
            new_df = pd.DataFrame(new_data)
            sheet.append_rows(new_df.values.tolist())
            logger.info(f"Added {len(new_data)} new questions to database")
        else:
            logger.info("No new questions to add")
        
        return True
        
    except Exception as e:
        logger.critical(f"Database update failed: {str(e)}")
        return False

if __name__ == "__main__":
    update_database()
