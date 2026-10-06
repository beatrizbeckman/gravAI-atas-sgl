import json
import os

import pytest

from gravai.jobs import executors
from gravai.jobs.store import JobStore
from gravai.jobs.worker import JobWorker


def seg(start, end, text):
    return {"id": 0, "start": start, "end": end, "text": text, "no_speech_prob": 0.0}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake LLM, recordings and minutes under tmp_path."""
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("SAVE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def store():
    s = JobStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def worker(store):
    return JobWorker(store, executors.EXECUTORS)


def _write_recording(folder, speakers: dict[str, list[dict]]):
    folder.mkdir(parents=True, exist_ok=True)
    tracks = {}
    for i, (name, segments) in enumerate(speakers.items()):
        pid = f"speaking-element-{i}"
        path = folder / f"track_{pid}_transcription_segments.json"
        path.write_text(json.dumps(segments), encoding="utf-8")
        tracks[pid] = {
            "participant_name": name,
            "transcription": {"transcription_segments_file_path": f"/app/tmp/x_tracks/{path.name}"},
        }
    (folder / "session_transcription.json").write_text(json.dumps({"tracks": tracks}), encoding="utf-8")


def test_from_transcript_writes_the_docx_under_save_dir(env, store, worker, meeting, speakers):
    job = store.create("from_transcript", "dell", meeting["header"], {"utterances": meeting["utterances"]})

    done = worker.run(job.id)

    assert done.status == "done", done.error
    assert done.result.llm_model == "fake" and done.result.parts == 1
    assert done.result.participants == speakers
    assert done.result.download_url == f"/minutes/jobs/{job.id}/download"
    assert done.result.filename.startswith("ata_dell_") and done.result.filename.endswith(
        "_controle-remoto-universal.docx"
    )
    assert done.docx_path == os.path.join(str(env), "minutes", job.id, done.result.filename)
    assert os.path.getsize(done.docx_path) > 0
    assert set(done.minutes) == {
        "topicos",
        "resumo",
        "finalizado",
        "em_andamento",
        "ideias_propostas",
        "duvidas",
        "pendencias",
        "decisoes",
        "plano_acao",
        "proxima_reuniao",
    }


def test_from_transcript_with_custom_template_and_participants(env, store, worker, short_meeting):
    params = {
        "utterances": short_meeting["utterances"],
        "participants": ["Equipe Dell", "LaCInA"],
        "custom": {"instructions": "Resuma."},
    }
    job = store.create("from_transcript", "custom", {"projeto": "X", "data": "01/10/2026"}, params)
    done = worker.run(job.id)
    assert done.status == "done", done.error
    assert done.participants == ["Equipe Dell", "LaCInA"] and set(done.minutes) == {"conteudo"}


def test_from_recording_normalizes_the_tracks_first(env, store, worker):
    folder = env / "abc_tracks"
    _write_recording(
        folder,
        {
            "Ana": [
                seg(0.0, 2.0, "Bom dia, vamos começar a daily."),
                seg(10.0, 12.0, "Legendas pela comunidade Amara.org"),
            ],
            "Bruno": [seg(3.0, 5.0, "Ontem terminei o endpoint de anexos.")],
        },
    )
    stages = []
    store_update = store.update

    def spy(job_id, **fields):
        if fields.get("stage"):
            stages.append(fields["stage"])
        return store_update(job_id, **fields)

    store.update = spy
    job = store.create("from_recording", "daily", {"projeto": "X", "data": "01/10/2026"}, {"tracks_dir": str(folder)})
    done = worker.run(job.id)

    assert done.status == "done", done.error
    assert stages == ["normalizing", "generating", "rendering"]
    assert done.result.utterances == 2 and done.result.participants == ["Ana", "Bruno"]


def test_from_recording_with_bad_folder_is_transcription_failed(env, store, worker):
    job = store.create(
        "from_recording", "daily", {"projeto": "X", "data": "01/10/2026"}, {"tracks_dir": str(env / "missing_tracks")}
    )
    assert worker.run(job.id).error.code == "transcription_failed"

    empty = env / "empty_tracks"
    empty.mkdir()
    job = store.create("from_recording", "daily", {"projeto": "X", "data": "01/10/2026"}, {"tracks_dir": str(empty)})
    failed = worker.run(job.id)
    assert failed.error.code == "empty_transcript"


def test_record_and_generate_runs_record_transcribe_normalize_generate(env, store, worker, monkeypatch):
    folder = env / "rec_tracks"
    calls = []

    class FakeRecorder:
        def record_meeting_with_ws_audio_server(self, url, max_seconds=None):
            calls.append(("record", url, max_seconds))
            _write_recording(folder, {"Ana": [seg(0.0, 2.0, "Fala da Ana.")]})
            return str(folder)

    def fake_transcribe(tracks_dir):
        calls.append(("transcribe", tracks_dir))

    monkeypatch.setattr("gravai.recording.teams.TeamsMeetingRecorder", FakeRecorder)
    monkeypatch.setattr(executors, "_transcribe", fake_transcribe)

    job = store.create(
        "record_and_generate",
        "daily",
        {"projeto": "X", "data": "01/10/2026"},
        {"meeting_url": "https://teams.live.com/meet/1", "max_recording_seconds": 900},
    )
    done = worker.run(job.id)

    assert done.status == "done", done.error
    assert calls == [("record", "https://teams.live.com/meet/1", 900), ("transcribe", str(folder))]
    assert not executors.RECORDING_LOCK.locked()


def test_record_and_generate_failures_are_recording_failed(env, store, worker, monkeypatch):
    class BrokenRecorder:
        def record_meeting_with_ws_audio_server(self, url, max_seconds=None):
            raise RuntimeError("Rejected from joining the meeting")

    monkeypatch.setattr("gravai.recording.teams.TeamsMeetingRecorder", BrokenRecorder)
    job = store.create(
        "record_and_generate",
        "daily",
        {"projeto": "X", "data": "01/10/2026"},
        {"meeting_url": "https://teams.live.com/meet/1"},
    )
    failed = worker.run(job.id)
    assert failed.error.code == "recording_failed" and "Rejected" in failed.error.message
    assert not executors.RECORDING_LOCK.locked()

    executors.RECORDING_LOCK.acquire()
    try:
        job = store.create(
            "record_and_generate",
            "daily",
            {"projeto": "X", "data": "01/10/2026"},
            {"meeting_url": "https://teams.live.com/meet/1"},
        )
        assert "another meeting" in worker.run(job.id).error.message
    finally:
        executors.RECORDING_LOCK.release()


def test_llm_failure_in_a_job_keeps_the_contract_code(env, store, worker, monkeypatch, short_meeting):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")  # nothing listens here
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "2")
    job = store.create("from_transcript", "dell", short_meeting["header"], {"utterances": short_meeting["utterances"]})
    failed = worker.run(job.id)
    assert failed.status == "failed" and failed.error.code == "llm_unreachable"
