import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from transformers import pipeline
import time

# Initialize QA Generator - USE UPDATED MODEL
qa_generator = pipeline('text2text-generation', 
                       model='mrm8488/t5-base-finetuned-answer-questions')  # Updated model

sources = [
    {"url": "https://www.interviewbit.com/data-science-interview-questions/", "selector": ".question-title"},
    {"url": "https://www.geeksforgeeks.org/python-interview-questions/", "selector": "article h2"}
]

def scrape_questions():
    all_questions = []
    for source in sources:
        try:
            res = requests.get(source['url'], timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            questions = [q.text.strip() for q in soup.select(source['selector']) if '?' in q.text]
            all_questions.extend(questions)
        except Exception as e:
            print(f"Scrape error: {str(e)}")
            continue
    return list(set(all_questions))

def generate_answer(question):
    prompt = f"Generate concise interview answer under 75 words: {question}"
    try:
        return qa_generator(prompt, max_length=100)[0]['generated_text']
    except Exception as e:
        print(f"Generation error: {str(e)}")
        return "Answer not available"

def update_database():
    # Google Sheets auth
    scope = ['https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('service-account.json', scope)
    client = gspread.authorize(creds)
    sheet = client.open("InterviewCoach_DB").sheet1
    existing_data = sheet.get_all_records()
    existing = pd.DataFrame(existing_data)
    
    new_questions = scrape_questions()
    new_data = []
    
    for q in new_questions:
        if q not in existing['question'].values:
            answer = generate_answer(q)
            new_data.append({
                'question': q,
                'answer': answer,
                'industry': 'Tech',
                'experience': 'all',
                'tags': 'auto-generated',
                'source': 'scraped',
                'date_added': pd.Timestamp.now().strftime('%Y-%m-%d')
            })
            time.sleep(2)  # Avoid rate limits
    
    if new_data:
        new_df = pd.DataFrame(new_data)
        sheet.append_rows(new_df.values.tolist())
        print(f"Added {len(new_data)} new questions")

if __name__ == "__main__":
    update_database()
