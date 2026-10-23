import sqlite3

import pytest

from gravai.jobs.store import JobStore


@pytest.fixture
def store(tmp_path):
    s = JobStore(str(tmp_path / "jobs.sqlite3"))
    yield s
    s.close()


def test_create_and_get_roundtrip(store):
    job = store.create(
        "from_transcript",
        "dell",
        {"projeto": "X", "data": "01/10/2026"},
        {"utterances": [{"speaker": "A", "start": 0, "end": 1, "text": "oi"}]},
    )

    loaded = store.get(job.id)
    assert loaded == job
    assert loaded.status == "queued" and loaded.stage is None and loaded.result is None and loaded.error is None
    assert loaded.params["utterances"][0]["text"] == "oi"
    assert loaded.created_at == loaded.updated_at and loaded.created_at.endswith("Z")
    assert store.get("nope") is None


def test_public_view_hides_internal_columns(store):
    job = store.create("from_recording", "daily", {"projeto": "X"}, {"tracks_dir": "/x"})
    public = job.public()
    assert set(public) == set(job.PUBLIC_FIELDS)
    assert "params" not in public and "docx_path" not in public and "minutes" not in public


def test_update_sets_updated_at_and_finishing_sets_finished_at(store, monkeypatch):
    clock = iter(["2026-10-01T00:00:01Z", "2026-10-01T00:00:02Z", "2026-10-01T00:00:03Z", "2026-10-01T00:00:04Z"])
    monkeypatch.setattr("gravai.jobs.store.utcnow", lambda: next(clock))
    job = store.create("from_transcript", "dell", {}, {})

    running = store.update(job.id, status="running", stage="generating")
    assert running.status == "running" and running.stage == "generating"
    assert running.updated_at == "2026-10-01T00:00:02Z" and running.finished_at is None

    done = store.update(
        job.id,
        status="done",
        result={
            "download_url": "/d",
            "filename": "a.docx",
            "participants": ["A"],
            "utterances": 1,
            "parts": 1,
            "llm_model": "fake",
            "generation_seconds": 0.1,
        },
        minutes={"resumo": "x"},
    )
    assert done.finished_at is not None and done.stage is None
    assert done.result.filename == "a.docx" and done.minutes == {"resumo": "x"}


def test_update_rejects_unknown_job_and_status(store):
    job = store.create("from_transcript", "dell", {}, {})
    with pytest.raises(KeyError):
        store.update("missing", stage="generating")
    with pytest.raises(ValueError):
        store.update(job.id, status="exploded")


def test_list_is_newest_first_with_limit_and_status_filter(store, monkeypatch):
    clock = iter(f"2026-10-01T00:00:0{i}Z" for i in range(1, 9))
    monkeypatch.setattr("gravai.jobs.store.utcnow", lambda: next(clock))
    a = store.create("from_transcript", "dell", {}, {})
    b = store.create("from_transcript", "dell", {}, {})
    c = store.create("from_transcript", "dell", {}, {})
    store.update(b.id, status="failed", error={"code": "internal", "message": "x"})

    assert [j.id for j in store.list()] == [c.id, b.id, a.id]
    assert [j.id for j in store.list(limit=2)] == [c.id, b.id]
    assert [j.id for j in store.list(status="queued")] == [c.id, a.id]
    assert store.list(status="failed")[0].error.code == "internal"


def test_recover_on_startup_fails_running_and_returns_queued_oldest_first(store, monkeypatch):
    clock = iter(f"2026-10-01T00:00:{i:02d}Z" for i in range(1, 20))
    monkeypatch.setattr("gravai.jobs.store.utcnow", lambda: next(clock))
    q1 = store.create("from_transcript", "dell", {}, {})
    r = store.create("from_transcript", "dell", {}, {})
    q2 = store.create("from_transcript", "dell", {}, {})
    store.update(r.id, status="running", stage="generating")

    assert store.recover_on_startup() == [q1.id, q2.id]
    failed = store.get(r.id)
    assert failed.status == "failed" and failed.stage is None and failed.finished_at is not None
    assert failed.error.code == "internal" and "restart" in failed.error.message


def test_jobs_survive_reopening_the_file(tmp_path):
    path = str(tmp_path / "jobs.sqlite3")
    first = JobStore(path)
    job = first.create("from_transcript", "dell", {"projeto": "Persistente"}, {})
    first.close()

    second = JobStore(path)
    assert second.get(job.id).header == {"projeto": "Persistente"}
    second.close()


def test_list_filters_by_project_alone_and_with_status(store):
    a = store.create("from_transcript", "dell", {}, {}, project_id="sgl-1")
    b = store.create("from_transcript", "dell", {}, {}, project_id="sgl-2")
    c = store.create("from_transcript", "dell", {}, {}, project_id="sgl-1")
    store.create("from_transcript", "dell", {}, {})  # no project
    store.update(a.id, status="done")

    assert store.get(b.id).project_id == "sgl-2"
    assert {j.id for j in store.list(project_id="sgl-1")} == {a.id, c.id}
    assert [j.id for j in store.list(project_id="sgl-1", status="done")] == [a.id]
    assert store.list(project_id="nobody") == []
    assert len(store.list()) == 4


def test_database_from_before_project_id_is_migrated(tmp_path):
    # The table as it was created by the first version of the API, already holding a job.
    path = str(tmp_path / "old.sqlite3")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, stage TEXT,
            template TEXT NOT NULL, header TEXT NOT NULL, params TEXT NOT NULL, result TEXT,
            error TEXT, minutes TEXT, participants TEXT, docx_path TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
        );
        INSERT INTO jobs (id, kind, status, template, header, params, created_at, updated_at)
        VALUES ('old', 'from_transcript', 'done', 'dell', '{}', '{}', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z');
        """
    )
    conn.close()

    store = JobStore(path)
    assert store.get("old").project_id is None
    new = store.create("from_transcript", "dell", {}, {}, project_id="sgl-1")
    assert [j.id for j in store.list(project_id="sgl-1")] == [new.id]
    store.close()
    JobStore(path).close()  # opening an already migrated file again is a no-op
