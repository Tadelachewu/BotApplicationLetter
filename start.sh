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
  if curl -sS --fail http://localhost:11434/api/info >/dev/null 2>&1; then
    echo "Ollama is healthy"
    break
  fi
  i=$((i+1))
  echo "waiting... ($i)"
  sleep 5
done

echo "Starting bot"
exec python bot.py
