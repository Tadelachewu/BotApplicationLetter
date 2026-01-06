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

    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "8"))
    backoff_cap = float(os.getenv("GEMINI_BACKOFF_CAP_SECONDS", "120"))
    request_timeout = float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "25"))

    def _parse_retry_after(value: str):
        """Return seconds to wait from a Retry-After header (int/float seconds or HTTP date)."""
        if not value:
            return None
        raw = str(value).strip()
        # First: numeric seconds
        try:
            secs = float(raw)
            if secs >= 0:
                return secs
        except Exception:
            pass

        # Second: HTTP-date
        try:
            dt = email.utils.parsedate_to_datetime(raw)
            if dt is None:
                return None
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.utcnow()
            delta = (dt - now).total_seconds()
            return max(0.0, float(delta))
        except Exception:
            return None

    def _full_jitter_backoff(attempt_index: int):
        """AWS-style full jitter backoff: random(0, min(cap, base*2^n))."""
        base = 1.0
        ceiling = min(backoff_cap, base * (2.0 ** attempt_index))
        return random.uniform(0.0, max(0.0, ceiling))

    def _classify_quota_vs_rate_limit(status_code: int, payload: dict):
        """Best-effort classification for debugging: returns ('quota'|'rate_limit'|'unknown_429'|'other', details)."""
        err = (payload or {}).get("error") or {}
        status = str(err.get("status") or "").upper()
        message = str(err.get("message") or payload.get("message") or "")
        message_l = message.lower()

        # Gemini/Google APIs commonly use RESOURCE_EXHAUSTED for quotas.
        # Rate limiting is also often 429, but messages mention 'rate', 'per minute', 'rpm', etc.
        quota_markers = [
            "quota",
            "exceed",
            "exhaust",
            "insufficient quota",
            "billing",
            "payment",
            "resource has been exhausted",
        ]
        rate_markers = [
            "rate",
            "rate limit",
            "too many requests",
            "per minute",
            "per second",
            "rpm",
            "rps",
            "requests per",
        ]

        if status in {"RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"}:
            return "quota", (status, message)

        if status_code in {429, 403}:
            if any(m in message_l for m in quota_markers) and not any(m in message_l for m in rate_markers):
                return "quota", (status, message)
            if any(m in message_l for m in rate_markers):
                return "rate_limit", (status, message)
            # Ambiguous: keep it separate so it's easier to debug
            if status_code == 429:
                return "unknown_429", (status, message)

        return "other", (status, message)

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=request_timeout,
            )

            if response.status_code in (429, 403):
                # Best-effort extraction of provider payload (keep it short)
                payload = {}
                try:
                    payload = response.json() if response.content else {}
                except Exception:
                    payload = {}

                classification, (provider_status, provider_msg) = _classify_quota_vs_rate_limit(
                    response.status_code, payload
                )

                # Quota/billing won't improve with retries; fail fast with a distinct message.
                if classification == "quota":
                    return (
                        "❌ Gemini Quota Exhausted: Your API key/project appears out of quota (or billing is required). "
                        "Increase quota/enable billing or wait for quota reset."
                        + (f" Provider status: {provider_status}." if provider_status else "")
                        + (f" Provider said: {provider_msg[:160]}" if provider_msg else "")
                    )

                # Not a quota issue: only retry on rate limiting / ambiguous 429.
                if response.status_code == 403 and classification != "rate_limit":
                    # 403 is often auth/config; don't hammer retries.
                    return (
                        "❌ Gemini Error: 403 Forbidden (not retrying). "
                        "This can mean invalid key, missing permissions, disabled API, or billing/quota restrictions."
                        + (f" Provider status: {provider_status}." if provider_status else "")
                        + (f" Provider said: {provider_msg[:160]}" if provider_msg else "")
                    )

                # Rate limit or unknown_429: proceed with backoff retries.
                if response.status_code == 429:
                    error_prefix = "❌ Gemini Rate Limited" if classification == "rate_limit" else "❌ Gemini 429 (Unclassified)"

                    if attempt == max_retries:
                        return (
                            f"{error_prefix}: 429 Too Many Requests after {max_retries} attempts. "
                            "Wait a bit and tap Retry. If it happens frequently, reduce request frequency or increase limits/quota."
                            + (f" Provider status: {provider_status}." if provider_status else "")
                            + (f" Provider said: {provider_msg[:160]}" if provider_msg else "")
                        )

                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    if retry_after is not None:
                        wait = min(backoff_cap, retry_after)
                    else:
                        wait = _full_jitter_backoff(attempt)

                    print(
                        f"429 from Gemini ({classification}). Retrying after {wait:.1f}s "
                        f"(attempt {attempt}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue

                # Any other 4xx here: fall through to raise_for_status() below.

            response.raise_for_status()

            data = response.json() if response.content else {}
            candidates = (data or {}).get("candidates") or []
            generated_text = ""
            if candidates:
                content = candidates[0].get("content") or {}
                parts = content.get("parts") or []
                if parts and isinstance(parts[0], dict):
                    generated_text = (parts[0].get("text") or "").strip()
            if not generated_text:
                return "❌ Gemini Error: Empty/invalid response from API"

            # Validate the output meets guidelines
            if "Dear Hiring Manager" not in generated_text or "Sincerely," not in generated_text:
                return "❌ Strict Format Error: Generated letter doesn't follow required format"

            return generated_text

        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                return f"❌ Gemini Error: {str(e)}"
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