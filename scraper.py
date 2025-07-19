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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        return None

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
            logger.info(f"Loaded {len(existing_data)} existing records")
        except Exception as e:
            logger.critical(f"Google Sheets access failed: {str(e)}")
            return False
        
        # Scrape sources
        sources = [
            {"url": "https://www.interviewbit.com/data-science-interview-questions/", "selector": ".question-title"},
            {"url": "https://www.geeksforgeeks.org/python-interview-questions/", "selector": "article h2"}
        ]
        
        new_questions = []
        for source in sources:
            response = safe_request(source['url'])
            if not response:
                continue
                
            try:
                soup = BeautifulSoup(response.text, 'html.parser')
                elements = soup.select(source['selector'])
                logger.info(f"Found {len(elements)} elements at {source['url']}")
                
                for element in elements:
                    question = element.get_text().strip()
                    if '?' in question:
                        new_questions.append(question)
                
                time.sleep(2)  # Be polite to servers
            except Exception as e:
                logger.error(f"Processing error: {str(e)}")
        
        # Add new questions
        if new_questions:
            logger.info(f"Adding {len(set(new_questions))} new questions")
            for question in set(new_questions):
                try:
                    # Simple answer template
                    answer = (
                        "This is an important interview question. Focus on providing a clear, "
                        "structured response that highlights your relevant skills and experience."
                    )
                    
                    sheet.append_row([f"scraped-{int(time.time())}", 
                                     question, 
                                     answer,
                                     "Tech",
                                     "all",
                                     "auto-generated",
                                     "scraped",
                                     datetime.now().strftime("%Y-%m-%d")])
                    logger.info(f"Added: {question[:50]}...")
                except Exception as e:
                    logger.error(f"Failed to add question: {str(e)}")
        else:
            logger.info("No new questions found")
        
        return True
        
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
