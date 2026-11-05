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


# Texts Teams shows when nobody else is in the call (English UI of the headless browser, Portuguese too).
ALONE_TEXTS = (
    "waiting for others to join",
    "you're the only one here",
    "you are the only one here",
    "aguardando outras pessoas",
    "você é o único",
    "você é a única",
)
EMPTY_MEETING_GRACE_SECONDS = 900


class AloneWatcher:
    """
    Decides when the bot should leave because it is alone in the call. People
    often just leave instead of ending the meeting for everyone; without this the
    bot would record silence (which whisper fills with invented text) until
    MAX_RECORDING_SECONDS. Before anyone else has been seen, the bot waits at
    least EMPTY_MEETING_GRACE_SECONDS, so it does not leave a meeting that has
    not started yet.
    """

    def __init__(self, alone_seconds: int, empty_grace_seconds: int = EMPTY_MEETING_GRACE_SECONDS):
        self.alone_seconds = alone_seconds
        self.empty_grace_seconds = empty_grace_seconds
        self.seen_others = False
        self.alone_since: float | None = None

    def update(self, alone: bool, now: float) -> bool:
        """Feeds one observation; True when it is time to leave."""
        if self.alone_seconds <= 0:
            return False
        if not alone:
            self.seen_others = True
            self.alone_since = None
            return False
        if self.alone_since is None:
            self.alone_since = now
        limit = self.alone_seconds if self.seen_others else max(self.alone_seconds, self.empty_grace_seconds)
        return now - self.alone_since >= limit


def page_says_alone(page_text: str) -> bool:
    text = page_text.lower().replace("’", "'")
    return any(phrase in text for phrase in ALONE_TEXTS)
