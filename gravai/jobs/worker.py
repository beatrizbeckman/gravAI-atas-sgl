"""
Background threads that run the jobs. The API creates the job in the store, then
calls submit(); the worker moves it queued -> running -> done | failed and keeps
`stage` current.

Two lanes:

- **Preparing** (one thread per recorder slot): the slow part that can run side by
  side, today the recording of a meeting (record_and_generate). When it ends the
  job is `running · waiting` and goes to the processing lane. Several meetings of
  different projects can be recorded at the same time this way.
- **Processing** (one thread): everything else (transcription, LLM, docx), one
  job at a time, in submission order. Whisper and the LLM are the bottleneck and
  run one request at a time anyway.

An executor is a function (job, progress) -> ExecutionOutcome registered per job
kind; a preparer is (job, progress) -> Prepared. Both raise MinutesError for
expected failures (mapped to the error codes of the contract) and anything else
becomes "internal".
"""

import queue
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

from gravai.jobs.callback import deliver_in_background
from gravai.jobs.models import Job
from gravai.jobs.store import JobStore
from gravai.minutes.generate import MinutesError

_STOP = object()


@dataclass
class ExecutionOutcome:
    """What an executor hands back: the public result plus the internal columns."""

    result: dict
    docx_path: str
    minutes: dict
    participants: list[str]
    header: dict


@dataclass
class Prepared:
    """What a preparer hands back: parameters to add to the job and its (possibly completed) header."""

    params: dict = field(default_factory=dict)
    header: dict = field(default_factory=dict)


Progress = Callable[[str], None]
Executor = Callable[[Job, Progress], ExecutionOutcome]
Preparer = Callable[[Job, Progress], Prepared]
# (callback_url, public job) -> None; delivers the webhook of a finished job.
Notifier = Callable[[str, dict], None]


class JobWorker:
    def __init__(
        self,
        store: JobStore,
        executors: dict[str, Executor],
        notify: Notifier = deliver_in_background,
        preparers: dict[str, Preparer] | None = None,
        preparing_threads: int = 1,
    ):
        self.store = store
        self.executors = executors
        self.preparers = preparers or {}
        self.notify = notify
        self.preparing_threads = preparing_threads
        self._queue: queue.Queue = queue.Queue()  # processing lane
        self._prepare_queue: queue.Queue = queue.Queue()  # preparing lane
        self._threads: list[threading.Thread] = []

    # ----------------------------------------------------------- control

    def start(self) -> None:
        """Starts the threads and re-queues jobs that were waiting before a restart."""
        if any(t.is_alive() for t in self._threads):
            return
        for job_id in self.store.recover_on_startup():
            self.submit(job_id)
        self._threads = [threading.Thread(target=self._loop, name="minutes-jobs", daemon=True)]
        if self.preparers:
            self._threads += [
                threading.Thread(target=self._prepare_loop, name=f"minutes-recording-{i + 1}", daemon=True)
                for i in range(self.preparing_threads)
            ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float | None = None) -> None:
        if not self._threads:
            return
        self._queue.put(_STOP)
        for _ in range(len(self._threads) - 1):
            self._prepare_queue.put(_STOP)
        for thread in self._threads:
            thread.join(timeout)

    def submit(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is not None and self._needs_preparing(job):
            self._prepare_queue.put(job_id)
        else:
            self._queue.put(job_id)

    @property
    def pending(self) -> int:
        """Jobs waiting in the processing lane."""
        return self._queue.qsize()

    def _needs_preparing(self, job: Job) -> bool:
        return job.kind in self.preparers and job.status == "queued"

    # ------------------------------------------------------------- loops

    def _loop(self) -> None:
        self._consume(self._queue, self.run)

    def _prepare_loop(self) -> None:
        def prepare_then_queue(job_id: str) -> None:
            job = self.prepare(job_id)
            if job is not None and job.status == "running":
                self._queue.put(job_id)

        self._consume(self._prepare_queue, prepare_then_queue)

    @staticmethod
    def _consume(source: queue.Queue, handle: Callable[[str], object]) -> None:
        while True:
            item = source.get()
            if item is _STOP:
                return
            try:
                handle(item)
            except Exception:  # never let the thread die
                traceback.print_exc()

    # -------------------------------------------------------------- steps

    def prepare(self, job_id: str) -> Job | None:
        """
        Runs the preparer of a queued job (the recording). On success the job is left
        `running · waiting` with the new params and header; on failure it is failed
        and its webhook fired.
        """
        job = self.store.get(job_id)
        if job is None or not self._needs_preparing(job):
            return job
        self.store.update(job_id, status="running", stage=None)
        try:
            prepared = self.preparers[job.kind](job, self._progress(job_id))
        except Exception as exc:
            return self._finish(job, self._failure(job_id, exc))
        return self.store.update(
            job_id, stage="waiting", params={**job.params, **prepared.params}, header=prepared.header or job.header
        )

    def run(self, job_id: str) -> Job | None:
        """
        Runs one job to the end synchronously (the processing loop calls this; tests
        can too, then the preparer runs inline first), then fires its webhook.
        """
        job = self.store.get(job_id)
        if job is not None and self._needs_preparing(job):
            job = self.prepare(job_id)
        if job is None or not (job.status == "queued" or (job.status == "running" and job.stage == "waiting")):
            return job
        return self._finish(job, self._execute(job))

    def _finish(self, job: Job, finished: Job) -> Job:
        if callback_url := job.params.get("callback_url"):
            self.notify(callback_url, finished.public())
        return finished

    def _progress(self, job_id: str) -> Progress:
        def progress(stage: str) -> None:
            self.store.update(job_id, stage=stage)

        return progress

    def _execute(self, job: Job) -> Job:
        job_id = job.id
        self.store.update(job_id, status="running", stage=None)
        try:
            executor = self.executors.get(job.kind)
            if executor is None:
                raise MinutesError("internal", f"no executor for job kind '{job.kind}'")
            outcome = executor(self.store.get(job_id), self._progress(job_id))
        except Exception as exc:
            return self._failure(job_id, exc)

        return self.store.update(
            job_id,
            status="done",
            result=outcome.result,
            docx_path=outcome.docx_path,
            minutes=outcome.minutes,
            participants=outcome.participants,
            header=outcome.header,
        )

    def _failure(self, job_id: str, exc: Exception) -> Job:
        if isinstance(exc, MinutesError):
            return self._fail(job_id, exc.code, exc.message)
        traceback.print_exc()
        return self._fail(job_id, "internal", f"{exc.__class__.__name__}: {exc}")

    def _fail(self, job_id: str, code: str, message: str) -> Job:
        return self.store.update(job_id, status="failed", error={"code": code, "message": message})
