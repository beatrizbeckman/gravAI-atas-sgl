from gravai.recording import pipeline


def test_request_stop_sets_the_event_of_the_running_recording(monkeypatch):
    seen = {}

    class FakeRecorder:
        def record_meeting_with_ws_audio_server(self, meeting_url, max_seconds=None, stop_event=None):
            # While "recording", the API asks to stop; the recorder sees the event set.
            assert pipeline.request_stop() is True
            seen["stopped"] = stop_event.is_set()
            return "/tmp/session_tracks"

    monkeypatch.setattr("gravai.recording.teams.TeamsMeetingRecorder", FakeRecorder)
    assert pipeline.request_stop() is False  # nothing recording yet
    assert pipeline.record_meeting("https://teams.live.com/meet/1") == "/tmp/session_tracks"
    assert seen == {"stopped": True}
    assert pipeline.request_stop() is False  # the event is gone with the recording
    assert not pipeline.RECORDING_LOCK.locked()
