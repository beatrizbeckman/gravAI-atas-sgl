"""
Store + worker bundle the API keeps on app.state.jobs. Built once at startup
(see api/app.py lifespan); tests build one around an in-memory store.
"""

import os

from gravai.config import Settings
from gravai.jobs.executors import EXECUTORS, PREPARERS
from gravai.jobs.store import JobStore
from gravai.jobs.worker import Executor, JobWorker


class JobsRuntime:
    def __init__(self, store: JobStore, executors: dict[str, Executor] | None = None, recording_threads: int = 1):
        self.store = store
        # Custom executors (tests) run everything in the processing lane; the real ones record in parallel.
        self.worker = JobWorker(
            store,
            executors if executors is not None else EXECUTORS,
            preparers=PREPARERS if executors is None else None,
            preparing_threads=recording_threads,
        )

    @classmethod
    def from_settings(cls) -> "JobsRuntime":
        settings = Settings()
        path = settings.JOBS_DB_PATH or os.path.join(settings.SAVE_DIR, "minutes_jobs.sqlite3")
        return cls(JobStore(path), recording_threads=settings.MAX_CONCURRENT_RECORDINGS)

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop(timeout=5)
        self.store.close()

    def enqueue(self, kind: str, template: str, header: dict, params: dict, project_id: str | None = None):
        job = self.store.create(kind, template, header, params, project_id)
        self.worker.submit(job.id)
        return job
