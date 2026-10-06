"""
Store + worker bundle the API keeps on app.state.jobs. Built once at startup
(see api/app.py lifespan); tests build one around an in-memory store.
"""

import os

from gravai.config import Settings
from gravai.jobs.executors import EXECUTORS
from gravai.jobs.store import JobStore
from gravai.jobs.worker import Executor, JobWorker


class JobsRuntime:
    def __init__(self, store: JobStore, executors: dict[str, Executor] | None = None):
        self.store = store
        self.worker = JobWorker(store, executors if executors is not None else EXECUTORS)

    @classmethod
    def from_settings(cls) -> "JobsRuntime":
        settings = Settings()
        path = settings.JOBS_DB_PATH or os.path.join(settings.SAVE_DIR, "minutes_jobs.sqlite3")
        return cls(JobStore(path))

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop(timeout=5)
        self.store.close()

    def enqueue(self, kind: str, template: str, header: dict, params: dict):
        job = self.store.create(kind, template, header, params)
        self.worker.submit(job.id)
        return job
