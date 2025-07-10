import os
import requests
from dotenv import load_dotenv
from datetime import datetime
from fpdf import FPDF

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

def generate_letter(user_input):
    headers = {"Content-Type": "application/json"}
    today = datetime.today().strftime("%B %d, %Y")

    prompt = f"""
You are a professional HR assistant.

Write a clean, ready-to-send job application letter using the following applicant details:

{user_input}

Guidelines:
- Do NOT include any placeholder text like [Date] or [Company Address, if unknown].
- Use today's date: {today}.
- Only include details actually provided. If company address or similar is missing, omit that line.
- Format as a polished application letter — no section headers like "Contact Info", "Subject Line", or "Greeting".
- Begin with sender's address, phone, email, and the current date, followed by the company's name and greeting.
- Use professional tone and paragraph structure covering: interest in job, relevant skills/experience, motivation, and closing.
- End with “Sincerely,” followed by the applicant’s full name.

Make sure this looks exactly like a job letter ready to submit.
"""

    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(GEMINI_URL, headers=headers, json=data)
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"❌ Error generating letter:\n{e}"


def save_letter_as_pdf(letter_text, filename="Application_Letter.pdf"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=12)

    for line in letter_text.split('\n'):
        pdf.multi_cell(0, 10, line.encode('latin-1', 'replace').decode('latin-1'))

    os.makedirs("temp", exist_ok=True)
    path = os.path.join("temp", filename)
    pdf.output(path)
    return path
