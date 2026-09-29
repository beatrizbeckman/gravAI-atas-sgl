import requests

from config.settings import Settings


def generate(system: str, user: str) -> str:
    """
    Sends one system + user prompt to the configured provider and returns the
    reply text. Everything above this function is provider-agnostic: switching
    between the local Ollama and Groq is only LLM_PROVIDER in .env.
    """
    settings = Settings()
    if settings.LLM_PROVIDER == "ollama":
        return ollama_generate(
            system, user,
            host=settings.OLLAMA_HOST,
            model=settings.OLLAMA_MODEL,
            num_ctx=settings.OLLAMA_NUM_CTX,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
    if settings.LLM_PROVIDER == "groq":
        # Imported lazily: the groq package and its key are only needed for this provider.
        from llm_analyser.groq_config import call_groq
        return call_groq(user, system)
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}' (expected 'ollama' or 'groq')")


def ollama_generate(system: str, user: str, host: str, model: str, num_ctx: int, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # Constrains the sampler to valid JSON; the prompt still has to say what keys to use.
        "format": "json",
        "options": {
            "temperature": 0,
            # Ollama defaults to a 2k context and silently truncates the prompt beyond it.
            "num_ctx": num_ctx,
        },
    }
    try:
        response = requests.post(f"{host}/api/chat", json=payload, timeout=timeout)
    except requests.ConnectionError as exc:
        raise RuntimeError(f"Could not reach Ollama at {host}. Is it running? (`ollama serve`)") from exc
    if response.status_code == 404:
        raise RuntimeError(f"Ollama does not have model '{model}'. Run `ollama pull {model}`.")
    if response.status_code != 200:
        raise RuntimeError(f"Ollama error {response.status_code}: {response.text[:300]}")

    content = response.json().get("message", {}).get("content", "")
    if not content.strip():
        raise RuntimeError("Ollama returned an empty reply")
    return content
