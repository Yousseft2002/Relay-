"""Durable jobs for the private, single-user local bridge.

Each operation opens its own SQLite connection so separate worker processes share
one state machine. Expired work fails closed: it is never retried automatically,
because another provider request could spend money twice. Credential checks catch
obvious token/private-key formats; they are not comprehensive secret detection.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MAX_PAYLOAD_CHARS = 200_000
MAX_RESULT_CHARS = 200_000
REQUIRED_FIELDS = {"objective", "research", "rough_prompt"}
OPTIONAL_FIELDS = {"sources", "acceptance_criteria"}
STRING_LIMITS = {"objective": 8_000, "research": 128_000, "rough_prompt": 96_000}
LIST_LIMITS = {"sources": (100, 2_048), "acceptance_criteria": (100, 2_000)}
JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    r"|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
)


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Job data must be finite JSON values.") from None


def _checked_text(value: object, name: str, limit: int, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError(f"{name} must be a nonempty string.")
    if len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} exceeds its size limit or contains a null character.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} must contain valid Unicode text.") from None
    if SECRET.search(value):
        raise ValueError("Remove credentials before submitting job data.")
    return value


def _payload(payload: dict) -> tuple[dict, str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Job input must be an object.")
    if set(payload) - REQUIRED_FIELDS - OPTIONAL_FIELDS:
        raise ValueError("Job input contains unknown fields.")
    if not REQUIRED_FIELDS <= set(payload):
        raise ValueError("Job input requires objective, research, and rough_prompt.")
    normalized = {name: _checked_text(payload[name], name, limit)
                  for name, limit in STRING_LIMITS.items()}
    for name, (count_limit, text_limit) in LIST_LIMITS.items():
        values = payload.get(name, [])
        if not isinstance(values, list) or len(values) > count_limit:
            raise ValueError(f"{name} must be a list with at most {count_limit} items.")
        normalized[name] = [_checked_text(value, name, text_limit) for value in values]
    encoded = _json(normalized)
    if len(encoded) > MAX_PAYLOAD_CHARS:
        raise ValueError("Job input exceeds the total size limit.")
    return normalized, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _job_id(job_id: str) -> None:
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job ID.")


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


class JobStore:
    """SQLite-backed handoffs shared by one user's stdio client and workers."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "jobs.sqlite3"
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                request_id TEXT UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('submitted','running','completed','failed')),
                input TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                result TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                deadline REAL
            )""")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _expire(db: sqlite3.Connection, job_id: str, now: float) -> None:
        db.execute("""UPDATE jobs SET status='failed', error=?, updated_at=?
                      WHERE job_id=? AND status='running' AND deadline<=?""",
                   ("Job deadline expired; no automatic retry was started.", now, job_id, now))

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        job = {"job_id": row["job_id"], "status": row["status"],
               "input": json.loads(row["input"]), "input_hash": row["input_hash"],
               "result": json.loads(row["result"]) if row["result"] is not None else None,
               "error": row["error"], "created_at": _stamp(row["created_at"]),
               "updated_at": _stamp(row["updated_at"])}
        if row["deadline"] is not None:
            job["deadline"] = _stamp(row["deadline"])
        return job

    def submit(self, payload: dict, request_id: str | None = None) -> dict:
        """Persist normalized input; the same request key returns the original job."""
        _, encoded, input_hash = _payload(payload)
        if request_id is not None and (
                not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id)):
            raise ValueError("request_id must be 1-128 letters, digits, or ._:- characters.")
        with self._transaction() as db:
            now = time.time()
            if request_id is not None:
                row = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
                if row is not None:
                    if row["input_hash"] != input_hash:
                        raise ValueError("request_id was already used for different input.")
                    self._expire(db, row["job_id"], now)
                    row = db.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
                    return self._record(row)
            job_id = uuid.uuid4().hex
            db.execute("""INSERT INTO jobs
                (job_id,request_id,status,input,input_hash,created_at,updated_at)
                VALUES (?,?,'submitted',?,?,?,?)""",
                       (job_id, request_id, encoded, input_hash, now, now))
            return self._record(db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def get(self, job_id: str) -> dict:
        """Read a job, failing expired running work before returning it."""
        _job_id(job_id)
        with self._transaction() as db:
            self._expire(db, job_id, time.time())
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError("Job not found.")
            return self._record(row)

    def claim(self, job_id: str, timeout_s: int = 180) -> bool:
        """Atomically grant exactly one worker a bounded execution window."""
        _job_id(job_id)
        if type(timeout_s) is not int or not 1 <= timeout_s <= 3600:
            raise ValueError("timeout_s must be an integer from 1 to 3600.")
        with self._transaction() as db:
            now = time.time()
            self._expire(db, job_id, now)
            cursor = db.execute("""UPDATE jobs SET status='running', updated_at=?, deadline=?
                                   WHERE job_id=? AND status='submitted'""",
                                (now, now + timeout_s, job_id))
            return cursor.rowcount == 1

    def complete(self, job_id: str, input_hash: str, result: dict) -> bool:
        """Accept a caller-validated report only for the active, unchanged input."""
        _job_id(job_id)
        if not isinstance(input_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", input_hash):
            raise ValueError("Invalid input hash.")
        if not isinstance(result, dict):
            raise ValueError("Job result must be an object.")
        encoded = _json(result)
        _checked_text(encoded, "result", MAX_RESULT_CHARS)
        with self._transaction() as db:
            now = time.time()
            self._expire(db, job_id, now)
            cursor = db.execute("""UPDATE jobs SET status='completed', result=?, error=NULL, updated_at=?
                WHERE job_id=? AND status='running' AND input_hash=? AND deadline>?""",
                                (encoded, now, job_id, input_hash, now))
            return cursor.rowcount == 1

    def fail(self, job_id: str, message: str) -> bool:
        """Store a caller-redacted failure; terminal jobs cannot be overwritten."""
        _job_id(job_id)
        message = _checked_text(message, "error", 2_000)
        with self._transaction() as db:
            now = time.time()
            self._expire(db, job_id, now)
            cursor = db.execute("""UPDATE jobs SET status='failed', error=?, updated_at=?
                                   WHERE job_id=? AND status IN ('submitted','running')""",
                                (message, now, job_id))
            return cursor.rowcount == 1
