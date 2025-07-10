import os
import telebot
from dotenv import load_dotenv
import re
from letter_ai import generate_letter, save_letter_as_pdf

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

user_data = {}
user_progress = {}

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
    "achievements": "🏆 Mention 1–2 achievements (with numbers if possible):",
    "skills": "🛠️ List your top 3–5 skills:",
    "job_platform": "🌐 Where did you find the job (e.g., LinkedIn, Effoysira)?",
    "company_reason": "💡 Why do you want to work for this company?"
}

@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_progress[chat_id] = 0
    user_data[chat_id] = {}
    bot.send_message(chat_id, "👋 Welcome! I’ll help you generate your job application letter.\nLet's begin step-by-step.")
    ask_next(chat_id)

@bot.message_handler(commands=['reset'])
def reset(message):
    chat_id = message.chat.id
    user_progress[chat_id] = 0
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🔄 Session reset. Type /start to begin again.")

def ask_next(chat_id):
    step = user_progress.get(chat_id, 0)
    if step < len(steps):
        key = steps[step]
        bot.send_message(chat_id, questions[key], parse_mode="Markdown")
    else:
        finalize_letter(chat_id)





def validate_input(step, text):
    text = text.strip()

    if step == "full_name":
        if len(text.split()) < 2:
            return False, "Please enter your full name (first and last name)."
        if any(char.isdigit() for char in text):
            return False, "Full name should not contain numbers."

    elif step == "address":
        if len(text) < 5:
            return False, "Please enter a complete address."

    elif step == "phone":
        if not re.match(r"^(?:\+?251|0)?9\d{8}$", text):
            return False, "Please enter a valid Ethiopian phone number (e.g., 0912345678 or +251912345678)."

    elif step == "email":
        if not re.match(r"[^@]+@[^@]+\.[^@]+", text):
            return False, "Please enter a valid email address (e.g., example@gmail.com)."

    elif step == "job_title":
        if len(text) < 3:
            return False, "Please enter a valid job title."
        if any(char.isdigit() for char in text):
            return False, "Job title should not contain numbers."

    elif step == "company_name":
        if len(text) < 2 or any(char.isdigit() for char in text):
            return False, "Company name must be text only (no numbers)."

    elif step == "experience":
        if not re.search(r"\d", text):
            return False, "Please include the number of years in your experience (e.g., '2 years in programming')."

    elif step == "achievements":
        if len(text) < 10:
            return False, "Please mention at least one achievement clearly."

    elif step == "skills":
        skills = [s.strip() for s in text.split(',')]
        if len(skills) < 2:
            return False, "Please enter at least 2 skills separated by commas (e.g., Python, React)."

    elif step == "job_platform":
        if len(text) < 3:
            return False, "Please specify the platform where you found the job."

    elif step == "company_reason":
        if len(text) < 10:
            return False, "Please explain briefly why you want to join this company."

    return True, ""



@bot.message_handler(func=lambda m: True)
def handle_response(message):
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
        return  # Ask again for the same step

    user_data[chat_id][key] = text
    user_progress[chat_id] += 1
    ask_next(chat_id)


def finalize_letter(chat_id):
    inputs = user_data[chat_id]
    prompt = (
        f"Name: {inputs['full_name']}\n"
        f"Address: {inputs['address']}\n"
        f"Phone: {inputs['phone']}\n"
        f"Email: {inputs['email']}\n"
        f"Job Title: {inputs['job_title']}\n"
        f"Company: {inputs['company_name']}\n"
        f"Experience: {inputs['experience']}\n"
        f"Achievements: {inputs['achievements']}\n"
        f"Skills: {inputs['skills']}\n"
        f"Job Platform: {inputs['job_platform']}\n"
        f"Why this company: {inputs['company_reason']}"
    )

    bot.send_chat_action(chat_id, 'typing')
    letter_text = generate_letter(prompt)
    bot.send_message(chat_id, "📄 Here's your generated letter:\n\n" + letter_text)

    pdf_path = save_letter_as_pdf(letter_text, f"{inputs['full_name'].replace(' ', '_')}_Application.pdf")
    with open(pdf_path, "rb") as pdf_file:
        bot.send_document(chat_id, pdf_file)

    # Reset
    user_data[chat_id] = {}
    user_progress[chat_id] = 0

if __name__ == "__main__":
    print("🚀 Bot is running...")
    bot.polling()
