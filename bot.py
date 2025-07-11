# app.py - Telegram Bot with Multilingual, SQLite Storage & Web Dashboard

import os, re, time, threading, logging, sqlite3
from flask import Flask, request, jsonify
import telebot
from dotenv import load_dotenv
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from letter_ai import generate_letter, save_letter_as_pdf
from datetime import datetime, timezone

# Load environment
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEVELOPMENT").upper()
if not BOT_TOKEN or (ENVIRONMENT == "PRODUCTION" and not WEBHOOK_URL):
    raise ValueError("Required environment variables are missing")

# Initialize
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# Setup SQLite
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS letters (chat_id INTEGER, full_name TEXT, timestamp TEXT, letter TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS feedback (chat_id INTEGER, timestamp TEXT, feedback TEXT)''')
conn.commit()

# Session storage
user_data = {}
user_progress = {}

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
        logging.info(f"Session cleared for {chat_id}")
    threading.Thread(target=clear).start()

def get_post_letter_buttons(lang):
    kb = InlineKeyboardMarkup()
    texts = {"English": ("🔄 Restart", "💬 Feedback"), "Amharic": ("🔄 ጀምር ሁልቱ", "💬 አስተያየት")}
    kb.add(InlineKeyboardButton(texts[lang][0], callback_data="restart"),
           InlineKeyboardButton(texts[lang][1], callback_data="feedback"))
    return kb

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

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        u = telebot.types.Update.de_json(request.get_data().decode())
        bot.process_new_updates([u])
        return '', 200
    return 'Bad request', 400

# Handlers
@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    cid = message.chat.id
    user_data[cid] = {"language": None}
    user_progress[cid] = -1
    options = "\n".join([f"{i+1}. {l}" for i, l in enumerate(LANGUAGES)])
    bot.send_message(cid, f"Choose language / ቋንቋ ይምረጡ:\n{options}")

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    cid = message.chat.id
    user_data[cid] = {"language": None}
    user_progress[cid] = -1
    bot.send_message(cid, "🔄 Restarted. Type /start")    

@bot.message_handler(commands=['feedback'])
def cmd_feedback(message):
    cid = message.chat.id
    user_data[cid]['awaiting_feedback'] = True
    bot.send_message(cid, "💬 Please type your feedback.")

@bot.message_handler(commands=['edit'])
def cmd_edit(message):
    cid = message.chat.id
    if cid not in user_data or not user_data[cid].get('responses'):
        bot.send_message(cid, "⚠️ No data to edit. Start with /start.")
        return
    user_progress[cid] = "editing"
    options = "\n".join(f"- `{s}`" for s in steps)
    bot.send_message(cid, f"Select field to edit:\n{options}", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def cb_handler(call):
    cid = call.message.chat.id
    lang = user_data[cid].get('language', 'English')
    if call.data == "restart":
        cmd_reset(call.message)
    elif call.data == "feedback":
        cmd_feedback(call.message)

# Message handling
@bot.message_handler(func=lambda m: True)
def msg_handler(msg):
    cid = msg.chat.id
    txt = msg.text.strip()
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
            ask_next(cid)
        else:
            bot.send_message(cid, "⚠️ Invalid choice. Please choose 1 or 2.")
        return

    # editing
    if state == "editing":
        if txt not in steps:
            bot.send_message(cid, "⚠️ Invalid field.")
            return
        user_progress[cid] = steps.index(txt)
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

        bot.send_message(cid, "✅ Next?", reply_markup=get_post_letter_buttons(lang))
        schedule_clear_session(cid)
        logging.info(f"Letter saved for {resp['full_name']}")

    except Exception as e:
        bot.send_message(cid, f"⚠️ Error generating letter: {str(e)[:200]}")
        logging.error(str(e))
    finally:
        user_data[cid] = {"language": lang, "responses": {}}
        user_progress[cid] = 0

# Bot config and start...


# === Bot Configuration ===
def configure_bot():
    if ENVIRONMENT.upper() == "PRODUCTION":
        print("⚙️ Configuring PRODUCTION (Webhook mode)")
        bot.remove_webhook()
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    else:
        print("⚙️ Configuring DEVELOPMENT (Polling mode)")
        bot.remove_webhook()

# === Entry point ===
if __name__ == '__main__':
    print(f"🚀 Starting bot in {ENVIRONMENT.upper()} mode")
    configure_bot()

    if ENVIRONMENT.upper() == "PRODUCTION":
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)
    else:
        print("🤖 Polling for updates...")
        bot.infinity_polling()
