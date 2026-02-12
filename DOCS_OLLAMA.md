# Ollama Fallback (Local LLM) — Usage Guide

This project supports using a locally hosted Ollama model as a last-resort fallback when cloud LLMs (Gemini/OpenAI/Groq) fail due to quota, billing, or rate limits.

How it works
- The app will automatically append `ollama` to the provider order when the Ollama provider is available.
- The Python code attempts to run the `ollama` CLI or a custom command template and reads its stdout as the model output.

Configure via environment
- Option A (recommended): set `OLLAMA_MODEL` to the model name you installed locally.
- Option B: set `OLLAMA_COMMAND` to a shell command template; the template may include `{prompt}` and `{model}`.

Example `.env` snippets
```
# Ollama local fallback (optional)
OLLAMA_MODEL=your-local-model-name
# Or a custom shell command template — `{prompt}` and `{model}` will be substituted
# Example: OLLAMA_COMMAND=ollama chat {model}
# OLLAMA_COMMAND="C:\\path\\to\\ollama.exe chat {model}"
```

Quick local test (from project root)
```powershell
python -c "from llm_providers import call_ollama; print(call_ollama('Write a brief professional job application letter.'))"
```

Notes
- Ollama must be installed separately (https://ollama.com). The repo does not vendor the Ollama CLI.
- No additional Python dependency is required: the integration calls the CLI via `subprocess`.
- If the CLI is unavailable or returns an error, the provider raises a `LLMProviderError` and the app will continue using other providers.
- If you want Ollama to run on the Render host, Render must allow installing and running the Ollama CLI there (not typical). The local fallback is most useful when you run the bot on your own machine.

Security
- Be careful when setting `OLLAMA_COMMAND` — it is executed via shell when provided. Prefer `OLLAMA_MODEL` with the standard `ollama` CLI for safety.

Docker image notes
------------------

The project's `Dockerfile` will attempt to pull whatever model name is set in the `OLLAMA_MODEL` environment variable at container startup. Do not bundle large GGUF blobs into the image; instead either:

- Provide a small/quantized model name (Q4 or stronger) via `OLLAMA_MODEL` so `ollama pull <model>` downloads an appropriately sized model at runtime.
- Or mount a model directory into the container at `/root/.ollama/models` (host or network storage) so the container can use an existing uploaded model.

Note: the repo includes `ollama_models/` for local development manifests. The Docker build ignores that folder by default (see `.dockerignore`) to avoid creating oversized images.
