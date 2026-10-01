import threading

import pytest

from jobs.store import JobStore
from jobs.worker import ExecutionOutcome, JobWorker
from minutes.generate import MinutesError


def outcome(job):
    return ExecutionOutcome(
        result={"download_url": f"/minutes/jobs/{job.id}/download", "filename": "a.docx", "participants": ["A"], "utterances": 1, "parts": 1, "llm_model": "fake", "generation_seconds": 0.1},
        docx_path="/x/a.docx",
        minutes={"resumo": "ok"},
        participants=["A"],
        header={**job.header, "normalized": "yes"},
    )


@pytest.fixture
def store():
    s = JobStore(":memory:")
    yield s
    s.close()


def test_run_moves_the_job_through_stages_to_done(store):
    seen = []

    def executor(job, progress):
        seen.append(store.get(job.id).status)
        progress("generating")
        seen.append(store.get(job.id).stage)
        progress("rendering")
        return outcome(job)

    worker = JobWorker(store, {"from_transcript": executor})
    job = store.create("from_transcript", "dell", {"projeto": "X"}, {})

    done = worker.run(job.id)

    assert seen == ["running", "generating"]
    assert done.status == "done" and done.stage is None and done.finished_at
    assert done.result.download_url.endswith(f"/{job.id}/download")
    assert done.minutes == {"resumo": "ok"} and done.docx_path == "/x/a.docx"
    assert done.header == {"projeto": "X", "normalized": "yes"}


def test_minutes_error_becomes_failed_with_its_code(store):
    def executor(job, progress):
        progress("generating")
        raise MinutesError("llm_unreachable", "Ollama is down")

    worker = JobWorker(store, {"from_transcript": executor})
    job = store.create("from_transcript", "dell", {}, {})
    failed = worker.run(job.id)
    assert failed.status == "failed" and failed.stage is None
    assert failed.error.code == "llm_unreachable" and failed.error.message == "Ollama is down"


def test_unexpected_exception_becomes_internal(store):
    def executor(job, progress):
        raise ZeroDivisionError("boom")

    worker = JobWorker(store, {"from_transcript": executor})
    job = store.create("from_transcript", "dell", {}, {})
    failed = worker.run(job.id)
    assert failed.error.code == "internal" and "ZeroDivisionError: boom" in failed.error.message


def test_missing_executor_is_internal_and_non_queued_jobs_are_skipped(store):
    worker = JobWorker(store, {})
    job = store.create("from_recording", "dell", {}, {})
    assert worker.run(job.id).error.code == "internal"
    # Already finished: running it again does nothing.
    assert worker.run(job.id).status == "failed"
    assert worker.run("missing") is None


def test_thread_runs_submitted_jobs_in_order_and_requeues_on_start(store):
    order = []
    gate = threading.Event()

    def executor(job, progress):
        order.append(job.id)
        if len(order) == 3:
            gate.set()
        return outcome(job)

    # Two jobs left queued "by a previous process", one left running.
    before1 = store.create("from_transcript", "dell", {}, {})
    stale = store.create("from_transcript", "dell", {}, {})
    store.update(stale.id, status="running")
    before2 = store.create("from_transcript", "dell", {}, {})

    worker = JobWorker(store, {"from_transcript": executor})
    worker.start()
    new = store.create("from_transcript", "dell", {}, {})
    worker.submit(new.id)

    assert gate.wait(5)
    worker.stop(timeout=5)
    assert order == [before1.id, before2.id, new.id]
    assert store.get(stale.id).status == "failed"
    assert all(store.get(i).status == "done" for i in order)


def test_worker_thread_survives_a_crashing_run(store, monkeypatch):
    worker = JobWorker(store, {"from_transcript": lambda job, progress: outcome(job)})
    calls = []

    def flaky_run(job_id):
        calls.append(job_id)
        if len(calls) == 1:
            raise RuntimeError("store exploded")
        return JobWorker.run(worker, job_id)

    monkeypatch.setattr(worker, "run", flaky_run)
    worker.start()  # before creating the jobs, otherwise start() re-queues them too
    a = store.create("from_transcript", "dell", {}, {})
    b = store.create("from_transcript", "dell", {}, {})
    worker.submit(a.id)
    worker.submit(b.id)
    worker.stop(timeout=5)
    assert calls == [a.id, b.id]
    assert store.get(b.id).status == "done"
