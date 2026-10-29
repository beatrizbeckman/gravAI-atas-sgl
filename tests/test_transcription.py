import requests

from gravai.transcription.base import transcribe


class Answer:
    status_code = 200

    def json(self):
        return {"text": "oi", "segments": []}


def test_whisper_is_asked_not_to_carry_text_between_windows(tmp_path, monkeypatch):
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"RIFF")
    sent = {}

    def fake_post(url, files, data, timeout):
        sent.update(url=url, data=data)
        return Answer()

    monkeypatch.setattr(requests, "post", fake_post)
    assert transcribe(str(wav), "whisper", 8080) == {"text": "oi", "segments": []}
    assert sent["url"] == "http://whisper:8080/inference"
    # Without it, silence at the start makes whisper repeat an invented subtitle credit over the speech.
    assert sent["data"]["max_context"] == "0"


def test_whisper_gets_the_language_and_beam_search(tmp_path, monkeypatch):
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"RIFF")
    sent = {}
    monkeypatch.setattr(requests, "post", lambda url, files, data, timeout: sent.update(data) or Answer())
    monkeypatch.setenv("WHISPER_LANGUAGE", "pt")
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "5")

    transcribe(str(wav), "whisper", 8080)

    assert sent["language"] == "pt" and sent["beam_size"] == "5"
