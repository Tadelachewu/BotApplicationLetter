import os
import time
import random
import requests
import email.utils
from datetime import datetime


class LLMError(Exception):
    def __init__(self, message: str, *, kind: str = "unknown", provider: str = "unknown"):
        super().__init__(message)
        self.kind = kind
        self.provider = provider


class LLMQuotaError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMAuthError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


def _parse_retry_after(value: str):
    if not value:
        return None
    raw = str(value).strip()
    try:
        secs = float(raw)
        if secs >= 0:
            return secs
    except Exception:
        pass

    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt is None:
            return None
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.utcnow()
        delta = (dt - now).total_seconds()
        return max(0.0, float(delta))
    except Exception:
        return None


def _full_jitter_backoff(attempt_index: int, cap_seconds: float):
    base = 1.0
    ceiling = min(float(cap_seconds), base * (2.0 ** float(attempt_index)))
    return random.uniform(0.0, max(0.0, ceiling))


def _get_json_safely(response: requests.Response):
    try:
        return response.json() if response.content else {}
    except Exception:
        return {}


def call_gemini(prompt: str) -> str:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key.lower() in {"your_gemini_api_key_here", "your_api_key_here"}:
        raise LLMAuthError("GEMINI_API_KEY is missing or placeholder", kind="auth", provider="gemini")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        f"?key={api_key}"
    )

    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "8"))
    backoff_cap = float(os.getenv("GEMINI_BACKOFF_CAP_SECONDS", "120"))
    request_timeout = float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "25"))

    headers = {"Content-Type": "application/json"}

    def classify(status_code: int, payload: dict):
        err = (payload or {}).get("error") or {}
        status = str(err.get("status") or "").upper()
        message = str(err.get("message") or payload.get("message") or "")
        message_l = message.lower()

        quota_markers = [
            "quota",
            "exceed",
            "exhaust",
            "insufficient quota",
            "billing",
            "payment",
            "resource has been exhausted",
        ]
        rate_markers = [
            "rate",
            "rate limit",
            "too many requests",
            "per minute",
            "per second",
            "rpm",
            "rps",
            "requests per",
        ]

        if status in {"RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"}:
            return "quota", status, message
        if status_code in {429, 403}:
            if any(m in message_l for m in quota_markers) and not any(m in message_l for m in rate_markers):
                return "quota", status, message
            if any(m in message_l for m in rate_markers):
                return "rate_limit", status, message
            if status_code == 429:
                return "unknown_429", status, message
        return "other", status, message

    for attempt in range(1, max_retries + 1):
        response = requests.post(
            url,
            headers=headers,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=request_timeout,
        )

        if response.status_code in (429, 403):
            payload = _get_json_safely(response)
            kind, status, message = classify(response.status_code, payload)

            if kind == "quota":
                raise LLMQuotaError(
                    f"Quota exhausted. Provider status={status}. {message}".strip(),
                    kind="quota",
                    provider="gemini",
                )

            if response.status_code == 403 and kind != "rate_limit":
                raise LLMAuthError(
                    f"Forbidden (not retrying). Provider status={status}. {message}".strip(),
                    kind="auth",
                    provider="gemini",
                )

            if response.status_code == 429:
                if attempt == max_retries:
                    raise LLMRateLimitError(
                        f"Rate limited after {max_retries} attempts. Provider status={status}. {message}".strip(),
                        kind="rate_limit" if kind == "rate_limit" else "unknown_429",
                        provider="gemini",
                    )

                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                wait = min(backoff_cap, retry_after) if retry_after is not None else _full_jitter_backoff(attempt, backoff_cap)
                print(f"429 from Gemini ({kind}). Retrying after {wait:.1f}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
                continue

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            payload = _get_json_safely(response)
            message = (payload.get("error", {}) or {}).get("message") or payload.get("message") or str(e)
            raise LLMProviderError(message, kind="http_error", provider="gemini")

        data = _get_json_safely(response)
        candidates = (data or {}).get("candidates") or []
        generated_text = ""
        if candidates:
            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            if parts and isinstance(parts[0], dict):
                generated_text = (parts[0].get("text") or "").strip()

        if not generated_text:
            raise LLMProviderError("Empty/invalid response from Gemini API", kind="empty", provider="gemini")
        return generated_text

    raise LLMRateLimitError("Rate limited", kind="rate_limit", provider="gemini")


def _openai_like_chat_completion(
    *,
    provider: str,
    base_url: str,
    api_key_env: str,
    model_env: str,
    default_model: str,
    prompt: str,
) -> str:
    api_key = (os.getenv(api_key_env) or "").strip()
    if not api_key or api_key.lower().startswith("your_"):
        raise LLMAuthError(f"{api_key_env} is missing or placeholder", kind="auth", provider=provider)

    model = (os.getenv(model_env) or default_model).strip()
    timeout = float(os.getenv(f"{provider.upper()}_REQUEST_TIMEOUT_SECONDS", "30"))

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant that follows formatting instructions exactly.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    data = _get_json_safely(resp)

    if resp.status_code in (401, 403):
        msg = (data.get("error") or {}).get("message") or "Forbidden/Unauthorized"
        raise LLMAuthError(msg, kind="auth", provider=provider)

    # OpenAI-style “insufficient_quota” can come as 429 with type/code.
    if resp.status_code == 429:
        err = data.get("error") or {}
        err_type = str(err.get("type") or "").lower()
        err_code = str(err.get("code") or "").lower()
        msg = str(err.get("message") or "Too Many Requests")
        if "insufficient" in err_type or "insufficient" in err_code or "quota" in msg.lower():
            raise LLMQuotaError(msg, kind="quota", provider=provider)
        raise LLMRateLimitError(msg, kind="rate_limit", provider=provider)

    if resp.status_code == 402:
        msg = (data.get("error") or {}).get("message") or "Payment required"
        raise LLMQuotaError(msg, kind="quota", provider=provider)

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        msg = (data.get("error") or {}).get("message") or str(e)
        raise LLMProviderError(msg, kind="http_error", provider=provider)

    choices = data.get("choices") or []
    if not choices:
        raise LLMProviderError("Empty response", kind="empty", provider=provider)

    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise LLMProviderError("Empty content", kind="empty", provider=provider)
    return text


def call_openai(prompt: str) -> str:
    return _openai_like_chat_completion(
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        default_model="gpt-4o-mini",
        prompt=prompt,
    )


def call_groq(prompt: str) -> str:
    return _openai_like_chat_completion(
        provider="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        default_model="llama-3.1-70b-versatile",
        prompt=prompt,
    )


def call_huggingface(prompt: str) -> str:
    api_key = (os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_API_KEY") or "").strip()
    if not api_key or api_key.lower().startswith("your_"):
        raise LLMAuthError("HUGGINGFACE_API_KEY (or HF_API_KEY) is missing or placeholder", kind="auth", provider="huggingface")

    model = (os.getenv("HUGGINGFACE_MODEL") or "mistralai/Mistral-7B-Instruct-v0.2").strip()
    timeout = float(os.getenv("HUGGINGFACE_REQUEST_TIMEOUT_SECONDS", "45"))

    # If the model env is a full URL (some users paste the full inference URL),
    # accept it but normalize any deprecated api-inference host to router.huggingface.co.
    if model.lower().startswith("http"):
        url = model
    else:
        url = f"https://router.huggingface.co/models/{model}"

    # Normalize deprecated hostname if present
    url = url.replace("api-inference.huggingface.co", "router.huggingface.co")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Inference API behavior varies by model; keep request simple.
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 700,
            "temperature": 0.4,
            "return_full_text": False,
        },
        "options": {"wait_for_model": True},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    data = _get_json_safely(resp)

    if resp.status_code in (401, 403):
        msg = (data.get("error") if isinstance(data, dict) else None) or "Forbidden/Unauthorized"
        raise LLMAuthError(str(msg), kind="auth", provider="huggingface")

    if resp.status_code == 429:
        msg = (data.get("error") if isinstance(data, dict) else None) or "Too Many Requests"
        raise LLMRateLimitError(str(msg), kind="rate_limit", provider="huggingface")

    if resp.status_code in (402,):
        msg = (data.get("error") if isinstance(data, dict) else None) or "Payment required"
        raise LLMQuotaError(str(msg), kind="quota", provider="huggingface")

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        msg = (data.get("error") if isinstance(data, dict) else None) or str(e)
        raise LLMProviderError(str(msg), kind="http_error", provider="huggingface")

    # Typical successful output: a list of {"generated_text": "..."}
    if isinstance(data, list) and data and isinstance(data[0], dict):
        text = (data[0].get("generated_text") or "").strip()
        if text:
            return text

    # Some models return dict with "generated_text".
    if isinstance(data, dict):
        text = (data.get("generated_text") or "").strip()
        if text:
            return text

    raise LLMProviderError("Unrecognized Hugging Face response format", kind="parse", provider="huggingface")


_PROVIDER_CALLS = {
    "gemini": call_gemini,
    "openai": call_openai,
    "groq": call_groq,
    "huggingface": call_huggingface,
}


def list_available_providers():
    return list(_PROVIDER_CALLS.keys())


def call_provider(provider: str, prompt: str) -> str:
    key = (provider or "").strip().lower()
    if key not in _PROVIDER_CALLS:
        raise LLMProviderError(f"Unknown provider: {provider}", kind="config", provider=key or "unknown")
    return _PROVIDER_CALLS[key](prompt)
