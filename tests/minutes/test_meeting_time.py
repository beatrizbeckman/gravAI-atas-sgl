import json
from datetime import UTC, datetime

from gravai.minutes.meeting_time import fill_meeting_time, fillable_fields, recording_span
from gravai.minutes.templates import load_template

# 13:05 to 14:10 UTC is 10:05 to 11:10 in Campina Grande (UTC-3).
START = datetime(2026, 10, 24, 13, 5, tzinfo=UTC)
END = datetime(2026, 10, 24, 14, 10, tzinfo=UTC)


def test_fillable_fields_follow_the_header_formats():
    assert fillable_fields(load_template("dell")) == {"data", "horario"}
    assert fillable_fields(load_template("daily")) == {"data"}


def test_empty_fields_are_filled_in_the_meeting_timezone():
    dell = fill_meeting_time(load_template("dell"), {"projeto": "X"}, START, END, "America/Fortaleza")
    assert dell == {"projeto": "X", "data": "24/10/2026", "horario": "10:05 – 11:10"}
    daily = fill_meeting_time(load_template("daily"), {"projeto": "X", "data": " "}, START, END, "America/Fortaleza")
    assert daily["data"] == "24/10/2026 · 10:05 – 11:10"


def test_what_the_client_sent_is_kept():
    header = {"projeto": "X", "data": "23/10/2026", "horario": ""}
    filled = fill_meeting_time(load_template("dell"), header, START, END, "America/Fortaleza")
    assert filled["data"] == "23/10/2026" and filled["horario"] == "10:05 – 11:10"
    assert header["horario"] == ""  # the input is not changed


def test_recording_span_reads_the_vad_timeline(tmp_path):
    assert recording_span(str(tmp_path)) is None
    meta = {"page_start_ms": START.timestamp() * 1000, "page_end_ms": END.timestamp() * 1000}
    (tmp_path / "vad_timeline.json").write_text(json.dumps({"meta": meta, "events": []}), encoding="utf-8")
    assert recording_span(str(tmp_path)) == (START, END)
    (tmp_path / "vad_timeline.json").write_text(json.dumps({"meta": {"page_start_ms": None}}), encoding="utf-8")
    assert recording_span(str(tmp_path)) is None
