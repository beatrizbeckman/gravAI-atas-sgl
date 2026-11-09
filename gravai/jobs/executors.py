"""
The three job kinds of the contract, as executors for JobWorker.

    from_transcript      params: utterances, participants?, custom?
    from_recording       params: tracks_dir, participants?, custom?
    record_and_generate  params: meeting_url, max_recording_seconds?, participants?, custom?

All of them end in generate_minutes(); the first two differ only in where the
utterances come from, the third also records and transcribes first.

record_and_generate has a preparer too (PREPARERS): the recording itself, which the
worker runs in its own thread so several meetings can be recorded at once, while
transcription and generation stay one job at a time.
"""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime

from gravai.config import Settings
from gravai.jobs.models import Job
from gravai.jobs.worker import ExecutionOutcome, Prepared
from gravai.minutes.generate import (
    GenerationResult,
    MinutesError,
    generate_minutes,
    resolve_template,
    suggest_filename,
)
from gravai.minutes.meeting_time import fill_meeting_time, recording_span
from gravai.minutes.transcript_normalizer import normalize_session
from gravai.minutes.usage_log import log_generation
from gravai.recording import pipeline

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


def record_meeting_step(job: Job, progress: Progress) -> Prepared:
    """The recording part of record_and_generate: the meeting folder and the header with date/time."""
    started = datetime.now(UTC)
    tracks_dir = _record(job, progress)
    # When the bot was inside the meeting; the job's own clock if the recorder left no timeline.
    start, end = recording_span(tracks_dir) or (started, datetime.now(UTC))
    template = resolve_template(job.template, job.params.get("custom"))
    header = fill_meeting_time(template, job.header, start, end, Settings().TIMEZONE)
    return Prepared(params={"tracks_dir": tracks_dir}, header=header)


def run_record_and_generate(job: Job, progress: Progress) -> ExecutionOutcome:
    if "tracks_dir" in job.params:  # recorded already by the preparer
        tracks_dir, header = job.params["tracks_dir"], job.header
    else:
        prepared = record_meeting_step(job, progress)
        tracks_dir, header = prepared.params["tracks_dir"], prepared.header
    progress("transcribing")
    _transcribe(tracks_dir)
    progress("normalizing")
    utterances = _normalize(tracks_dir)
    return _generate(job, utterances, progress, header)


EXECUTORS = {
    "from_transcript": run_from_transcript,
    "from_recording": run_from_recording,
    "record_and_generate": run_record_and_generate,
}

PREPARERS = {
    "record_and_generate": record_meeting_step,
}


# ------------------------------------------------------------------ steps


def _generate(job: Job, utterances: list, progress: Progress, header: dict | None = None) -> ExecutionOutcome:
    header = header if header is not None else job.header
    filename = suggest_filename(job.template, header)
    output_path = os.path.join(minutes_output_dir(), job.id, filename)
    result: GenerationResult = generate_minutes(
        job.template,
        header,
        utterances,
        output_path,
        participants=job.params.get("participants"),
        custom=job.params.get("custom"),
        max_chars=Settings().LLM_MAX_CHARS,
        progress=progress,
    )
    # Terminal report + one row in <SAVE_DIR>/llm_usage.csv, to size the LLM plan per meeting.
    log_generation(result, job_id=job.id, kind=job.kind, project_id=job.project_id)
    usage = result.usage.summary()
    usage.pop("calls")
    usage["meeting_minutes"] = result.meeting_minutes
    return ExecutionOutcome(
        result={
            "download_url": download_url(job.id),
            "filename": filename,
            "participants": result.participants,
            "utterances": result.utterances,
            "parts": result.parts,
            "llm_model": result.llm_model,
            "generation_seconds": result.generation_seconds,
            "llm_calls": result.llm_calls,
            "llm_usage": usage,
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
    progress("recording")
    try:
        return pipeline.record_meeting(
            job.params["meeting_url"], max_seconds=job.params.get("max_recording_seconds"), key=job.id
        )
    except pipeline.RecordingBusy as exc:
        raise MinutesError("recording_failed", f"no recorder available: {exc}") from exc
    except Exception as exc:
        raise MinutesError("recording_failed", f"{exc.__class__.__name__}: {exc}") from exc


def _transcribe(tracks_dir: str) -> None:
    """Slices the tracks and runs whisper on each one (same steps as POST /transcribe)."""
    try:
        pipeline.slice_and_transcribe(tracks_dir)
    except Exception as exc:
        raise MinutesError("transcription_failed", f"{exc.__class__.__name__}: {exc}") from exc
