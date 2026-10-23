"""
HTTP layer of the minutes generation: the /minutes/* endpoints of
docs/API_MINUTES.md. Validates the request, creates the job and returns; the
work itself happens in the jobs worker (jobs/).
"""

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from gravai.jobs.runtime import JobsRuntime
from gravai.minutes.custom_template import CustomSpec
from gravai.minutes.generate import missing_header_fields, prepare_utterances, resolve_template
from gravai.minutes.templates import available_templates, load_template
from gravai.minutes.transcript_normalizer import SESSION_TRANSCRIPTION_FILE
from gravai.recording.pipeline import RECORDING_LOCK
from gravai.recording.utils import is_teams_meeting_url

router = APIRouter(prefix="/minutes", tags=["minutes"])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------- schemas


class UtteranceIn(BaseModel):
    speaker: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class MinutesRequest(BaseModel):
    """The block shared by the three POST endpoints (contract section 3)."""

    template: str
    header: dict[str, Any]
    project_id: str | None = Field(default=None, min_length=1, max_length=100)
    participants: list[str] | None = None
    custom: CustomSpec | None = None

    @model_validator(mode="after")
    def check_template_and_header(self):
        if self.template not in available_templates():
            raise ValueError(f"unknown template '{self.template}'; available: {', '.join(available_templates())}")
        try:
            template = resolve_template(self.template, self.custom)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        missing = missing_header_fields(template, self.header)
        if missing:
            raise ValueError(f"missing required header fields for template '{self.template}': {', '.join(missing)}")
        return self

    def job_params(self) -> dict:
        params: dict = {}
        if self.participants:
            params["participants"] = self.participants
        if self.custom is not None:
            params["custom"] = self.custom.model_dump(exclude_none=True)
        return params


class FromTranscriptRequest(MinutesRequest):
    utterances: list[UtteranceIn] = Field(min_length=1)

    @model_validator(mode="after")
    def check_usable_utterances(self):
        if not prepare_utterances([u.model_dump() for u in self.utterances]):
            raise ValueError("utterances has no usable item (non-empty text, end > start)")
        return self


class FromRecordingRequest(MinutesRequest):
    tracks_dir: str = Field(min_length=1)


class RecordAndGenerateRequest(MinutesRequest):
    meeting_url: str = Field(min_length=1)
    max_recording_seconds: int | None = Field(default=None, ge=60)


# -------------------------------------------------------------- helpers


def _jobs(request: Request) -> JobsRuntime:
    return request.app.state.jobs


def _get_job(request: Request, job_id: str):
    job = _jobs(request).store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    return job


def _finished_job(request: Request, job_id: str):
    job = _get_job(request, job_id)
    if job.status != "done":
        detail = f"job is {job.status}" + (f": {job.error.code}: {job.error.message}" if job.error else "")
        raise HTTPException(status_code=409, detail=detail)
    return job


def _has_transcription(tracks_dir: str) -> bool:
    if os.path.isfile(os.path.join(tracks_dir, SESSION_TRANSCRIPTION_FILE)):
        return True
    has_tracks = any(f.endswith("_transcription_segments.json") for f in os.listdir(tracks_dir))
    return has_tracks and os.path.isfile(os.path.join(tracks_dir, "vad_timeline.json"))


def _recording_in_progress(runtime: JobsRuntime) -> bool:
    if RECORDING_LOCK.locked():
        return True
    return any(j.kind == "record_and_generate" for j in runtime.store.list(limit=100, status="queued")) or any(
        j.kind == "record_and_generate" for j in runtime.store.list(limit=100, status="running")
    )


# ------------------------------------------------------------- endpoints


@router.get("/templates")
def list_templates() -> dict:
    return {"templates": [load_template(t).summary() for t in available_templates()]}


@router.post("/from-transcript", status_code=202)
def from_transcript(body: FromTranscriptRequest, request: Request) -> dict:
    params = {**body.job_params(), "utterances": [u.model_dump() for u in body.utterances]}
    job = _jobs(request).enqueue("from_transcript", body.template, body.header, params, body.project_id)
    return job.public()


@router.post("/from-recording", status_code=202)
def from_recording(body: FromRecordingRequest, request: Request) -> dict:
    tracks_dir = os.path.abspath(body.tracks_dir)
    if not os.path.isdir(tracks_dir):
        raise HTTPException(status_code=404, detail=f"recording folder not found: {body.tracks_dir}")
    if not _has_transcription(tracks_dir):
        raise HTTPException(
            status_code=422,
            detail=f"no transcription in {body.tracks_dir}: expected {SESSION_TRANSCRIPTION_FILE} or track_*_transcription_segments.json + vad_timeline.json",
        )
    params = {**body.job_params(), "tracks_dir": tracks_dir}
    job = _jobs(request).enqueue("from_recording", body.template, body.header, params, body.project_id)
    return job.public()


@router.post("/record-and-generate", status_code=202)
def record_and_generate(body: RecordAndGenerateRequest, request: Request) -> dict:
    if not is_teams_meeting_url(body.meeting_url):
        raise HTTPException(
            status_code=400,
            detail="Only Teams meetings are supported: the url must contain 'teams.live.com' or 'teams.microsoft.com'.",
        )
    runtime = _jobs(request)
    if _recording_in_progress(runtime):
        raise HTTPException(
            status_code=409,
            detail="A meeting is already being recorded (or waiting to be). Try again when that job finishes.",
        )
    params = {**body.job_params(), "meeting_url": body.meeting_url}
    if body.max_recording_seconds:
        params["max_recording_seconds"] = body.max_recording_seconds
    job = runtime.enqueue("record_and_generate", body.template, body.header, params, body.project_id)
    return job.public()


@router.get("/jobs")
def list_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(queued|running|done|failed)$"),
    project_id: str | None = Query(None, min_length=1, max_length=100),
) -> dict:
    jobs = _jobs(request).store.list(limit=limit, status=status, project_id=project_id)
    return {"jobs": [j.public() for j in jobs]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    return _get_job(request, job_id).public()


@router.get("/jobs/{job_id}/result")
def get_result(job_id: str, request: Request) -> dict:
    job = _finished_job(request, job_id)
    return {
        "template": job.template,
        "header": job.header,
        "participants": job.participants or [],
        "minutes": job.minutes or {},
    }


@router.get("/jobs/{job_id}/download")
def download(job_id: str, request: Request):
    job = _finished_job(request, job_id)
    if not job.docx_path or not os.path.isfile(job.docx_path):
        raise HTTPException(status_code=404, detail="the .docx of this job no longer exists on disk")
    return FileResponse(
        job.docx_path,
        media_type=DOCX_MEDIA_TYPE,
        filename=job.result.filename if job.result else os.path.basename(job.docx_path),
    )
