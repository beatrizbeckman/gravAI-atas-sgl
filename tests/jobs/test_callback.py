import requests

from gravai.jobs import callback
from gravai.jobs.store import JobStore
from gravai.jobs.worker import ExecutionOutcome, JobWorker
from gravai.minutes.generate import MinutesError


class Answer:
    def __init__(self, status_code):
        self.status_code = status_code


def test_deliver_sends_the_job_with_the_api_key_and_retries(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    monkeypatch.setattr(callback.time, "sleep", lambda s: None)
    sent = []
    answers = iter([requests.ConnectionError("down"), Answer(500), Answer(204)])

    def fake_post(url, json, headers, timeout):
        sent.append((url, json["id"], headers.get("X-API-Key")))
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(requests, "post", fake_post)
    assert callback.deliver("http://sgl.lab/atas/webhook", {"id": "j1"}) is True
    assert sent == [("http://sgl.lab/atas/webhook", "j1", "s3cret")] * 3


def test_deliver_gives_up_after_the_attempts(monkeypatch):
    monkeypatch.setattr(callback.time, "sleep", lambda s: None)
    monkeypatch.setattr(requests, "post", lambda url, json, headers, timeout: Answer(503))
    assert callback.deliver("http://sgl.lab/atas/webhook", {"id": "j1"}) is False


def test_worker_notifies_finished_jobs_that_asked_for_it():
    store = JobStore(":memory:")
    notified = []

    def ok(job, progress):
        return ExecutionOutcome(
            result={
                "download_url": "/x",
                "filename": "a.docx",
                "participants": [],
                "utterances": 1,
                "parts": 1,
                "llm_model": "m",
                "generation_seconds": 1.0,
            },
            docx_path="/x",
            minutes={},
            participants=[],
            header=job.header,
        )

    def broken(job, progress):
        raise MinutesError("llm_unreachable", "down")

    worker = JobWorker(
        store,
        {"from_transcript": ok, "from_recording": broken},
        notify=lambda url, job: notified.append((url, job["status"])),
    )
    done = store.create("from_transcript", "dell", {}, {"callback_url": "http://sgl.lab/hook"})
    failed = store.create("from_recording", "dell", {}, {"callback_url": "http://sgl.lab/hook"})
    silent = store.create("from_transcript", "dell", {}, {})

    worker.run(done.id)
    worker.run(failed.id)
    worker.run(silent.id)
    assert notified == [("http://sgl.lab/hook", "done"), ("http://sgl.lab/hook", "failed")]
    store.close()
