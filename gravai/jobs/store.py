"""
SQLite persistence for jobs. One table, JSON columns for the nested parts.

A single store is shared by the API threads and the worker thread, so every
access goes through one connection guarded by a lock (SQLite itself is fine
with that; what it does not like is many connections writing at once).
"""

import json
import os
import sqlite3
import threading
import uuid

from gravai.jobs.models import STATUSES, Job, utcnow

_JSON_COLUMNS = ("header", "params", "result", "error", "minutes", "participants")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL,
    stage         TEXT,
    template      TEXT NOT NULL,
    header        TEXT NOT NULL,
    project_id    TEXT,
    params        TEXT NOT NULL,
    result        TEXT,
    error         TEXT,
    minutes       TEXT,
    participants  TEXT,
    docx_path     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status);
"""

# Columns added after the first version of the table. A database created before them
# (the servers already have one) gets them on open; CREATE TABLE IF NOT EXISTS does not.
_ADDED_COLUMNS = {"project_id": "TEXT"}


class JobStore:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        existing = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        for column, sql_type in _ADDED_COLUMNS.items():
            if column not in existing:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {sql_type}")
        self._conn.execute("CREATE INDEX IF NOT EXISTS jobs_project_id ON jobs (project_id)")
        self._conn.commit()

    # ------------------------------------------------------------ writes

    def create(self, kind: str, template: str, header: dict, params: dict, project_id: str | None = None) -> Job:
        now = utcnow()
        job = Job(
            id=str(uuid.uuid4()),
            kind=kind,
            template=template,
            header=header,
            project_id=project_id,
            params=params,
            created_at=now,
            updated_at=now,
        )
        row = _to_row(job)
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        with self._lock:
            self._conn.execute(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", list(row.values()))
            self._conn.commit()
        return job

    def update(self, job_id: str, **fields) -> Job:
        """
        Sets the given columns and bumps updated_at. Moving to done/failed also
        sets finished_at and clears the stage. Returns the updated job.
        """
        if "status" in fields:
            if fields["status"] not in STATUSES:
                raise ValueError(f"unknown status '{fields['status']}'")
            if fields["status"] in ("done", "failed"):
                fields.setdefault("finished_at", utcnow())
                fields.setdefault("stage", None)
        fields["updated_at"] = utcnow()
        values = {
            k: (json.dumps(v, ensure_ascii=False) if k in _JSON_COLUMNS and v is not None else v)
            for k, v in fields.items()
        }
        assignments = ", ".join(f"{k} = ?" for k in values)
        with self._lock:
            cursor = self._conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", [*values.values(), job_id])
            self._conn.commit()
            if cursor.rowcount == 0:
                raise KeyError(job_id)
        return self.get(job_id)

    def recover_on_startup(self) -> list[str]:
        """
        Called once when the API starts. Jobs left in 'running' by a previous
        process can never finish, so they become failed; jobs still 'queued'
        are returned so the worker can pick them up again, oldest first.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'failed', stage = NULL, finished_at = ?, updated_at = ?, error = ? WHERE status = 'running'",
                [utcnow(), utcnow(), json.dumps({"code": "internal", "message": "interrupted by restart"})],
            )
            self._conn.commit()
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at, rowid"
            ).fetchall()
        return [r["id"] for r in rows]

    # ------------------------------------------------------------- reads

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()
        return _from_row(row) if row else None

    def list(self, limit: int = 20, status: str | None = None, project_id: str | None = None) -> list[Job]:
        """Most recent first, optionally only one status and/or one project."""
        filters = {"status": status, "project_id": project_id}
        conditions = [f"{column} = ?" for column, value in filters.items() if value]
        args: list = [value for value in filters.values() if value]
        query = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(conditions) if conditions else "")
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [_from_row(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _to_row(job: Job) -> dict:
    data = job.model_dump()
    return {
        k: (json.dumps(v, ensure_ascii=False) if k in _JSON_COLUMNS and v is not None else v) for k, v in data.items()
    }


def _from_row(row: sqlite3.Row) -> Job:
    data = dict(row)
    for k in _JSON_COLUMNS:
        if data.get(k) is not None:
            data[k] = json.loads(data[k])
    return Job(**data)
