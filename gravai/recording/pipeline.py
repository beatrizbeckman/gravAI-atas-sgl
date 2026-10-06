"""
The recording steps shared by the legacy endpoints in api/app.py and the
minutes jobs in jobs/executors.py: record a Teams meeting, slice the main audio
track per participant and transcribe the slices with whisper. Each step writes
the same files to the recording folder whoever calls it.
"""

from __future__ import annotations

import json
import os
import threading

from gravai.models import Session, TranscriptedSession

SESSION_METADATA_FILE = "session_metadata.json"
SESSION_TRANSCRIPTION_FILE = "session_transcription.json"

# The WS audio server and the Playwright recorder support a single meeting at a time.
RECORDING_LOCK = threading.Lock()


class RecordingBusy(RuntimeError):
    """Another meeting is being recorded right now."""


def record_meeting(meeting_url: str, max_seconds: int | None = None) -> str:
    """Joins the meeting with the bot and records it until it ends. Returns the tracks folder."""
    # Imported here: Playwright and the WS server are heavy and only needed for this step.
    from gravai.recording.teams import TeamsMeetingRecorder

    if not RECORDING_LOCK.acquire(blocking=False):
        raise RecordingBusy("A meeting is already being recorded. Try again when it finishes.")
    try:
        return TeamsMeetingRecorder().record_meeting_with_ws_audio_server(meeting_url, max_seconds=max_seconds)
    finally:
        RECORDING_LOCK.release()


def slice_tracks(tracks_dir: str) -> tuple[str, Session]:
    """Cuts the main audio track into one WAV per participant and writes session_metadata.json."""
    from gravai.slicing.slice import Slicer

    session = Slicer.slice_teams_audio_track(tracks_dir)
    metadata_path = os.path.join(tracks_dir, SESSION_METADATA_FILE)
    Slicer.save_session_data(session, metadata_path)
    return metadata_path, session


def transcribe_tracks(tracks_dir: str, session: Session) -> TranscriptedSession:
    """Runs whisper on every participant track and writes session_transcription.json."""
    from gravai.transcription.base import transcribe_meeting_tracks

    transcribed = transcribe_meeting_tracks(session)
    with open(os.path.join(tracks_dir, SESSION_TRANSCRIPTION_FILE), "w", encoding="utf-8") as f:
        json.dump(transcribed.model_dump(), f, default=str, ensure_ascii=False, indent=2)
    return transcribed


def slice_and_transcribe(tracks_dir: str) -> tuple[str, TranscriptedSession]:
    metadata_path, session = slice_tracks(tracks_dir)
    return metadata_path, transcribe_tracks(tracks_dir, session)
