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
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# Use an explicit entrypoint script (POSIX) to avoid /bin/sh parsing issues
CMD ["/usr/local/bin/start.sh"]
