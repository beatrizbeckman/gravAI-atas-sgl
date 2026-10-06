"""
Access to the meeting dataset in datasets/reunioes/: one folder per meeting with
transcricao.json (template, header, utterances, meta), gabarito.md and
original.json. Used by the demo page, the experiments runner and the tests, so
the path and the file layout live in one place.
"""

from __future__ import annotations

import json
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repository root
DATASET_DIR = os.path.join(ROOT_DIR, "datasets", "reunioes")
TRANSCRIPT_FILE = "transcricao.json"
ANSWER_KEY_FILE = "gabarito.md"


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data, indent: int = 1) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def list_meetings(dataset_dir: str = DATASET_DIR) -> list[str]:
    """Meeting ids (folder names) that have a transcript, sorted."""
    if not os.path.isdir(dataset_dir):
        return []
    return sorted(name for name in os.listdir(dataset_dir) if os.path.isfile(transcript_path(name, dataset_dir)))


def transcript_path(meeting_id: str, dataset_dir: str = DATASET_DIR) -> str:
    return os.path.join(dataset_dir, meeting_id, TRANSCRIPT_FILE)


def load_meeting(meeting_id: str, dataset_dir: str = DATASET_DIR) -> dict:
    """The transcript file as a dict: template, header, utterances and meta."""
    path = transcript_path(meeting_id, dataset_dir)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"meeting '{meeting_id}' not found in {dataset_dir}. Available: {', '.join(list_meetings(dataset_dir))}"
        )
    return read_json(path)


def describe_meeting(meeting: dict) -> str:
    """One-line label for pickers: phase, id and size."""
    meta = meeting.get("meta", {})
    phase = meta.get("phase") or meeting.get("template", "")
    return f"{phase} · {meta.get('meeting_id', '?')} ({len(meeting['utterances'])} falas)"
