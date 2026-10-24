import os

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

RECORDING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recording")


def _recording_file(*parts: str) -> str:
    return os.path.join(RECORDING_DIR, *parts)


class Settings(BaseSettings):
    """Application configuration from environment variables (.env is loaded too)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    WS_HOST: str = Field("127.0.0.1", min_length=1, description="Required WebSocket host", alias="WS_HOST")
    WS_PORT: int = Field(8765, description="Required WebSocket port", alias="WS_PORT")
    SAVE_DIR: str = Field(
        "/tmp", min_length=1, description="Directory to save recordings and metadata", alias="SAVE_DIR"
    )

    # Browser-side scripts and the audio server, resolved relative to the repository.
    RTC_INTERCEPT_JS_PATH: str = Field(
        default_factory=lambda: _recording_file("common", "rtc_intercept.js"),
        description="Path to the RTC intercept JavaScript file",
    )
    VAD_OBSERVER_TEAMS_JS_PATH: str = Field(
        default_factory=lambda: _recording_file("teams", "vad_observer.js"),
        description="Path to the VAD observer JavaScript file",
    )
    AUDIO_WORKLET_JS_PATH: str = Field(
        default_factory=lambda: _recording_file("common", "audio_worklet_processor.js"),
        description="Path to the Audio Worklet JavaScript file",
    )
    WS_AUDIO_SERVER_PATH: str = Field(
        default_factory=lambda: _recording_file("ws_audio_server.py"),
        description="Path to the WebSocket audio server Python file",
    )

    WHISPER_HOST: str = Field(..., description="Host URL for the Whisper transcription service", alias="WHISPER_HOST")
    WHISPER_PORT: str = Field(..., description="Port for the Whisper transcription service", alias="WHISPER_PORT")

    RECORDING_DEBUG: bool = Field(
        False,
        description="Save periodic screenshots of the Teams pre-join screen to the session folder",
        alias="RECORDING_DEBUG",
    )
    MAX_RECORDING_SECONDS: int = Field(
        7_200,
        description="Stop recording after this many seconds if the meeting end is not detected",
        alias="MAX_RECORDING_SECONDS",
    )
    TIMEZONE: str = Field(
        "America/Fortaleza",
        description=(
            "IANA timezone of the meetings, used to write the recorded date and time in the minutes header "
            "(the container clock is UTC). America/Fortaleza = Campina Grande, UTC-3 all year"
        ),
        alias="TIMEZONE",
    )
    API_KEY: str = Field(
        "",
        description=(
            "Shared secret the clients (the SGL) send in the X-API-Key header to call /minutes/* and the "
            "recording endpoints. Empty: no key is asked, anyone who reaches the API can use it"
        ),
        alias="API_KEY",
    )

    # Minutes generation
    LLM_PROVIDER: str = Field(
        "openai_compatible",
        description=(
            "Who generates the minutes: 'openai_compatible' (online API in the OpenAI format: DeepInfra, Groq, OpenAI...), "
            "'ollama' (local), 'groq' (legacy), or 'fake' (placeholder text, no LLM; for demos and tests)"
        ),
        alias="LLM_PROVIDER",
    )
    OLLAMA_HOST: str = Field("http://127.0.0.1:11434", description="Base URL of the Ollama server", alias="OLLAMA_HOST")
    OLLAMA_MODEL: str = Field(
        "qwen2.5:7b-instruct", description="Ollama model used for the minutes", alias="OLLAMA_MODEL"
    )
    OLLAMA_NUM_CTX: int = Field(
        16_384,
        description="Context window requested from Ollama; must hold the prompt plus the transcript part",
        alias="OLLAMA_NUM_CTX",
    )
    LLM_BASE_URL: str = Field(
        "https://api.groq.com/openai/v1",
        description=(
            "Base URL of the online provider when LLM_PROVIDER='openai_compatible' "
            "(Groq: https://api.groq.com/openai/v1, OpenRouter: https://openrouter.ai/api/v1, "
            "DeepInfra: https://api.deepinfra.com/v1/openai)"
        ),
        alias="LLM_BASE_URL",
    )
    LLM_API_KEY: str = Field(
        "", description="API key of the online provider; sent as 'Authorization: Bearer <key>'", alias="LLM_API_KEY"
    )
    LLM_MODEL: str = Field(
        # Only model with 5/5 minutes in the experiments on the Groq free tier (LLMS.md)
        "openai/gpt-oss-120b",
        description="Model id at the online provider, in the provider's own naming",
        alias="LLM_MODEL",
    )
    LLM_MAX_TOKENS: int = Field(
        8_000,
        description="Reply cap sent to the online provider; reasoning models spend part of it thinking, so keep it generous",
        alias="LLM_MAX_TOKENS",
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        600, description="Give up on a single LLM request after this many seconds", alias="LLM_TIMEOUT_SECONDS"
    )

    JOBS_DB_PATH: str | None = Field(
        None,
        description="SQLite file for the minutes jobs; default is <SAVE_DIR>/minutes_jobs.sqlite3",
        alias="JOBS_DB_PATH",
    )
