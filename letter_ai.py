# letter_ai.py - Strict Guidelines Version
import os
import requests
import time
import random
import email.utils
from datetime import datetime
from fpdf import FPDF
from dotenv import load_dotenv
from pathlib import Path

from llm_providers import (
    call_provider,
    list_available_providers,
    LLMError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMAuthError,
    LLMProviderError,
)

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

    # Provider fallback chain (comma-separated). Example: gemini,groq,openai,huggingface
    order_raw = (os.getenv("LLM_PROVIDER_ORDER") or "gemini").strip()
    provider_order = [p.strip().lower() for p in order_raw.split(",") if p.strip()]
    # If user misconfigured it, fall back to a safe default
    if not provider_order:
        provider_order = ["gemini"]

    available = set(list_available_providers())
    provider_order = [p for p in provider_order if p in available]
    if not provider_order:
        provider_order = ["gemini"]

    last_error = None
    for provider in provider_order:
        try:
            generated_text = call_provider(provider, prompt)

            # Validate the output meets guidelines
            if "Dear Hiring Manager" not in generated_text or "Sincerely," not in generated_text:
                last_error = "❌ Strict Format Error: Generated letter doesn't follow required format"
                continue

            return generated_text

        except LLMQuotaError as e:
            last_error = f"❌ {provider.title()} Quota Exhausted: {str(e)[:220]}"
            continue
        except LLMRateLimitError as e:
            last_error = f"❌ {provider.title()} Rate Limited: {str(e)[:220]}"
            continue
        except LLMAuthError as e:
            last_error = f"❌ {provider.title()} Auth Error: {str(e)[:220]}"
            continue
        except LLMProviderError as e:
            last_error = f"❌ {provider.title()} Provider Error: {str(e)[:220]}"
            continue
        except LLMError as e:
            last_error = f"❌ {provider.title()} Error: {str(e)[:220]}"
            continue
        except requests.exceptions.RequestException as e:
            last_error = f"❌ {provider.title()} Network Error: {str(e)[:220]}"
            continue

    return last_error or "❌ No LLM providers succeeded. Configure LLM_PROVIDER_ORDER and API keys."

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