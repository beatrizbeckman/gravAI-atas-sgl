import json
import re
import time
from dataclasses import dataclass, field

import requests

from gravai.config import Settings


def generate(system: str, user: str) -> str:
    """
    Sends one system + user prompt to the configured provider and returns the
    reply text. Everything above this function is provider-agnostic: switching
    between an online API, the local Ollama and the fake provider is only
    LLM_PROVIDER in .env.
    """
    settings = Settings()
    if settings.LLM_PROVIDER == "openai_compatible":
        return openai_compatible_generate(
            system,
            user,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    if settings.LLM_PROVIDER == "ollama":
        return ollama_generate(
            system,
            user,
            host=settings.OLLAMA_HOST,
            model=settings.OLLAMA_MODEL,
            num_ctx=settings.OLLAMA_NUM_CTX,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
    if settings.LLM_PROVIDER == "groq":
        # Imported lazily: the groq package and its key are only needed for this provider.
        from gravai.legacy.llm_analyser.groq_config import call_groq

        return call_groq(user, system)
    if settings.LLM_PROVIDER == "fake":
        return fake_generate(system, user)
    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}' (expected 'openai_compatible', 'ollama', 'groq' or 'fake')"
    )


def model_name() -> str:
    """Identifier of the model behind generate(), reported in the job result."""
    settings = Settings()
    if settings.LLM_PROVIDER == "openai_compatible":
        return settings.LLM_MODEL
    if settings.LLM_PROVIDER == "ollama":
        return settings.OLLAMA_MODEL
    if settings.LLM_PROVIDER == "groq":
        import os

        return os.environ.get("GROQ_MODEL", "groq")
    return settings.LLM_PROVIDER


_SCHEMA_BLOCK = re.compile(r"Formato de saída\s*(\{.*?\})\s*Conteúdo de cada chave", re.DOTALL)


def fake_generate(system: str, user: str) -> str:
    """
    No LLM at all: answers with the output schema found in the system prompt,
    so every section comes back filled with placeholder text. Lets the API, the
    jobs and the demo page run end to end on a machine without Ollama.
    """
    match = _SCHEMA_BLOCK.search(system)
    if not match:
        raise RuntimeError("fake provider: could not find the output schema in the system prompt")
    schema = json.loads(match.group(1))
    return json.dumps(_fill(schema), ensure_ascii=False)


def _fill(value):
    if isinstance(value, dict):
        return {k: _fill(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v) for v in value]
    if isinstance(value, str):
        # Hints look like "texto", "DD/MM" or "Pendente | Em andamento"; keep the first allowed value.
        first = value.split("|")[0].strip()
        return "Conteúdo de exemplo gerado sem LLM (provedor fake)." if first == "texto" else first
    return value


@dataclass
class ChatReply:
    """One answer from an OpenAI-format API, with what the experiments need to log."""

    content: str
    model: str
    seconds: float
    # prompt_tokens / completion_tokens / total_tokens as the provider reports them (may be empty).
    usage: dict = field(default_factory=dict)
    # False when the provider refused response_format and the call was repeated without it.
    json_mode: bool = True
    # "stop" when the model finished; "length" means the reply was cut by max_tokens.
    finish_reason: str | None = None


def openai_compatible_generate(
    system: str, user: str, base_url: str, api_key: str, model: str, timeout: int, max_tokens: int | None = None
) -> str:
    """Online provider for generate(): any API in the OpenAI chat format (DeepInfra, Groq, OpenAI, Together...)."""
    return openai_chat(
        system, user, base_url=base_url, api_key=api_key, model=model, timeout=timeout, max_tokens=max_tokens
    ).content


def openai_chat(
    system: str,
    user: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    json_mode: bool = True,
    max_tokens: int | None = None,
    extra: dict | None = None,
) -> ChatReply:
    """
    POST {base_url}/chat/completions in the OpenAI format and return the reply
    with usage and elapsed time. Kept separate from openai_compatible_generate so
    the experiment runner can call any model directly and log tokens and time.

    json_mode asks for response_format=json_object (temperature 0 as everywhere
    else). Some small models reject that field with 400; the call is then
    repeated once without it, because the prompt already demands JSON and
    parse_response validates the reply anyway.

    max_tokens caps the reply (reasoning tokens count against it on gpt-oss
    models, so keep room). extra is merged into the payload for provider
    specific knobs such as {"reasoning_effort": "low"}.
    """
    if not api_key:
        raise RuntimeError("LLM_API_KEY is empty: set the online provider's key in .env")
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)

    started = time.monotonic()
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.ConnectionError as exc:
        raise RuntimeError(
            f"Could not reach the LLM provider at {base_url}. Check LLM_BASE_URL and the network."
        ) from exc

    if (
        response.status_code == 400
        and json_mode
        and ("response_format" in response.text or "json_validate_failed" in response.text)
    ):
        # Either the model does not support response_format, or (Groq) it produced
        # something that is not valid JSON and the provider refused to return it.
        # Without json mode the raw text comes back and parse_response decides.
        return openai_chat(
            system, user, base_url, api_key, model, timeout, json_mode=False, max_tokens=max_tokens, extra=extra
        )
    _raise_for_provider_error(response, model, base_url)

    body = response.json()
    if isinstance(body, dict) and "error" in body and "choices" not in body:
        # OpenRouter answers 200 with the upstream failure in the body, e.g.
        # {"error": {"message": "Upstream error ...", "code": 502}}. Surface the code
        # so a transient one (5xx/429) is retried like a real HTTP error.
        error = body["error"] if isinstance(body["error"], dict) else {"message": str(body["error"])}
        code = error.get("code") or response.status_code
        raise RuntimeError(f"The LLM provider returned an error ({code}) for model '{model}': {error.get('message')}")
    try:
        choice = body["choices"][0]
        content = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected reply from the LLM provider: {response.text[:300]}") from exc
    if not content.strip():
        raise RuntimeError(f"The LLM provider returned an empty reply for model '{model}'")

    return ChatReply(
        content=content,
        model=body.get("model") or model,
        seconds=round(time.monotonic() - started, 2),
        usage=body.get("usage") or {},
        json_mode=json_mode,
        finish_reason=choice.get("finish_reason"),
    )


RATE_LIMIT_WAITS = (20, 40, 60, 90, 120)


def is_rate_limit_error(exc: Exception) -> bool:
    """
    Worth waiting and trying again: 429, the 413 Groq answers when the per-minute
    budget is nearly used up, and the 5xx a saturated free upstream returns.
    """
    text = str(exc)
    return any(f"({code})" in text or f"error {code}" in text for code in (429, 413, 500, 502, 503, 504))


def openai_chat_retrying(
    system: str, user: str, waits: tuple[int, ...] = RATE_LIMIT_WAITS, log=print, **cfg
) -> ChatReply:
    """openai_chat that waits and tries again while the provider is rate limiting (used by the batch scripts)."""
    for wait in (*waits, None):
        try:
            return openai_chat(system, user, **cfg)
        except RuntimeError as exc:
            if wait is None or not is_rate_limit_error(exc):
                raise
            log(f"rate limit from the LLM provider, waiting {wait}s")
            time.sleep(wait)
    raise AssertionError("unreachable")  # the loop either returned or re-raised


def _raise_for_provider_error(response, model: str, base_url: str) -> None:
    """Turns the HTTP statuses an OpenAI-format API uses into messages that say what to fix."""
    status = response.status_code
    if status == 200:
        return
    detail = response.text[:300]
    if status in (401, 403):
        raise RuntimeError(f"The LLM provider rejected the API key ({status}). Check LLM_API_KEY for {base_url}.")
    if status == 402:
        raise RuntimeError(
            f"The LLM provider account has no balance (402). Add credits at the provider or switch LLM_BASE_URL/LLM_API_KEY: {detail}"
        )
    if status == 404 or (status == 400 and "model" in detail.lower()):
        raise RuntimeError(f"The LLM provider does not serve model '{model}' ({status}): {detail}")
    if status == 413:
        # Groq also answers 413 when the request would exceed what is left of the per-minute budget, so callers retry it like a 429.
        raise RuntimeError(
            f"The request is too large for model {model!r} at this provider, or its per-minute token budget is used up (413). Wait and retry, or reduce max_chars so each transcript part is smaller: {detail}"
        )
    if status == 429:
        raise RuntimeError(
            f"The LLM provider is rate limiting (429). Wait and retry, or use another model/provider: {detail}"
        )
    raise RuntimeError(f"LLM provider error {status}: {detail}")


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
