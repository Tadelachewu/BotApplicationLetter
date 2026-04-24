# app.py - Telegram Bot with Multilingual, SQLite Storage & Web Dashboard

import os, re, time, threading, logging, sqlite3, json, smtplib, ssl
import sys
from flask import Flask, request, jsonify
import telebot
from dotenv import load_dotenv
from pathlib import Path
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from letter_ai import generate_letter, save_letter_as_pdf
from datetime import datetime, timezone
from email.message import EmailMessage

# Load environment from this project (override any stale OS env vars)
_dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_dotenv_path, override=True)
_SMTP_TEST_MODE = "--smtp-test" in sys.argv
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or "").strip()
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEVELOPMENT").upper()
if not _SMTP_TEST_MODE and BOT_TOKEN.lower() == "your_telegram_bot_token_here":
    raise ValueError("TELEGRAM_BOT_TOKEN is still the placeholder. Update and save .env, then restart.")
if not _SMTP_TEST_MODE and (not BOT_TOKEN or (ENVIRONMENT == "PRODUCTION" and not WEBHOOK_URL)):
    raise ValueError("Required environment variables are missing")

# Basic token sanity check to avoid starting polling with an invalid token
import re as _re
_token_valid = bool(_re.match(r"^\d+:[-\w]+$", BOT_TOKEN))
if not _token_valid:
    print("⚠️ TELEGRAM_BOT_TOKEN looks invalid or missing. Bot will not start polling.")

# Initialize
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# Setup SQLite
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS letters (chat_id INTEGER, full_name TEXT, timestamp TEXT, letter TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS feedback (chat_id INTEGER, timestamp TEXT, feedback TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS sessions (
    chat_id INTEGER PRIMARY KEY,
    language TEXT,
    progress INTEGER,
    responses TEXT,
    updated_at TEXT
)''')
conn.commit()

# Session storage
user_data = {}
user_progress = {}
def load_session(chat_id):
    row = c.execute(
        "SELECT language, progress, responses FROM sessions WHERE chat_id=?",
        (chat_id,),
    ).fetchone()
    if not row:
        return None
    language, progress, responses_json = row
    try:
        responses = json.loads(responses_json) if responses_json else {}
    except Exception:
        responses = {}
    return {"language": language, "progress": int(progress), "responses": responses}


def save_session(chat_id, language, progress, responses):
    timestamp = datetime.now(timezone.utc).isoformat()
    c.execute(
        "REPLACE INTO sessions(chat_id, language, progress, responses, updated_at) VALUES (?,?,?,?,?)",
        (chat_id, language, int(progress), json.dumps(responses, ensure_ascii=False), timestamp),
    )
    conn.commit()


def delete_session(chat_id):
    c.execute("DELETE FROM sessions WHERE chat_id=?", (chat_id,))
    conn.commit()


# Logging
logging.basicConfig(level=logging.INFO, filename="bot.log", format="%(asctime)s - %(message)s")

# Languages and questions
LANGUAGES = ["English", "Amharic"]
lang_questions = {
    "English": {
        "full_name": "📝 What is your **full name**?",
        "address": "🏠 What is your **address**?",
        "phone": "📱 What is your **phone number**?",
        "email": "📧 What is your **email address**?",
        "job_title": "💼 What **job title** are you applying for?",
        "company_name": "🏢 What is the **company name**?",
        "experience": "⌛ How many years of experience and in what field?",
        "achievements": "🏆 Mention 1-2 achievements (with numbers if possible):",
        "skills": "🛠️ List your top 3-5 skills:",
        "job_platform": "🌐 Where did you find the job?",
        "company_reason": "💡 Why do you want to work for this company?"
    },
    "Amharic": {
        "full_name": "📝 ሙሉ ስምዎን ያስገቡ።",
        "address": "🏠 አድራሻዎን ያስገቡ።",
        "phone": "📱 የስልክ ቁጥርዎን ያስገቡ።",
        "email": "📧 ኢሜል አድራሻዎን ያስገቡ።",
        "job_title": "💼 ስራ መደበኛውን ርዕስ ያስገቡ።",
        "company_name": "🏢 የኩባንያው ስም ያስገቡ።",
        "experience": "⌛ ምን ዓመት ልምድ አለዎት?",
        "achievements": "🏆 አንድ ወይም ሁለት ስኬቶችን ያስግቡ።",
        "skills": "🛠️ 3-5 ክህሎትዎችን ያስገቡ።",
        "job_platform": "🌐 ስራውን ከየት ተገኘው?",
        "company_reason": "💡 ከለምነት ለምን ትጠብቃላችሁ?"
    }
}
steps = list(lang_questions["English"].keys())

# Reusable Enhancements
def schedule_clear_session(chat_id, delay=600):
    def clear():
        time.sleep(delay)
        user_data.pop(chat_id, None)
        user_progress.pop(chat_id, None)
        delete_session(chat_id)
        logging.info(f"Session cleared for {chat_id}")
    threading.Thread(target=clear).start()


def _get_smtp_config():
    host = os.getenv("SMTP_HOST") or os.getenv("EMAIL_SMTP_HOST") or "smtp.gmail.com"
    port_str = os.getenv("SMTP_PORT") or os.getenv("EMAIL_SMTP_PORT") or "465"
    try:
        port = int(port_str)
    except Exception:
        port = 465
    user = os.getenv("SMTP_USER") or os.getenv("EMAIL_USERNAME")
    password = os.getenv("SMTP_PASS") or os.getenv("EMAIL_PASSWORD")
    timeout_str = os.getenv("SMTP_TIMEOUT_SECONDS") or "20"
    try:
        timeout = float(timeout_str)
    except Exception:
        timeout = 20.0

    def _env_true(v):
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    use_ssl = None
    use_tls = None
    explicit_ssl = os.getenv("SMTP_USE_SSL")
    explicit_tls = os.getenv("SMTP_USE_TLS") or os.getenv("EMAIL_USE_TLS")
    if explicit_ssl is not None:
        use_ssl = _env_true(explicit_ssl)
    if explicit_tls is not None:
        use_tls = _env_true(explicit_tls)

    secure_env = os.getenv("SMTP_SECURE")
    if use_ssl is None and use_tls is None and secure_env is not None:
        if port == 465:
            use_ssl = _env_true(secure_env)
            use_tls = False
        else:
            use_tls = _env_true(secure_env)
            use_ssl = False

    if use_ssl is None and use_tls is None:
        use_ssl = True if port == 465 else False
        use_tls = True if port == 587 else False

    if use_ssl and use_tls:
        use_tls = False

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "use_tls": bool(use_tls),
        "use_ssl": bool(use_ssl),
        "timeout": timeout,
    }


def _send_email_message(msg: EmailMessage, cfg: dict):
    if not cfg.get("user") or not cfg.get("password"):
        raise ValueError("SMTP credentials missing")

    if cfg.get("use_ssl"):
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=cfg.get("timeout", 20)) as smtp:
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
            return True

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg.get("timeout", 20)) as smtp:
        smtp.ehlo()
        if cfg.get("use_tls"):
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)
        return True


def smtp_self_test():
    cfg = _get_smtp_config()
    if not cfg.get("user") or not cfg.get("password"):
        return False, "Missing SMTP_USER/SMTP_PASS (or EMAIL_USERNAME/EMAIL_PASSWORD)"

    try:
        if cfg.get("use_ssl"):
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=cfg.get("timeout", 20)) as smtp:
                smtp.ehlo()
                smtp.login(cfg["user"], cfg["password"])
                code, message = smtp.noop()
                return int(code) == 250, f"Connected (SSL). NOOP={code} {message.decode('utf-8', errors='ignore') if hasattr(message, 'decode') else message}"

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg.get("timeout", 20)) as smtp:
            smtp.ehlo()
            if cfg.get("use_tls"):
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            code, message = smtp.noop()
            return int(code) == 250, f"Connected. NOOP={code} {message.decode('utf-8', errors='ignore') if hasattr(message, 'decode') else message}"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Auth failed: {e}"
    except Exception as e:
        return False, str(e)


def send_user_info_via_email(chat_id, username):
    """Send Telegram user id and username to a fixed recipient via SMTP.

    Requires environment vars: EMAIL_USERNAME and EMAIL_PASSWORD. Optional:
    EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_USE_TLS
    """
    recipient = (os.getenv("ADMIN_EMAIL_RECIPIENT") or "tade2024bdugit@gmail.com").strip()

    cfg = _get_smtp_config()

    if not cfg["user"] or not cfg["password"]:
        logging.warning("Email credentials not set; skipping sending user info for %s", chat_id)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"New bot user: {username or 'unknown'} ({chat_id})"
    msg["From"] = cfg["user"]
    msg["To"] = recipient
    msg.set_content(f"Telegram user info:\n\nID: {chat_id}\nUsername: {username}\nTimestamp: {datetime.now(timezone.utc).isoformat()}")

    try:
        _send_email_message(msg, cfg)
        logging.info("Sent user info email for %s", chat_id)
        return True
    except Exception as e:
        logging.error("Failed to send user info email for %s: %s", chat_id, e)
        return False

def get_post_letter_buttons(lang):
    kb = InlineKeyboardMarkup()
    texts = {"English": ("🔄 Restart", "💬 Feedback"), "Amharic": ("🔄 ጀምር ሁልቱ", "💬 አስተያየት")}
    kb.add(InlineKeyboardButton(texts[lang][0], callback_data="restart"),
           InlineKeyboardButton(texts[lang][1], callback_data="feedback"))
    return kb


def get_retry_buttons(lang):
    kb = InlineKeyboardMarkup()
    texts = {
        "English": ("🔁 Retry", "🔄 Restart"),
        "Amharic": ("🔁 ደግመው ሞክር", "🔄 ጀምር ሁልቱ"),
    }
    kb.add(
        InlineKeyboardButton(texts[lang][0], callback_data="retry"),
        InlineKeyboardButton(texts[lang][1], callback_data="restart"),
    )
    return kb


def get_edit_buttons(lang, responses):
    kb = InlineKeyboardMarkup()
    # Show only fields that have been answered
    for step in steps:
        if step in (responses or {}):
            label = step.replace('_', ' ').title()
            kb.add(InlineKeyboardButton(f"✏️ {label}", callback_data=f"edit:{step}"))
    cancel_text = "❌ Cancel" if lang == "English" else "❌ ተወው"
    kb.add(InlineKeyboardButton(cancel_text, callback_data="edit_cancel"))
    return kb


def compute_next_progress(responses):
    responses = responses or {}
    idx = 0
    while idx < len(steps) and steps[idx] in responses and str(responses[steps[idx]]).strip():
        idx += 1
    return idx


def retry_generation(cid):
    # Prefer in-memory session, else load from DB
    if cid not in user_data or not user_data[cid].get('responses'):
        sess = load_session(cid)
        if not sess or not sess.get('responses'):
            bot.send_message(cid, "⚠️ No saved session to retry. Type /start")
            return
        user_data[cid] = {"language": sess.get("language", "English"), "responses": sess.get("responses", {})}
        user_progress[cid] = sess.get("progress", 0)

    # Mark as completed so finalize runs
    user_progress[cid] = len(steps)
    finalize_letter(cid)

# Routes
@app.route('/')
def health():
    return jsonify({"status": "healthy", "mode": ENVIRONMENT})

@app.route('/dashboard/letters')
def dashboard_letters():
    rows = c.execute("SELECT * FROM letters ORDER BY timestamp DESC").fetchall()
    html = "<h1>Saved Letters</h1><ul>"
    for chat_id, name, ts, let in rows:
        html += f"<li>{ts} – {name}:<pre>{let[:200]}...</pre></li>"
    return html

@app.route('/dashboard/feedback')
def dashboard_feedback(): 
    rows = c.execute("SELECT * FROM feedback ORDER BY timestamp DESC").fetchall()
    html = "<h1>User Feedback</h1><ul>"
    for chat, ts, fb in rows:
        html += f"<li>{ts} – chat {chat}: {fb}</li>"
    return html
#bind this https://botapplicationletter.onrender.com/webhook  on deployed server as .env
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        u = telebot.types.Update.de_json(request.get_data().decode())
        # Process updates in a background thread so the HTTP response is fast.
        try:
            threading.Thread(target=bot.process_new_updates, args=([u],), daemon=True).start()
            return '', 200
        except Exception:
            # Fallback to synchronous processing on unexpected failure
            bot.process_new_updates([u])
            return '', 200
    return 'Bad request', 400

# Handlers
@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    cid = message.chat.id
    # Always start fresh on /start: clear any persisted or in-memory session
    try:
        delete_session(cid)
    except Exception:
        logging.exception("Failed to delete session for %s on /start", cid)
    user_data.pop(cid, None)
    user_progress.pop(cid, None)

    user_data[cid] = {"language": None}
    user_progress[cid] = -1
    # send Telegram user id and username to the configured recipient
    try:
        username = None
        if getattr(message, 'from_user', None):
            username = getattr(message.from_user, 'username', None) or f"{getattr(message.from_user, 'first_name', '')} {getattr(message.from_user, 'last_name', '')}".strip()
        send_user_info_via_email(cid, username)
    except Exception:
        logging.exception("Error while attempting to send user info email for %s", cid)
    options = "\n".join([f"{i+1}. {l}" for i, l in enumerate(LANGUAGES)])
    bot.send_message(cid, f"Choose language / ቋንቋ ይምረጡ:\n{options}")

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    cid = message.chat.id
    user_data[cid] = {"language": None}
    user_progress[cid] = -1
    delete_session(cid)
    bot.send_message(cid, "🔄 Restarted. Type /start")    


@bot.message_handler(commands=['retry'])
def cmd_retry(message):
    cid = message.chat.id
    retry_generation(cid)

@bot.message_handler(commands=['feedback'])
def cmd_feedback(message):
    cid = message.chat.id
    user_data[cid]['awaiting_feedback'] = True
    bot.send_message(cid, "💬 Please type your feedback.")

@bot.message_handler(commands=['edit'])
def cmd_edit(message):
    cid = message.chat.id
    # Restore from DB if needed
    if cid not in user_data or not user_data[cid].get('responses'):
        sess = load_session(cid)
        if sess and sess.get('responses'):
            user_data[cid] = {"language": sess.get("language", "English"), "responses": sess.get("responses", {})}
            user_progress[cid] = sess.get("progress", compute_next_progress(user_data[cid]['responses']))

    if cid not in user_data or not user_data[cid].get('responses'):
        bot.send_message(cid, "⚠️ No saved data to edit. Start with /start.")
        return

    lang = user_data[cid].get('language', 'English')
    user_progress[cid] = "editing"
    bot.send_message(
        cid,
        "Select a field to edit:",
        reply_markup=get_edit_buttons(lang, user_data[cid].get('responses', {})),
    )

@bot.callback_query_handler(func=lambda call: True)
def cb_handler(call):
    cid = call.message.chat.id
    # Ensure user_data[cid] is initialized
    if cid not in user_data:
        sess = load_session(cid)
        if sess and sess.get("language"):
            user_data[cid] = {"language": sess.get("language", "English"), "responses": sess.get("responses", {})}
            user_progress[cid] = sess.get("progress", 0)
        else:
            user_data[cid] = {"language": "English", "responses": {}}
    lang = user_data[cid].get('language', 'English')
    if call.data == "restart":
        cmd_reset(call.message)
    elif call.data == "feedback":
        cmd_feedback(call.message)
    elif call.data == "retry":
        retry_generation(cid)
    elif call.data == "edit_cancel":
        user_data.setdefault(cid, {}).pop('editing_field', None)
        bot.send_message(cid, "✅ Edit cancelled.")
    elif call.data.startswith("edit:"):
        field = call.data.split(":", 1)[1]
        if field not in steps:
            bot.send_message(cid, "⚠️ Invalid field.")
            return
        user_data.setdefault(cid, {})['editing_field'] = field
        user_progress[cid] = "editing_value"
        bot.send_message(cid, f"✏️ Enter new value for `{field}`", parse_mode="Markdown")

# Message handling
@bot.message_handler(func=lambda m: True)
def msg_handler(msg):
    cid = msg.chat.id
    txt = msg.text.strip()
    state = user_progress.get(cid)

    # If bot restarted and memory is empty, restore from DB
    if state is None:
        sess = load_session(cid)
        if sess and sess.get("language") in LANGUAGES:
            user_data[cid] = {"language": sess["language"], "responses": sess.get("responses", {})}
            user_progress[cid] = sess.get("progress", -1)
            state = user_progress.get(cid)

    # feedback
    if user_data.get(cid, {}).get('awaiting_feedback'):
        timestamp = datetime.now(timezone.utc).isoformat()
        c.execute("INSERT INTO feedback VALUES (?,?,?)", (cid, timestamp, txt))
        conn.commit()
        user_data[cid]['awaiting_feedback'] = False
        bot.send_message(cid, "🙏 Thank you for your feedback!")
        return

    # language selection
    if state == -1:
        idx = int(txt) - 1 if txt.isdigit() else -1
        if 0 <= idx < len(LANGUAGES):
            lang = LANGUAGES[idx]
            user_data[cid]['language'] = lang
            user_data[cid]['responses'] = {}
            user_progress[cid] = 0
            save_session(cid, lang, user_progress[cid], user_data[cid]['responses'])
            ask_next(cid)
        else:
            bot.send_message(cid, "⚠️ Invalid choice. Please choose 1 or 2.")
        return

    # editing value entry (works for both inline edit buttons and typed-field edit)
    if user_data.get(cid, {}).get('editing_field'):
        lang = user_data[cid].get('language', 'English')
        field = user_data[cid]['editing_field']
        is_valid, err = validate_input(field, txt)
        if not is_valid:
            bot.send_message(cid, f"⚠️ {err}")
            return

        user_data[cid].setdefault('responses', {})[field] = txt
        user_data[cid].pop('editing_field', None)

        next_idx = compute_next_progress(user_data[cid]['responses'])
        user_progress[cid] = next_idx if next_idx < len(steps) else len(steps)
        save_session(cid, lang, user_progress[cid], user_data[cid]['responses'])

        if next_idx < len(steps):
            bot.send_message(cid, "✅ Updated. Continuing…")
            ask_next(cid)
        else:
            bot.send_message(
                cid,
                "✅ Updated. Tap Retry to generate again, or /edit to change more.",
                reply_markup=get_retry_buttons(lang),
            )
        return

    # editing
    if state == "editing":
        if txt not in steps:
            bot.send_message(cid, "⚠️ Invalid field. Use the buttons or type a valid field key.")
            return
        user_data[cid]['editing_field'] = txt
        user_progress[cid] = "editing_value"
        bot.send_message(cid, f"✏️ Enter new value for `{txt}`", parse_mode="Markdown")
        return

    # normal question flow
    if isinstance(state, int) and state < len(steps):
        lang = user_data[cid]['language']
        key = steps[state]
        # validate
        is_valid, err = validate_input(key, txt)
        if not is_valid:
            bot.send_message(cid, f"⚠️ {err}")
            return
        user_data[cid]['responses'][key] = txt
        user_progress[cid] += 1
        save_session(cid, lang, user_progress[cid], user_data[cid]['responses'])
        ask_next(cid)
        return

# ask_next
def ask_next(cid):
    lang = user_data[cid]['language']
    idx = user_progress[cid]
    if idx < len(steps):
        key = steps[idx]
        bot.send_message(cid, lang_questions[lang][key], parse_mode="Markdown")
    else:
        finalize_letter(cid)

# Input validation
def validate_input(step, text):
    text = text.strip()
    
    validations = {
        "full_name": (
            len(text.split()) >= 2 and not any(char.isdigit() for char in text),
            "Please enter your full name (first and last name, no numbers)"
        ),
        "address": (
            len(text) >= 5,
            "Please enter a complete address"
        ),
        "phone": (
            re.match(r"^(?:\+?251|0)?9\d{8}$", text),
            "Please enter a valid Ethiopian phone number (e.g., 0912345678 or +251912345678)"
        ),
        "email": (
            re.match(r"[^@]+@[^@]+\.[^@]+", text),
            "Please enter a valid email address (e.g., example@gmail.com)"
        ),
        "job_title": (
            len(text) >= 3 and not any(char.isdigit() for char in text),
            "Please enter a valid job title (no numbers)"
        ),
        "company_name": (
            len(text) >= 2 and not any(char.isdigit() for char in text),
            "Company name must be text only (no numbers)"
        ),
        "experience": (
            re.search(r"\d", text),
            "Please include years of experience (e.g., '2 years in programming')"
        ),
        "achievements": (
            len(text) >= 10,
            "Please mention at least one achievement clearly"
        ),
        "skills": (
            len([s.strip() for s in text.split(',')]) >= 2,
            "Please enter at least 2 skills separated by commas"
        ),
        "job_platform": (
            len(text) >= 3,
            "Please specify where you found the job"
        ),
        "company_reason": (
            len(text) >= 10,
            "Please explain why you want to join this company"
        )
    }
    
    is_valid, error_msg = validations.get(step, (True, ""))
    return is_valid, error_msg if not is_valid else ""


# finalize_letter
def finalize_letter(cid):
    lang = user_data[cid]['language']
    resp = user_data[cid]['responses']
    prompt = "\n".join(f"{k.replace('_', ' ').title()}: {v}" for k,v in resp.items())

    try:
        bot.send_chat_action(cid, 'typing')
        letter = generate_letter(prompt)
        if letter.startswith("❌"): raise Exception(letter)
        bot.send_message(cid, f"✉️ {letter}")
        pdfname = f"{resp['full_name'].replace(' ','_')}_App.pdf"
        path = save_letter_as_pdf(letter, pdfname)
        with open(path,'rb') as f:
            bot.send_document(cid, f, caption="📄 PDF")
        timestamp = datetime.now(timezone.utc).isoformat()
        # save letter
        c.execute("INSERT INTO letters VALUES(?,?,?,?)",
                  (cid, resp['full_name'], timestamp, letter))
        conn.commit()

        # Send email with letter and user info
        try:
            username = resp.get('full_name', 'unknown')
            email_body = f"A new application letter was generated.\n\nUser ID: {cid}\nUsername: {username}\nTimestamp: {timestamp}\n\nLetter:\n{letter}"
            msg = EmailMessage()
            recipient = (os.getenv("ADMIN_EMAIL_RECIPIENT") or "tade2024bdugit@gmail.com").strip()
            msg["Subject"] = f"New Application Letter: {username} ({cid})"
            cfg = _get_smtp_config()
            if cfg.get("user"):
                msg["From"] = cfg.get("user")
            msg["To"] = recipient
            msg.set_content(email_body)

            if cfg.get("user") and cfg.get("password"):
                try:
                    try:
                        with open(path, "rb") as f:
                            msg.add_attachment(
                                f.read(),
                                maintype="application",
                                subtype="pdf",
                                filename=pdfname,
                            )
                    except Exception as e:
                        logging.error("Failed attaching PDF for %s: %s", cid, e)

                    _send_email_message(msg, cfg)
                    logging.info("Sent application letter email for %s", cid)
                except Exception as e:
                    logging.error("Failed to send application letter email for %s: %s", cid, e)
            else:
                logging.warning("Email credentials not set; skipping sending application letter for %s", cid)
        except Exception as e:
            logging.error(f"Failed to send application letter email for {resp['full_name']}: {e}")

        bot.send_message(cid, "✅ Next?", reply_markup=get_post_letter_buttons(lang))
        # Success: session can be cleared
        delete_session(cid)
        schedule_clear_session(cid)
        logging.info(f"Letter saved for {resp['full_name']}")

    except Exception as e:
        bot.send_message(cid, f"⚠️ Error generating letter: {str(e)[:200]}")
        bot.send_message(
            cid,
            "✅ Your answers are saved. Tap Retry to try again, or use /edit to change something.",
            reply_markup=get_retry_buttons(lang),
        )
        logging.error(str(e))
    finally:
        # Keep state after failure; only reset on success or /reset
        user_data[cid] = {"language": lang, "responses": resp}
        user_progress[cid] = len(steps)
        save_session(cid, lang, user_progress[cid], resp)

# Bot config and start...


# === Bot Configuration ===
def configure_bot():
    if ENVIRONMENT.upper() == "PRODUCTION":
        print("⚙️ Configuring PRODUCTION (Webhook mode)")
        try:
            bot.remove_webhook()
            bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        except Exception as e:
            print(f"⚠️ Warning configuring webhook: {e}")
    else:
        print("⚙️ Configuring DEVELOPMENT (Polling mode)")
        try:
            bot.remove_webhook()
        except Exception as e:
            print(f"⚠️ Warning removing webhook (continuing): {e}")

# === Entry point ===
if __name__ == '__main__':
    if _SMTP_TEST_MODE:
        ok, message = smtp_self_test()
        print(message)
        raise SystemExit(0 if ok else 1)

    print(f"🚀 Starting bot in {ENVIRONMENT.upper()} mode")
    configure_bot()

    if ENVIRONMENT.upper() == "PRODUCTION":
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)
    else:
        if _token_valid:
            print("🤖 Polling for updates...")
            bot.infinity_polling()
        else:
            print("Exiting due to invalid TELEGRAM_BOT_TOKEN. Fix .env and restart.")
