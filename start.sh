#!/bin/sh
set -eu

# Pull model if requested
if [ -n "${OLLAMA_MODEL:-}" ]; then
  echo "Pulling Ollama model: $OLLAMA_MODEL"
  ollama pull "$OLLAMA_MODEL" || true
fi

echo "Starting Ollama server"
ollama serve &

echo "Waiting for Ollama to become healthy"
i=0
max=60
while [ "$i" -lt "$max" ]; do
  # Consider the Ollama HTTP server "up" if we can connect to the port
  # (some Ollama/Gin builds may not expose /api/info and return 404).
  if curl -sS --max-time 2 http://localhost:11434/ >/dev/null 2>&1; then
    echo "Ollama is healthy"
    break
  fi
  i=$((i+1))
  echo "waiting... ($i)"
  sleep 5
done

echo "Starting bot"
exec python bot.py
