"""
The job object of the API contract (docs/API_MINUTES.md, section 4.1) plus the
internal fields the worker needs (request parameters, paths, the minutes JSON).
"""

from datetime import UTC, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

JobKind = Literal["from_transcript", "from_recording", "record_and_generate"]
JobStatus = Literal["queued", "running", "done", "failed"]
JobStage = Literal["recording", "transcribing", "normalizing", "generating", "rendering"]

STATUSES: tuple[str, ...] = ("queued", "running", "done", "failed")


def utcnow() -> str:
    """ISO 8601 in UTC with a Z suffix, second precision: 2026-10-01T14:03:12Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobError(BaseModel):
    code: str
    message: str


class JobResult(BaseModel):
    download_url: str
    filename: str
    participants: list[str]
    utterances: int
    parts: int
    llm_model: str
    generation_seconds: float


class Job(BaseModel):
    id: str
    kind: JobKind
    status: JobStatus = "queued"
    stage: JobStage | None = None
    template: str
    header: dict
    created_at: str
    updated_at: str
    finished_at: str | None = None
    result: JobResult | None = None
    error: JobError | None = None
    # Internal, not part of the public object: what the executor needs and what it produced.
    params: dict = Field(default_factory=dict)
    docx_path: str | None = None
    minutes: dict | None = None
    participants: list[str] | None = None

    PUBLIC_FIELDS: ClassVar[tuple[str, ...]] = (
        "id",
        "kind",
        "status",
        "stage",
        "template",
        "header",
        "created_at",
        "updated_at",
        "finished_at",
        "result",
        "error",
    )

    def public(self) -> dict:
        """The object returned by the API."""
        return self.model_dump(include=set(self.PUBLIC_FIELDS))
