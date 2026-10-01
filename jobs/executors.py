"""
The three job kinds of the contract, as executors for JobWorker.

    from_transcript      params: utterances, participants?, custom?
    from_recording       params: tracks_dir, participants?, custom?
    record_and_generate  params: meeting_url, max_recording_seconds?, participants?, custom?

All of them end in generate_minutes(); the first two differ only in where the
utterances come from, the third also records and transcribes first.
"""
import json
import os
import threading
from typing import Callable

from config.settings import Settings
from jobs.models import Job
from jobs.worker import ExecutionOutcome
from minutes.generate import GenerationResult, MinutesError, generate_minutes, suggest_filename
from minutes.transcript_normalizer import SESSION_TRANSCRIPTION_FILE, normalize_session

# The WS audio server and the Playwright recorder support a single meeting at a time.
# Shared with the legacy /record_meeting endpoints in api/app.py.
RECORDING_LOCK = threading.Lock()

Progress = Callable[[str], None]


def minutes_output_dir() -> str:
    return os.path.join(Settings().SAVE_DIR, "minutes")


def download_url(job_id: str) -> str:
    return f"/minutes/jobs/{job_id}/download"


# --------------------------------------------------------------- executors

def run_from_transcript(job: Job, progress: Progress) -> ExecutionOutcome:
    return _generate(job, job.params["utterances"], progress)


def run_from_recording(job: Job, progress: Progress) -> ExecutionOutcome:
    progress("normalizing")
    utterances = _normalize(job.params["tracks_dir"])
    return _generate(job, utterances, progress)


def run_record_and_generate(job: Job, progress: Progress) -> ExecutionOutcome:
    tracks_dir = _record(job, progress)
    progress("transcribing")
    _transcribe(tracks_dir)
    progress("normalizing")
    utterances = _normalize(tracks_dir)
    return _generate(job, utterances, progress)


EXECUTORS = {
    "from_transcript": run_from_transcript,
    "from_recording": run_from_recording,
    "record_and_generate": run_record_and_generate,
}


# ------------------------------------------------------------------ steps

def _generate(job: Job, utterances: list, progress: Progress) -> ExecutionOutcome:
    filename = suggest_filename(job.template, job.header)
    output_path = os.path.join(minutes_output_dir(), job.id, filename)
    result: GenerationResult = generate_minutes(
        job.template,
        job.header,
        utterances,
        output_path,
        participants=job.params.get("participants"),
        custom=job.params.get("custom"),
        progress=progress,
    )
    return ExecutionOutcome(
        result={
            "download_url": download_url(job.id),
            "filename": filename,
            "participants": result.participants,
            "utterances": result.utterances,
            "parts": result.parts,
            "llm_model": result.llm_model,
            "generation_seconds": result.generation_seconds,
        },
        docx_path=output_path,
        minutes=result.minutes,
        participants=result.participants,
        header=result.header,
    )


def _normalize(tracks_dir: str) -> list:
    if not os.path.isdir(tracks_dir):
        raise MinutesError("transcription_failed", f"recording folder not found: {tracks_dir}")
    try:
        return [u.model_dump() for u in normalize_session(tracks_dir)]
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise MinutesError("transcription_failed", f"could not read the transcription in {tracks_dir}: {exc}") from exc


def _record(job: Job, progress: Progress) -> str:
    # Imported here: Playwright and the WS server are heavy and only needed for this kind.
    from recording.teams import TeamsMeetingRecorder

    if not RECORDING_LOCK.acquire(blocking=False):
        raise MinutesError("recording_failed", "another meeting is being recorded")
    try:
        progress("recording")
        return TeamsMeetingRecorder().record_meeting_with_ws_audio_server(
            job.params["meeting_url"], max_seconds=job.params.get("max_recording_seconds")
        )
    except MinutesError:
        raise
    except Exception as exc:
        raise MinutesError("recording_failed", f"{exc.__class__.__name__}: {exc}") from exc
    finally:
        RECORDING_LOCK.release()


def _transcribe(tracks_dir: str) -> None:
    """Slices the tracks and runs whisper on each one, writing session_transcription.json (same steps as POST /transcribe)."""
    from slicing.slice import Slicer
    from transcribe.base import transcribe_meeting_tracks

    try:
        session = Slicer.slice_teams_audio_track(tracks_dir)
        Slicer.save_session_data(session, os.path.join(tracks_dir, "session_metadata.json"))
        transcribed = transcribe_meeting_tracks(session)
        with open(os.path.join(tracks_dir, SESSION_TRANSCRIPTION_FILE), "w", encoding="utf-8") as f:
            json.dump(transcribed.model_dump(), f, default=str, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise MinutesError("transcription_failed", f"{exc.__class__.__name__}: {exc}") from exc
