FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gcc \
    build-essential \
    libffi-dev \
    zstd \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/letters

EXPOSE 5000
EXPOSE 11434

# Start Ollama, pull model at runtime (from $OLLAMA_MODEL), then start bot
# If OLLAMA_MODEL is set the container will attempt to pull that model at startup.
CMD if [ -n "$OLLAMA_MODEL" ]; then echo "Pulling Ollama model: $OLLAMA_MODEL" && ollama pull "$OLLAMA_MODEL" || true; fi \
    && echo "Starting Ollama server" && ollama serve & \
    && echo "Waiting for Ollama to become healthy" \
    && for i in $(seq 1 60); do \
    if curl -sS --fail http://localhost:11434/api/info >/dev/null 2>&1; then \
    echo "Ollama is healthy"; break; \
    fi; \
    echo "waiting... ($i)"; sleep 5; \
    done \
    && echo "Starting bot" \
    && python bot.py
