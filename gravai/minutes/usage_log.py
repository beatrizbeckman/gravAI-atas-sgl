"""
Token usage of each minutes generation, to size the LLM plan: how many tokens a
short and a long meeting cost, and how big the largest single request gets.

After every generation the jobs (and the CLI) print a short report to the
terminal and append one row to <SAVE_DIR>/llm_usage.csv, so the numbers of many
meetings can be compared later in a spreadsheet.
"""

import csv
import os
import threading
from datetime import datetime

from gravai.config import Settings
from gravai.minutes.generate import GenerationResult

CSV_NAME = "llm_usage.csv"
CSV_COLUMNS = (
    "finished_at",
    "job_id",
    "kind",
    "project_id",
    "template",
    "llm_model",
    "meeting_minutes",
    "utterances",
    "transcript_chars",
    "parts",
    "llm_calls",
    "retries",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "largest_call_tokens",
    "largest_prompt_tokens",
    "tokens_per_meeting_hour",
    "tokens_estimated",
    "generation_seconds",
)
_CSV_LOCK = threading.Lock()


def csv_path() -> str:
    return os.path.join(Settings().SAVE_DIR, CSV_NAME)


def tokens_per_hour(total_tokens: int, minutes: float) -> int | None:
    """Total tokens scaled to one hour of meeting; None when the meeting length is unknown."""
    return round(total_tokens * 60 / minutes) if minutes > 0 else None


def usage_row(result: GenerationResult, job_id: str = "", kind: str = "", project_id: str | None = None) -> dict:
    usage = result.usage
    return {
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "job_id": job_id,
        "kind": kind,
        "project_id": project_id or "",
        "template": result.template.id,
        "llm_model": result.llm_model,
        "meeting_minutes": result.meeting_minutes,
        "utterances": result.utterances,
        "transcript_chars": result.transcript_chars,
        "parts": result.parts,
        "llm_calls": result.llm_calls,
        "retries": result.retries,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
        "largest_call_tokens": usage.largest_call_tokens,
        "largest_prompt_tokens": usage.largest_prompt_tokens,
        "tokens_per_meeting_hour": tokens_per_hour(usage.total_tokens, result.meeting_minutes) or "",
        "tokens_estimated": usage.estimated,
        "generation_seconds": result.generation_seconds,
    }


def append_csv(row: dict, path: str | None = None) -> str:
    """Appends one row, writing the header first when the file is new. Returns the path."""
    path = path or csv_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with _CSV_LOCK:
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if new:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})
    return path


def _n(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_report(result: GenerationResult, job_id: str = "", saved_to: str | None = None) -> str:
    """The block printed to the terminal after each generation."""
    usage = result.usage
    calls_detail = " · ".join(
        f"#{i} {_n(c['prompt_tokens'])}+{_n(c['completion_tokens'])}" for i, c in enumerate(usage.calls, 1)
    )
    what = f"{result.parts} part(s)" + (" + merge" if result.parts > 1 else "")
    per_hour = tokens_per_hour(usage.total_tokens, result.meeting_minutes)
    lines = [
        f"===== LLM usage{f' · job {job_id[:8]}' if job_id else ''} · {result.template.id} · {result.llm_model} =====",
        f"meeting       {result.meeting_minutes} min · {result.utterances} utterances · {_n(result.transcript_chars)} chars",
        f"llm calls     {result.llm_calls} ({what}, {result.retries} retry(ies)) · {result.generation_seconds} s",
        f"tokens        input {_n(usage.prompt_tokens)} · output {_n(usage.completion_tokens)}"
        f" (reasoning {_n(usage.reasoning_tokens)}) · total {_n(usage.total_tokens)}",
        f"per hour      {_n(per_hour)} tokens per hour of meeting" if per_hour else "per hour      -",
        f"largest input {_n(usage.largest_prompt_tokens)} tokens (one request's input must fit the plan's tokens-per-minute limit)",
        f"largest call  {_n(usage.largest_call_tokens)} tokens (input+output)",
        f"per call      {calls_detail}  (input+output)",
    ]
    if usage.estimated:
        lines.append("note          ESTIMATED from characters: the provider reported no token usage")
    if saved_to:
        lines.append(f"saved to      {saved_to}")
    lines.append("=" * 60)
    return "\n".join(lines)


def log_generation(
    result: GenerationResult, job_id: str = "", kind: str = "", project_id: str | None = None, path: str | None = None
) -> None:
    """Prints the report and appends the CSV row. Never fails the generation: the minutes are already written."""
    saved_to = None
    try:
        saved_to = append_csv(usage_row(result, job_id, kind, project_id), path)
    except OSError as exc:
        print(f"[usage] could not write the usage CSV: {exc}", flush=True)
    print(format_report(result, job_id, saved_to), flush=True)
