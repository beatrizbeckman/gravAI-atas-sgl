from models.models import Session
from transcribe.base import transcribe_meeting_tracks as transcribe_meeting_tracks_base

def transcribe_meeting_tracks(
        session: Session,
        whisper_server_host: str | None = None,
        whisper_server_port: int | None = None
    ):
    return transcribe_meeting_tracks_base(session, whisper_server_host, whisper_server_port)
