import os
from pathlib import Path
import requests

from config.settings import Settings
from config.logging_config import get_logger
from models.models import Session, ParticipantDataTransc, Transcription, TranscriptedSession
from transcribe.formatter import format_and_save_single_segment

def transcribe_meeting_tracks(
        session: Session,
        whisper_server_host: str | None = None,
        whisper_server_port: int | None = None
    ):
    settings = Settings() # type: ignore
    whisper_host = whisper_server_host or settings.WHISPER_HOST
    whisper_port = whisper_server_port or settings.WHISPER_PORT
    log_dir = os.path.dirname(next(iter(session.tracks.values())).track.wav_file_path) if session.tracks else None
    logger = get_logger("transcribe", log_dir)

    logger.info(f"Transcription started for session {session.session_id} ({len(session.tracks)} track(s))")
    tracks = {}
    for participant_id, participant_data in session.tracks.items():
        wav_file_path = participant_data.track.wav_file_path
        os.makedirs(os.path.dirname(wav_file_path), exist_ok=True)
        logger.info(f"Transcribing track for participant {participant_data.participant_name} (id: {participant_id})")
        transcription = transcribe(wav_file_path, whisper_host, int(whisper_port))
        transcription_text = transcription.get("text", "")
        transcription_segments = transcription.get("segments", "")
        transcription_text_output_path = wav_file_path.split(".")[0] + "_transcription_text.txt"
        transcription_segments_output_path = wav_file_path.split(".")[0] + "_transcription_segments.txt"
        with open(transcription_text_output_path, "w", encoding="utf-8") as f:
            f.write(transcription_text)
        format_and_save_single_segment(Path(transcription_segments_output_path), transcription_segments)

        logger.info(f"Transcription finished for participant {participant_data.participant_name} (id: {participant_id})")
        tracks[participant_id] = ParticipantDataTransc(
            participant_id=participant_id,
            participant_name=participant_data.participant_name,
            track=participant_data.track,
            transcription=Transcription(
                transcription_text_file_path=transcription_text_output_path,
                transcription_segments_file_path=transcription_segments_output_path
            )
        )

    logger.info(f"Transcription completed for session {session.session_id}")
    return TranscriptedSession(
        session_id=session.session_id,
        session_start=session.session_start,
        session_end=session.session_end,
        tracks=tracks
    )


def transcribe(audio_file: str, whisper_server_host: str, whisper_server_port: int) -> dict:
    response = requests.post(
        f"http://{whisper_server_host}:{whisper_server_port}/inference",
        files={
            "file": (os.path.basename(audio_file), open(audio_file, "rb"), "audio/wav")
        },
        data={
            "temperature": "0.0",
            "response_format": "verbose_json"
        }
    )
    if response.status_code != 200:
        raise Exception(f"Error from whisper server: {response.status_code} {response.text}")
    
    # whisper.cpp usually returns the transcription under the "text" key when using verbose_json
    return response.json()