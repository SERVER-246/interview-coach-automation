import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import re
import sys
import os
import json
import logging
import hashlib

# Configure logging
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
    """Log critical system information"""
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current directory: {os.getcwd()}")
    logger.info(f"Files in directory: {os.listdir()}")
    
    # Verify service account file
    try:
        with open('service-account.json') as f:
            data = json.load(f)
            logger.info(f"Service account loaded for: {data['client_email']}")
    except Exception as e:
        logger.error(f"Service account error: {str(e)}")

def safe_request(url):
    """Make HTTP request with error handling"""
    try:
        logger.info(f"Requesting URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        return None

def get_question_hash(question):
    """Create unique hash for question"""
    return hashlib.md5(question.lower().encode()).hexdigest()

def extract_questions(soup, selector):
    """Extract questions from HTML using CSS selector"""
    elements = soup.select(selector)
    questions = []
    for element in elements:
        question = element.get_text().strip()
        if '?' in question and len(question) > 10:
            questions.append(question)
            logger.debug(f"Found question: {question}")
    return questions

def update_database():
    try:
        logger.info("===== Starting database update =====")
        log_system_info()
        
        # Google Sheets authentication
        scope = ['https://spreadsheets.google.com/feeds', 
                 'https://www.googleapis.com/auth/drive']
        
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
            client = gspread.authorize(creds)
            sheet = client.open("InterviewCoach_DB").sheet1
            existing_data = sheet.get_all_records()
            existing_df = pd.DataFrame(existing_data)
            logger.info(f"Loaded {len(existing_data)} existing records")
            
            # Get existing question hashes
            existing_hashes = set()
            if not existing_df.empty and 'question' in existing_df.columns:
                existing_hashes = set(existing_df['question'].apply(get_question_hash))
        except Exception as e:
            logger.critical(f"Google Sheets access failed: {str(e)}")
            return False
        
        # Scrape sources (updated selectors)
        sources = [
            {
                "url": "https://www.interviewbit.com/data-science-interview-questions/",
                "selector": "h3.ib-article-title"  # Updated selector
            },
            {
                "url": "https://www.geeksforgeeks.org/python-interview-questions/",
                "selector": "h2"  # More generic selector
            },
            {
                "url": "https://www.interviewbit.com/python-interview-questions/",
                "selector": "h3.ib-article-title"  # Additional source
            }
        ]
        
        new_questions = []
        for source in sources:
            response = safe_request(source['url'])
            if not response:
                continue
                
            try:
                soup = BeautifulSoup(response.text, 'html.parser')
                questions = extract_questions(soup, source['selector'])
                logger.info(f"Found {len(questions)} questions at {source['url']}")
                new_questions.extend(questions)
                time.sleep(2)  # Be polite to servers
            except Exception as e:
                logger.error(f"Processing error: {str(e)}")
        
        # Add new questions
        added_count = 0
        if new_questions:
            for question in set(new_questions):
                q_hash = get_question_hash(question)
                
                if q_hash not in existing_hashes:
                    try:
                        # Simple answer template
                        answer = (
                            "This is an important interview question. Focus on providing a clear, "
                            "structured response that highlights your relevant skills and experience."
                        )
                        
                        sheet.append_row([
                            f"scraped-{int(time.time())}", 
                            question, 
                            answer,
                            "Tech",
                            "all",
                            "auto-generated",
                            "scraped",
                            datetime.now().strftime("%Y-%m-%d")
                        ])
                        logger.info(f"Added: {question[:50]}...")
                        added_count += 1
                        existing_hashes.add(q_hash)
                    except Exception as e:
                        logger.error(f"Failed to add question: {str(e)}")
            logger.info(f"Added {added_count} new questions")
        else:
            logger.info("No new questions found")
        
        return added_count > 0  # Return True if added any questions
        
    except Exception as e:
        logger.critical(f"Critical error in update_database: {str(e)}")
        return False

if __name__ == "__main__":
    success = update_database()
    if success:
        logger.info("===== Scraper completed successfully =====")
        sys.exit(0)
    else:
        logger.error("===== Scraper failed =====")
        sys.exit(1)
