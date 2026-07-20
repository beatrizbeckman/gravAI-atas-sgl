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
        default_factory=lambda: os.path.join(os.path.dirname(__file__), "..", "recording", "providers", "teams", "vad_observer.js"),
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

    LOG_LEVEL: str = Field(
        "INFO",
        description="Logging verbosity (DEBUG, INFO, WARNING, ERROR)",
        alias="LOG_LEVEL",
    )

    # DF_PATH: str = "df.pkl"


    # @model_validator(mode="after")
    # def assemble_es_hosts(self) -> "Settings":
    #     """Constructs the ES_HOSTS URL after model validation."""
    #     if self.ES_HOST and self.ES_PORT:
    #         self.ES_HOSTS = [f"http://{self.ES_HOST}:{self.ES_PORT}"]
    #     return self
