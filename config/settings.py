from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from models.models import Singleton
import os 
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings, Singleton):
    """Application configuration from environment variables"""
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    WS_HOST: str = Field(
        "127.0.0.1",
        min_length=1,
        description="Required WebSocket host",
        alias="WS_HOST",
    )

    WS_PORT: int = Field(
        8765,
        description="Required WebSocket port",
        alias="WS_PORT",
    )

    SAVE_DIR: str = Field(
        "/tmp",
        min_length=1,
        description="Directory to save recordings and metadata",
        alias="SAVE_DIR",
    )

    RTC_INTERCEPT_JS_PATH: str = Field(
        default_factory=lambda: os.path.join(os.path.dirname(__file__), "..", "recording", "common", "rtc_intercept.js"),
        description="Path to the RTC intercept JavaScript file",
    )

    VAD_OBSERVER_TEAMS_JS_PATH: str = Field(
        default_factory=lambda: os.path.join(os.path.dirname(__file__), "..", "recording", "teams", "vad_observer.js"),
        description="Path to the VAD observer JavaScript file",
    )

    AUDIO_WORKLET_JS_PATH: str = Field(
        default_factory=lambda: os.path.join(os.path.dirname(__file__), "..", "recording", "common", "audio_worklet_processor.js"),
        description="Path to the Audio Worklet JavaScript file",
    )

    WS_AUDIO_SERVER_PATH: str = Field(
        default_factory=lambda: os.path.join(os.path.dirname(__file__), "..", "recording", "ws_audio_server.py"),
        description="Path to the WebSocket audio server Python file",
    )

    WHISPER_HOST: str = Field(
        ...,
        description="Host URL for the Whisper transcription service",
        alias="WHISPER_HOST",
    )

    WHISPER_PORT: str = Field(
        ...,
        description="Port for the Whisper transcription service",
        alias="WHISPER_PORT",
    )

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

    LLM_PROVIDER: str = Field(
        "ollama",
        description="Who generates the minutes: 'ollama' (local) or 'groq'",
        alias="LLM_PROVIDER",
    )

    OLLAMA_HOST: str = Field(
        "http://127.0.0.1:11434",
        description="Base URL of the Ollama server",
        alias="OLLAMA_HOST",
    )

    OLLAMA_MODEL: str = Field(
        "qwen2.5:7b-instruct",
        description="Ollama model used for the minutes",
        alias="OLLAMA_MODEL",
    )

    OLLAMA_NUM_CTX: int = Field(
        16_384,
        description="Context window requested from Ollama; must hold the prompt plus the transcript part",
        alias="OLLAMA_NUM_CTX",
    )

    LLM_TIMEOUT_SECONDS: int = Field(
        600,
        description="Give up on a single LLM request after this many seconds",
        alias="LLM_TIMEOUT_SECONDS",
    )

    # DF_PATH: str = "df.pkl"


    # @model_validator(mode="after")
    # def assemble_es_hosts(self) -> "Settings":
    #     """Constructs the ES_HOSTS URL after model validation."""
    #     if self.ES_HOST and self.ES_PORT:
    #         self.ES_HOSTS = [f"http://{self.ES_HOST}:{self.ES_PORT}"]
    #     return self
