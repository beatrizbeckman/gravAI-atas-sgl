"""Small helpers shared by the recorder, the API and the jobs."""

import json
from urllib.parse import urlparse

TEAMS_DOMAINS = ("teams.live.com", "teams.microsoft.com")


def is_teams_meeting_url(url: str) -> bool:
    return any(domain in url for domain in TEAMS_DOMAINS)


def _meeting_origin(meeting_url: str) -> str:
    parsed = urlparse(meeting_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_vad_timeline(path: str, meta: dict, events: list[dict]) -> None:
    payload = {"meta": meta, "events": events}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
