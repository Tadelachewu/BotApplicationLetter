# app.py - Dual Mode Telegram Bot (Webhook & Polling)
import os
import re
from flask import Flask, request, jsonify
import telebot
from dotenv import load_dotenv
from letter_ai import generate_letter, save_letter_as_pdf

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ENVIRONMENT = os.getenv("ENVIRONMENT", "DEVELOPMENT").upper()

# Validate configuration
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is required")
if ENVIRONMENT == "PRODUCTION" and not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL is required in production")

# Initialize Flask and Bot
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# User session management
user_data = {}
user_progress = {}

# Conversation flow
steps = [
    "full_name", "address", "phone", "email", "job_title", "company_name",
    "experience", "achievements", "skills", "job_platform", "company_reason"
]

questions = {
    "full_name": "📝 What is your **full name**?",
    "address": "🏠 What is your **address**?",
    "phone": "📱 What is your **phone number**?",
    "email": "📧 What is your **email address**?",
    "job_title": "💼 What **job title** are you applying for?",
    "company_name": "🏢 What is the **company name**?",
    "experience": "⌛ How many years of experience and in what field?",
    "achievements": "🏆 Mention 1-2 achievements (with numbers if possible):",
    "skills": "🛠️ List your top 3-5 skills:",
    "job_platform": "🌐 Where did you find the job (e.g., LinkedIn, Effoysira)?",
    "company_reason": "💡 Why do you want to work for this company?"
}

# Webhook routes
@app.route('/')
def health_check():
    return jsonify({"status": "healthy", "mode": ENVIRONMENT})

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Bad request', 400

# Bot command handlers
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    user_progress[chat_id] = 0
    user_data[chat_id] = {}
    bot.send_message(
        chat_id,
        "👋 Welcome! I'll help you generate a job application letter.\n\n"
        "Type /start to begin or /reset at any time to start over."
    )
    ask_next(chat_id)

@bot.message_handler(commands=['reset'])
def reset_conversation(message):
    chat_id = message.chat.id
    user_progress[chat_id] = 0
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🔄 Conversation reset. Type /start to begin.")

def ask_next(chat_id):
    step = user_progress.get(chat_id, 0)
    if step < len(steps):
        key = steps[step]
        bot.send_message(chat_id, questions[key], parse_mode="Markdown")
    else:
        finalize_letter(chat_id)

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

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    chat_id = message.chat.id
    
    if chat_id not in user_progress:
        bot.send_message(chat_id, "❗ Please type /start to begin.")
        return

    step_index = user_progress[chat_id]
    if step_index >= len(steps):
        return

    key = steps[step_index]
    text = message.text.strip()

    is_valid, error_msg = validate_input(key, text)
    if not is_valid:
        bot.send_message(chat_id, f"⚠️ {error_msg}")
        return

    user_data[chat_id][key] = text
    user_progress[chat_id] += 1
    ask_next(chat_id)

def finalize_letter(chat_id):
    inputs = user_data[chat_id]
    
    # Format the prompt more clearly
    prompt = "\n".join([
        f"Name: {inputs.get('full_name', '')}",
        f"Address: {inputs.get('address', '')}",
        f"Phone: {inputs.get('phone', '')}",
        f"Email: {inputs.get('email', '')}",
        f"Applying for: {inputs.get('job_title', '')} at {inputs.get('company_name', '')}",
        f"Experience: {inputs.get('experience', '')}",
        f"Achievements: {inputs.get('achievements', '')}",
        f"Skills: {inputs.get('skills', '')}",
        f"Found on: {inputs.get('job_platform', '')}",
        f"Reason for applying: {inputs.get('company_reason', '')}"
    ])
    
    try:
        bot.send_chat_action(chat_id, 'typing')
        letter_text = generate_letter(prompt)
        
        if letter_text.startswith("❌ Error"):
            raise Exception(letter_text)
            
        # Send text version first
        bot.send_message(chat_id, f"✉️ Here's your application letter:\n\n{letter_text}")
        
        # Then send PDF
        pdf_filename = f"{inputs['full_name'].replace(' ', '_')}_Application.pdf"
        pdf_path = save_letter_as_pdf(letter_text, pdf_filename)
        
        with open(pdf_path, 'rb') as pdf_file:
            bot.send_document(chat_id, pdf_file, caption="📄 PDF Version")
            
    except Exception as e:
        bot.send_message(
            chat_id,
            "⚠️ Sorry, we encountered an error generating your letter.\n"
            f"Technical details: {str(e)[:200]}\n\n"
            "Please try again or contact support."
        )
    finally:
        # Reset conversation
        user_data[chat_id] = {}
        user_progress[chat_id] = 0

def configure_bot():
    """Configure the bot for the current environment"""
    if ENVIRONMENT == "PRODUCTION":
        print("⚙️ Configuring PRODUCTION environment (webhook)")
        bot.remove_webhook()
        bot.set_webhook(
            url=f"{WEBHOOK_URL}/webhook",
            # certificate=open('server.crt', 'r')  # Uncomment if using SSL
        )
    else:
        print("⚙️ Configuring DEVELOPMENT environment (polling)")
        bot.remove_webhook()

if __name__ == '__main__':
    print(f"🚀 Starting bot in {ENVIRONMENT} mode")
    configure_bot()
    
    if ENVIRONMENT == "PRODUCTION":
        app.run(
            host="0.0.0.0",
            port=int(os.getenv("PORT", 5000)),
            # ssl_context=('server.crt', 'server.key')  # For HTTPS
        )
    else:
        print("🤖 Bot is now polling for messages...")
        bot.infinity_polling()