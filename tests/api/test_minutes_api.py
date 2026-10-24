import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gravai.api.minutes import router
from gravai.jobs import executors
from gravai.jobs.runtime import JobsRuntime
from gravai.jobs.store import JobStore


def seg(start, end, text):
    return {"id": 0, "start": start, "end": end, "text": text, "no_speech_prob": 0.0}


def write_recording(folder, speakers):
    folder.mkdir(parents=True, exist_ok=True)
    tracks = {}
    for i, (name, segments) in enumerate(speakers.items()):
        pid = f"speaking-element-{i}"
        path = folder / f"track_{pid}_transcription_segments.json"
        path.write_text(json.dumps(segments), encoding="utf-8")
        tracks[pid] = {"participant_name": name, "transcription": {"transcription_segments_file_path": str(path)}}
    (folder / "session_transcription.json").write_text(json.dumps({"tracks": tracks}), encoding="utf-8")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("SAVE_DIR", str(tmp_path))
    rt = JobsRuntime(JobStore(":memory:"))
    yield rt  # the worker thread is not started: tests run jobs with rt.worker.run(id)
    rt.store.close()


@pytest.fixture
def client(runtime):
    app = FastAPI()
    app.include_router(router)
    app.state.jobs = runtime
    return TestClient(app)


@pytest.fixture
def dell_body(meeting):
    return {"template": "dell", "header": meeting["header"], "utterances": meeting["utterances"]}


# ------------------------------------------------------------- templates


def test_templates_lists_every_template_with_its_header_fields(client):
    data = client.get("/minutes/templates").json()["templates"]
    assert [t["id"] for t in data] == ["custom", "daily", "dell", "professores"]
    dell = next(t for t in data if t["id"] == "dell")
    assert dell["name"] == "Ata Dell" and dell["description"]
    assert [(h["key"], h["required"]) for h in dell["header"]] == [
        ("projeto", True),
        ("numero", False),
        ("data", True),
        ("horario", False),
    ]
    assert dell["header"][2]["format"] == "DD/MM/AAAA"
    assert dell["participants"] == {"source": "transcript", "label": "Participantes"}
    assert {s["key"] for s in dell["sections"]} >= {"topicos", "decisoes", "plano_acao"}
    prof = next(t for t in data if t["id"] == "professores")
    tipo = next(h for h in prof["header"] if h["key"] == "tipo")
    assert tipo["values"] == ["Orientação", "Apresentação"] and tipo["default"] == "Orientação"


# ------------------------------------------------------- from-transcript


def test_from_transcript_full_cycle(client, runtime, dell_body, speakers):
    created = client.post("/minutes/from-transcript", json=dell_body)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["status"] == "queued" and job["kind"] == "from_transcript" and job["template"] == "dell"
    assert set(job) == {
        "id",
        "kind",
        "status",
        "stage",
        "template",
        "header",
        "project_id",
        "created_at",
        "updated_at",
        "finished_at",
        "result",
        "error",
    }
    assert runtime.worker.pending == 1

    # Not done yet: result and download refuse with 409.
    assert client.get(f"/minutes/jobs/{job['id']}/download").status_code == 409
    assert client.get(f"/minutes/jobs/{job['id']}/result").status_code == 409

    runtime.worker.run(job["id"])

    done = client.get(f"/minutes/jobs/{job['id']}").json()
    assert done["status"] == "done" and done["error"] is None and done["finished_at"]
    assert done["result"]["download_url"] == f"/minutes/jobs/{job['id']}/download"
    assert done["result"]["participants"] == speakers
    assert done["result"]["llm_model"] == "fake" and done["result"]["parts"] == 1
    assert done["result"]["utterances"] == len(dell_body["utterances"])

    result = client.get(f"/minutes/jobs/{job['id']}/result").json()
    assert result["template"] == "dell" and result["participants"] == speakers
    assert result["minutes"]["plano_acao"][0]["id"] == "A1"

    download = client.get(f"/minutes/jobs/{job['id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert done["result"]["filename"] in download.headers["content-disposition"]
    assert download.content[:2] == b"PK"  # a .docx is a zip


def test_from_transcript_with_custom_template_and_participants(client, runtime, dell_body):
    body = {
        "template": "custom",
        "header": {"projeto": "Retro", "data": "01/10/2026"},
        "participants": ["Time A"],
        "custom": {
            "sections": [{"key": "bom", "title": "Bom", "type": "bullets", "instructions": "Pontos positivos."}]
        },
        "utterances": dell_body["utterances"],
    }
    job = client.post("/minutes/from-transcript", json=body).json()
    runtime.worker.run(job["id"])
    result = client.get(f"/minutes/jobs/{job['id']}/result").json()
    assert set(result["minutes"]) == {"bom"} and result["participants"] == ["Time A"]


@pytest.mark.parametrize(
    "patch, match",
    [
        ({"template": "nope"}, "unknown template"),
        ({"header": {"data": "01/10/2026"}}, "missing required header fields"),
        ({"template": "custom"}, "needs the 'custom' object"),
        ({"custom": {"instructions": "x"}}, "only accepted with template 'custom'"),
        ({"template": "custom", "custom": {}}, "exactly one of"),
        (
            {
                "template": "custom",
                "header": {"projeto": "X", "data": "x"},
                "custom": {"sections": [{"key": "Bad Key", "title": "T", "type": "bullets", "instructions": "x"}]},
            },
            "snake_case",
        ),
        ({"utterances": []}, "at least 1 item"),
        ({"utterances": [{"speaker": "A", "start": 1, "end": 1, "text": "x"}]}, "no usable item"),
        ({"utterances": [{"speaker": "", "start": 0, "end": 1, "text": "x"}]}, "at least 1 character"),
    ],
)
def test_from_transcript_validation_errors_are_422(client, runtime, dell_body, patch, match):
    response = client.post("/minutes/from-transcript", json={**dell_body, **patch})
    assert response.status_code == 422, response.text
    assert match in response.text
    assert runtime.store.list() == []  # nothing was created


# -------------------------------------------------------- from-recording


def test_from_recording_normalizes_and_generates(client, runtime, tmp_path):
    folder = tmp_path / "abc_tracks"
    write_recording(folder, {"Ana": [seg(0.0, 2.0, "Bom dia.")], "Bruno": [seg(3.0, 5.0, "Terminei o endpoint.")]})
    body = {"template": "daily", "header": {"projeto": "X", "data": "01/10/2026"}, "tracks_dir": str(folder)}

    job = client.post("/minutes/from-recording", json=body).json()
    assert job["kind"] == "from_recording"
    runtime.worker.run(job["id"])
    done = client.get(f"/minutes/jobs/{job['id']}").json()
    assert done["status"] == "done", done["error"]
    assert done["result"]["utterances"] == 2 and done["result"]["participants"] == ["Ana", "Bruno"]


def test_from_recording_folder_errors(client, tmp_path):
    body = {"template": "daily", "header": {"projeto": "X", "data": "01/10/2026"}}
    assert (
        client.post("/minutes/from-recording", json={**body, "tracks_dir": str(tmp_path / "missing")}).status_code
        == 404
    )
    empty = tmp_path / "empty_tracks"
    empty.mkdir()
    response = client.post("/minutes/from-recording", json={**body, "tracks_dir": str(empty)})
    assert response.status_code == 422 and "no transcription" in response.text


# --------------------------------------------------- record-and-generate


def test_record_and_generate_validations_and_queueing(client, runtime):
    body = {
        "template": "daily",
        "header": {"projeto": "X", "data": "01/10/2026"},
        "meeting_url": "https://teams.live.com/meet/1",
        "max_recording_seconds": 900,
    }

    assert (
        client.post(
            "/minutes/record-and-generate", json={**body, "meeting_url": "https://meet.google.com/x"}
        ).status_code
        == 400
    )
    assert client.post("/minutes/record-and-generate", json={**body, "max_recording_seconds": 5}).status_code == 422

    executors.RECORDING_LOCK.acquire()
    try:
        assert client.post("/minutes/record-and-generate", json=body).status_code == 409
    finally:
        executors.RECORDING_LOCK.release()

    created = client.post("/minutes/record-and-generate", json=body)
    assert created.status_code == 202, created.text
    job = runtime.store.get(created.json()["id"])
    assert job.kind == "record_and_generate" and job.params == {
        "meeting_url": "https://teams.live.com/meet/1",
        "max_recording_seconds": 900,
    }

    # A second one while the first is still queued is refused.
    assert client.post("/minutes/record-and-generate", json=body).status_code == 409


def test_callback_url_is_kept_in_the_job_and_must_be_http(client, runtime, dell_body):
    created = client.post(
        "/minutes/from-transcript", json={**dell_body, "callback_url": "https://sgl.lab/atas/webhook"}
    )
    assert created.status_code == 202
    assert runtime.store.get(created.json()["id"]).params["callback_url"] == "https://sgl.lab/atas/webhook"
    assert client.post("/minutes/from-transcript", json={**dell_body, "callback_url": "ftp://x"}).status_code == 422


def test_record_and_generate_may_leave_date_and_time_to_the_recording(client, runtime, dell_body):
    body = {"template": "dell", "header": {"projeto": "X"}, "meeting_url": "https://teams.live.com/meet/1"}
    assert client.post("/minutes/record-and-generate", json=body).status_code == 202
    # Without a recording there is nothing to take the date from.
    no_date = {**dell_body, "header": {"projeto": "X"}}
    assert client.post("/minutes/from-transcript", json=no_date).status_code == 422
    # The project is never filled by the API.
    assert client.post("/minutes/record-and-generate", json={**body, "header": {}}).status_code == 422


def test_stop_ends_the_recording_of_a_running_job(client, runtime, monkeypatch):
    body = {
        "template": "daily",
        "header": {"projeto": "X", "data": "01/10/2026"},
        "meeting_url": "https://teams.live.com/meet/1",
    }
    job_id = client.post("/minutes/record-and-generate", json=body).json()["id"]
    calls = []
    monkeypatch.setattr("gravai.recording.pipeline.request_stop", lambda: calls.append(1) or True)

    # Still queued: nothing to stop yet.
    assert client.post(f"/minutes/jobs/{job_id}/stop").status_code == 409
    runtime.store.update(job_id, status="running", stage="recording")
    stopped = client.post(f"/minutes/jobs/{job_id}/stop")
    assert stopped.status_code == 202 and stopped.json()["id"] == job_id
    assert calls == [1]

    # Already past the recording, or a job that never records.
    runtime.store.update(job_id, stage="transcribing")
    assert client.post(f"/minutes/jobs/{job_id}/stop").status_code == 409
    other = runtime.store.create("from_transcript", "dell", {}, {})
    runtime.store.update(other.id, status="running", stage="recording")
    assert client.post(f"/minutes/jobs/{other.id}/stop").status_code == 409
    assert client.post("/minutes/jobs/does-not-exist/stop").status_code == 404


def test_stop_while_the_bot_is_still_starting_asks_to_retry(client, runtime, monkeypatch):
    job = runtime.store.create("record_and_generate", "daily", {}, {"meeting_url": "https://teams.live.com/meet/1"})
    runtime.store.update(job.id, status="running", stage="recording")
    monkeypatch.setattr("gravai.recording.pipeline.request_stop", lambda: False)
    response = client.post(f"/minutes/jobs/{job.id}/stop")
    assert response.status_code == 409 and "try again" in response.json()["detail"]


# ----------------------------------------------------------------- jobs


def test_jobs_listing_and_404(client, runtime, dell_body):
    ids = [client.post("/minutes/from-transcript", json=dell_body).json()["id"] for _ in range(3)]
    runtime.worker.run(ids[0])

    listed = client.get("/minutes/jobs").json()["jobs"]
    assert [j["id"] for j in listed] == ids[::-1]
    assert [j["id"] for j in client.get("/minutes/jobs?limit=1").json()["jobs"]] == [ids[2]]
    assert [j["id"] for j in client.get("/minutes/jobs?status=done").json()["jobs"]] == [ids[0]]
    assert client.get("/minutes/jobs?status=bogus").status_code == 422
    assert client.get("/minutes/jobs/does-not-exist").status_code == 404
    assert client.get("/minutes/jobs/does-not-exist/download").status_code == 404


def test_jobs_are_listed_per_project(client, runtime, dell_body):
    first = client.post("/minutes/from-transcript", json={**dell_body, "project_id": "sgl-7"}).json()
    client.post("/minutes/from-transcript", json={**dell_body, "project_id": "sgl-8"})
    client.post("/minutes/from-transcript", json=dell_body)  # clients that do not send it keep working

    assert first["project_id"] == "sgl-7"
    runtime.worker.run(first["id"])
    assert client.get(f"/minutes/jobs/{first['id']}").json()["project_id"] == "sgl-7"
    listed = client.get("/minutes/jobs?project_id=sgl-7").json()["jobs"]
    assert [j["id"] for j in listed] == [first["id"]]
    assert client.get("/minutes/jobs?project_id=sgl-7&status=queued").json()["jobs"] == []
    assert len(client.get("/minutes/jobs").json()["jobs"]) == 3
    assert client.post("/minutes/from-transcript", json={**dell_body, "project_id": ""}).status_code == 422


def test_failed_job_is_reported_with_its_code(client, runtime, dell_body, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "2")
    job = client.post("/minutes/from-transcript", json=dell_body).json()
    runtime.worker.run(job["id"])

    failed = client.get(f"/minutes/jobs/{job['id']}").json()
    assert failed["status"] == "failed" and failed["error"]["code"] == "llm_unreachable" and failed["result"] is None
    download = client.get(f"/minutes/jobs/{job['id']}/download")
    assert download.status_code == 409 and "llm_unreachable" in download.json()["detail"]


def test_end_to_end_with_the_worker_thread_and_polling(client, runtime, dell_body):
    runtime.start()
    try:
        job = client.post("/minutes/from-transcript", json=dell_body).json()
        deadline = time.time() + 15
        while time.time() < deadline:
            job = client.get(f"/minutes/jobs/{job['id']}").json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.1)
        assert job["status"] == "done", job
        assert client.get(job["result"]["download_url"]).status_code == 200
    finally:
        runtime.worker.stop(timeout=5)
