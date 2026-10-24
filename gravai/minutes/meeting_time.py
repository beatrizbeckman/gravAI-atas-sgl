"""
Fills the date and time of the minutes header from the recording itself.

When the SGL starts a meeting it knows the date but not when the meeting will
end, so record-and-generate accepts the header without them and the API fills
every empty header field whose format is a date, a time range or both, with the
moment the bot got into the meeting and the moment it left. Fields the client
did fill are never touched.
"""

import json
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from gravai.minutes.templates import MinutesTemplate

DATE = "DD/MM/AAAA"
TIME_RANGE = "HH:MM – HH:MM"
DATE_AND_TIME_RANGE = f"{DATE} · {TIME_RANGE}"
FILLABLE_FORMATS = (DATE, TIME_RANGE, DATE_AND_TIME_RANGE)

VAD_TIMELINE_FILE = "vad_timeline.json"


def fillable_fields(template: MinutesTemplate) -> set[str]:
    """Header keys the recording can fill (by their format), so the client may leave them out."""
    return {f.key for f in template.header if f.format in FILLABLE_FORMATS}


def recording_span(tracks_dir: str) -> tuple[datetime, datetime] | None:
    """When the bot was inside the meeting, from the timeline the recorder writes; None if unavailable."""
    try:
        with open(os.path.join(tracks_dir, VAD_TIMELINE_FILE), encoding="utf-8") as f:
            meta = json.load(f)["meta"]
        start, end = meta["page_start_ms"], meta["page_end_ms"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(start, int | float) or not isinstance(end, int | float) or end < start:
        return None
    return datetime.fromtimestamp(start / 1000, UTC), datetime.fromtimestamp(end / 1000, UTC)


def fill_meeting_time(template: MinutesTemplate, header: dict, start: datetime, end: datetime, timezone: str) -> dict:
    """A copy of header with the empty date/time fields filled, in the given IANA timezone."""
    tz = ZoneInfo(timezone)
    start, end = start.astimezone(tz), end.astimezone(tz)
    values = {
        DATE: f"{start:%d/%m/%Y}",
        TIME_RANGE: f"{start:%H:%M} – {end:%H:%M}",
        DATE_AND_TIME_RANGE: f"{start:%d/%m/%Y} · {start:%H:%M} – {end:%H:%M}",
    }
    filled = dict(header)
    for field in template.header:
        if field.format in values and not str(filled.get(field.key) or "").strip():
            filled[field.key] = values[field.format]
    return filled
