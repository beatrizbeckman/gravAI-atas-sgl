import os
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# Configuration from environment variables
GROQ_API_KEY_ENV = os.environ.get("GROQ_API_KEY_ENV")
GROQ_MODEL = os.environ.get("GROQ_MODEL")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
BASE_BACKOFF_SECONDS = int(os.environ.get("BASE_BACKOFF_SECONDS", "2"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "40"))
DAILY_TOKEN_BUDGET = int(os.environ.get("DAILY_TOKEN_BUDGET", "500000"))
RESERVED_FOR_AGGREGATION = int(os.environ.get("RESERVED_FOR_AGGREGATION", "20000"))

_enc = None


def estimate_tokens(text: str) -> int:
    # tiktoken downloads its encoding on first use, so load it lazily instead of at import time.
    global _enc
    if _enc is None:
        import tiktoken

        _enc = tiktoken.get_encoding("cl100k_base")
    return len(_enc.encode(text))


def create_groq_client() -> Groq:
    api_key = GROQ_API_KEY_ENV
    if not api_key:
        raise RuntimeError("Missing environment variable: GROQ_API_KEY_ENV")
    return Groq(api_key=api_key)


def call_groq(prompt: str, content: str) -> str:
    client = create_groq_client()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": content},
                    {"role": "user", "content": prompt},
                ],
            )

            content_text = response.choices[0].message.content
            if not content_text or not content_text.strip():
                raise RuntimeError("Groq response content is empty")

            return content_text

        except Exception as exc:
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"Groq API request failed after {MAX_RETRIES} attempts: {exc}") from exc
            backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            time.sleep(backoff)
