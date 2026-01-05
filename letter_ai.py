# letter_ai.py - Strict Guidelines Version
import os
import requests
import time
import random
from datetime import datetime
from fpdf import FPDF
from dotenv import load_dotenv
from pathlib import Path

# Load .env values from this project and override any stale OS env vars
_dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_dotenv_path, override=True)

class JobLetterPDF(FPDF):
    """Professional PDF generator for job application letters"""
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(25, 15, 25)  # Left, Top, Right margins
        self.set_font("Arial", size=12)
        
    def add_letter_content(self, content):
        """Add properly formatted letter content"""
        for line in content.split('\n'):
            clean_line = line.strip()
            if not clean_line:
                self.ln(6)  # Space between paragraphs
                continue
            
            # Handle encoding for Ethiopian characters if needed
            try:
                encoded_line = clean_line.encode('latin-1', 'replace').decode('latin-1')
                self.multi_cell(0, 8, encoded_line)
                self.ln(5)  # Slight space between lines
            except:
                self.multi_cell(0, 8, clean_line[:100])  # Fallback for problematic lines
                self.ln(5)

def generate_letter(user_input):
    """
    Generate a job application letter that strictly follows guidelines
    Args:
        user_input: Raw user data string
    Returns:
        str: Perfectly formatted letter or error message
    """
    headers = {"Content-Type": "application/json"}
    today = datetime.today().strftime("%B %d, %Y")
    
    # STRICT PROMPT (as per guidelines)
    prompt = f"""Generate a job application letter using EXACTLY these guidelines:

USER PROVIDED DETAILS:
{user_input}

REQUIRED FORMAT:
Name: [Full Name]
Address:[Street Address] (if provided)
City: [City] (if provided)
Phone: [Phone] 
Email: [Email]
Date: {today}

Company: [Company Name] (if provided)
Company Address:[Company Address] (only if provided)

Dear Hiring Manager,

[1st Paragraph: Position and where found. Concise introduction.]

[2nd Paragraph: Relevant experience with specific achievements.]

[3rd Paragraph: Skills matching job requirements.]

[4th Paragraph: Why interested in this company.]

Sincerely,
[Full Name]

STRICT RULES:
1. NEVER use placeholders like [Date] or [Company Address]
2. ONLY include information actually provided
3. Omit any missing sections completely
4. Use professional business letter format
5. Maintain 3-4 concise paragraphs
6. Today's date must be: {today}
7. Never add section headers
8. make it attractive and eye-catchying
9. make it exceptionally professional
10. follow formats strictly
11. Always end with "Sincerely," followed by full name"""

    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return "❌ Strict Format Error: GEMINI_API_KEY is not set in the environment"
    if api_key.lower() in {"your_gemini_api_key_here", "your_api_key_here"}:
        return "❌ Strict Format Error: GEMINI_API_KEY is still a placeholder. Update and save .env"

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        f"?key={api_key}"
    )

    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "5"))
    backoff_cap = int(os.getenv("GEMINI_BACKOFF_CAP_SECONDS", "60"))

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=20,
            )

            if response.status_code == 429:
                if attempt == max_retries:
                    return (
                        f"❌ Strict Format Error: 429 Too Many Requests after {max_retries} attempts. "
                        "This usually means your API key hit a rate/quota limit; wait a bit or increase quota."
                    )

                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = min(backoff_cap, int(retry_after))
                else:
                    # Jittered exponential backoff
                    wait = min(backoff_cap, (2 ** attempt) + random.uniform(0.0, 1.0))

                print(f"429 from Gemini. Retrying after {wait:.1f}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
                continue

            response.raise_for_status()

            generated_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]

            # Validate the output meets guidelines
            if "Dear Hiring Manager" not in generated_text or "Sincerely," not in generated_text:
                return "❌ Strict Format Error: Generated letter doesn't follow required format"

            return generated_text

        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                return f"❌ Strict Format Error: {str(e)}"
            # wait briefly before retrying on transient network errors
            time.sleep(min(backoff_cap, 2 ** attempt))
            continue

def save_letter_as_pdf(letter_text, filename="Job_Application.pdf"):
    """
    Create PDF that perfectly preserves letter formatting
    Args:
        letter_text: Pre-validated letter text
        filename: Output filename
    Returns:
        str: Path to generated PDF
    Raises:
        Exception: If formatting would be compromised
    """
    try:
        # Pre-check letter structure
        if not all(x in letter_text for x in ["Dear Hiring Manager", "Sincerely,"]):
            raise ValueError("Invalid letter structure - missing required components")
        
        pdf = JobLetterPDF()
        pdf.add_page()
        pdf.add_letter_content(letter_text)
        
        os.makedirs("letters", exist_ok=True)
        pdf_path = os.path.join("letters", filename)
        pdf.output(pdf_path)
        
        return pdf_path
        
    except Exception as e:
        raise Exception(f"PDF Generation Aborted: {str(e)}")