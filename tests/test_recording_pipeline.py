import threading

import pytest

from gravai.recording import pipeline


def test_request_stop_sets_the_event_of_that_recording_only(monkeypatch):
    seen = {}

    class FakeRecorder:
        def record_meeting_with_ws_audio_server(self, meeting_url, max_seconds=None, stop_event=None):
            # While "recording", the API asks to stop this job; another key is not affected.
            assert pipeline.request_stop("other-job") is False
            assert pipeline.request_stop("job-1") is True
            seen["stopped"] = stop_event.is_set()
            return "/tmp/session_tracks"

    monkeypatch.setattr("gravai.recording.teams.TeamsMeetingRecorder", FakeRecorder)
    assert pipeline.request_stop("job-1") is False  # nothing recording yet
    assert pipeline.record_meeting("https://teams.live.com/meet/1", key="job-1") == "/tmp/session_tracks"
    assert seen == {"stopped": True}
    assert pipeline.request_stop("job-1") is False  # gone with the recording
    assert pipeline.active_recordings() == 0


def test_meetings_record_at_the_same_time_up_to_the_limit(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RECORDINGS", "2")
    inside = threading.Barrier(3)  # two recordings + the test
    leave = threading.Event()

    class FakeRecorder:
        def record_meeting_with_ws_audio_server(self, meeting_url, max_seconds=None, stop_event=None):
            inside.wait(timeout=5)
            leave.wait(timeout=5)
            return f"/tmp/{meeting_url[-1]}_tracks"

    monkeypatch.setattr("gravai.recording.teams.TeamsMeetingRecorder", FakeRecorder)
    results = {}
    threads = [
        threading.Thread(
            target=lambda k=k: results.update({k: pipeline.record_meeting(f"https://teams.live.com/meet/{k}", key=k)})
        )
        for k in ("a", "b")
    ]
    for t in threads:
        t.start()
    inside.wait(timeout=5)  # both are recording now
    assert pipeline.active_recordings() == 2
    with pytest.raises(pipeline.RecordingBusy, match="All 2 recorders are busy"):
        pipeline.record_meeting("https://teams.live.com/meet/c", key="c")

    leave.set()
    for t in threads:
        t.join(timeout=5)
    assert results == {"a": "/tmp/a_tracks", "b": "/tmp/b_tracks"}
    assert pipeline.active_recordings() == 0
