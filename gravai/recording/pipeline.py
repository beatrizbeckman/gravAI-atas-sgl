"""
The recording steps shared by the legacy endpoints in api/app.py and the
minutes jobs in jobs/executors.py: record a Teams meeting, slice the main audio
track per participant and transcribe the slices with whisper. Each step writes
the same files to the recording folder whoever calls it.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
import uuid

from gravai.config import Settings
from gravai.models import Session, TranscriptedSession

SESSION_METADATA_FILE = "session_metadata.json"
SESSION_TRANSCRIPTION_FILE = "session_transcription.json"

# Recordings in progress, by key (the job id for minutes jobs), each with the event that
# makes its recorder process leave the meeting. Several meetings can be recorded at once:
# each one has its own Chromium process and its own session folder in the WS audio server.
_ACTIVE_LOCK = threading.Lock()
_active: dict[str, object] = {}


class RecordingBusy(RuntimeError):
    """Every recorder slot (MAX_CONCURRENT_RECORDINGS) is in use right now."""


def max_recordings() -> int:
    return Settings().MAX_CONCURRENT_RECORDINGS


def active_recordings() -> int:
    with _ACTIVE_LOCK:
        return len(_active)


def record_meeting(meeting_url: str, max_seconds: int | None = None, key: str | None = None) -> str:
    """
    Joins the meeting with the bot and records it until it ends or request_stop(key) is
    called. Returns the tracks folder. Raises RecordingBusy when all slots are taken.
    """
    # Imported here: Playwright and the WS server are heavy and only needed for this step.
    from gravai.recording.teams import TeamsMeetingRecorder

    key = key or uuid.uuid4().hex
    # The recorder runs in a spawned process, so the event must come from the same start method.
    stop_event = mp.get_context("spawn").Event()
    with _ACTIVE_LOCK:
        limit = max_recordings()
        if len(_active) >= limit:
            raise RecordingBusy(f"All {limit} recorders are busy. Try again when a meeting finishes.")
        if key in _active:
            raise RecordingBusy(f"Recording '{key}' is already running.")
        _active[key] = stop_event
    try:
        return TeamsMeetingRecorder().record_meeting_with_ws_audio_server(
            meeting_url, max_seconds=max_seconds, stop_event=stop_event
        )
    finally:
        with _ACTIVE_LOCK:
            _active.pop(key, None)


def request_stop(key: str) -> bool:
    """
    Asks the recording with this key to leave the meeting now; what was recorded is kept
    and the next steps (slicing, whisper, minutes) run as usual. The recorder checks the
    request about once a second, once it is inside the meeting. False when that recording
    is not running.
    """
    with _ACTIVE_LOCK:
        event = _active.get(key)
    if event is None:
        return False
    event.set()
    return True


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
