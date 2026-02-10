FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 1️⃣ Install system dependencies (ADD zstd)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gcc \
    build-essential \
    libffi-dev \
    zstd \
 && rm -rf /var/lib/apt/lists/*

# 2️⃣ Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/letters

# 🔥 Pull Llama 3
RUN ollama pull llama3

EXPOSE 5000
EXPOSE 11434

CMD ollama serve & python bot.py
