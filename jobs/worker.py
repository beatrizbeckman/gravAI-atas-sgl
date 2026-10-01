"""
One background thread that runs jobs one at a time, in the order they were
submitted. The API creates the job in the store, then calls submit(); the
worker moves it queued -> running -> done | failed and keeps `stage` current.

An executor is a function (job, progress) -> ExecutionOutcome registered per
job kind. It raises MinutesError for expected failures (mapped to the error
codes of the contract) and anything else becomes "internal".
"""
import queue
import threading
import traceback
from dataclasses import dataclass
from typing import Callable

from jobs.models import Job
from jobs.store import JobStore
from minutes.generate import MinutesError

_STOP = object()


@dataclass
class ExecutionOutcome:
    """What an executor hands back: the public result plus the internal columns."""
    result: dict
    docx_path: str
    minutes: dict
    participants: list[str]
    header: dict


Executor = Callable[[Job, Callable[[str], None]], ExecutionOutcome]


class JobWorker:
    def __init__(self, store: JobStore, executors: dict[str, Executor]):
        self.store = store
        self.executors = executors
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.current_job_id: str | None = None

    # ----------------------------------------------------------- control

    def start(self) -> None:
        """Starts the thread and re-queues jobs that were waiting before a restart."""
        if self._thread and self._thread.is_alive():
            return
        for job_id in self.store.recover_on_startup():
            self._queue.put(job_id)
        self._thread = threading.Thread(target=self._loop, name="minutes-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        if self._thread:
            self._queue.put(_STOP)
            self._thread.join(timeout)

    def submit(self, job_id: str) -> None:
        self._queue.put(job_id)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # -------------------------------------------------------------- loop

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            try:
                self.run(item)
            except Exception:  # never let the thread die
                traceback.print_exc()

    def run(self, job_id: str) -> Job:
        """Runs one job synchronously (the loop calls this; tests can too)."""
        job = self.store.get(job_id)
        if job is None or job.status != "queued":
            return job
        self.current_job_id = job_id
        self.store.update(job_id, status="running", stage=None)

        def progress(stage: str) -> None:
            self.store.update(job_id, stage=stage)

        try:
            executor = self.executors.get(job.kind)
            if executor is None:
                raise MinutesError("internal", f"no executor for job kind '{job.kind}'")
            outcome = executor(job, progress)
        except MinutesError as exc:
            return self._fail(job_id, exc.code, exc.message)
        except Exception as exc:
            traceback.print_exc()
            return self._fail(job_id, "internal", f"{exc.__class__.__name__}: {exc}")
        finally:
            self.current_job_id = None

        return self.store.update(
            job_id,
            status="done",
            result=outcome.result,
            docx_path=outcome.docx_path,
            minutes=outcome.minutes,
            participants=outcome.participants,
            header=outcome.header,
        )

    def _fail(self, job_id: str, code: str, message: str) -> Job:
        return self.store.update(job_id, status="failed", error={"code": code, "message": message})
