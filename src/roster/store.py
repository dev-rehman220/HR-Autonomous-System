"""SQLite-backed applicant roster: the single source of truth for candidates."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.roster.taxonomy import get_specializations

_JSON_COLUMNS = ("skills", "gaps", "questions")
_ORDERABLE = {
    "fit_score", "experience_years", "full_name", "specialization",
    "created_at", "updated_at", "last_seen_at", "id",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applicants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT,
    email TEXT,
    normalized_email TEXT,
    github_username TEXT,
    specialization TEXT,
    classification_confidence REAL NOT NULL DEFAULT 0,
    skills TEXT NOT NULL DEFAULT '[]',
    experience_years REAL NOT NULL DEFAULT 0,
    fit_score INTEGER NOT NULL DEFAULT 0,
    matched_job_id TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    decision TEXT,
    gaps TEXT NOT NULL DEFAULT '[]',
    questions TEXT NOT NULL DEFAULT '[]',
    draft_email TEXT,
    resume_text TEXT,
    cv_hash TEXT,
    message_id TEXT,
    source_subject TEXT,
    source_date TEXT,
    seen_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_applicants_cv_hash
    ON applicants(cv_hash) WHERE cv_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_applicants_message_id
    ON applicants(message_id) WHERE message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_applicants_norm_email
    ON applicants(normalized_email) WHERE normalized_email IS NOT NULL;
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    normalized = email.strip().lower()
    if normalized.startswith("unknown@"):
        return None
    return normalized


class SqliteApplicantStore:
    """CRUD + dedup + ranking queries over a SQLite roster."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def upsert_candidate(
        self,
        *,
        full_name: str,
        email: Optional[str] = None,
        github_username: Optional[str] = None,
        specialization: str = "Other",
        skills: Optional[list[str]] = None,
        experience_years: float = 0.0,
        fit_score: int = 0,
        confidence: float = 0.0,
        cv_hash: Optional[str] = None,
        message_id: Optional[str] = None,
        source_subject: Optional[str] = None,
        source_date: Optional[str] = None,
        resume_text: str = "",
    ) -> tuple[str, int]:
        """Insert a new applicant or flag a duplicate. Returns (status, id)."""
        normalized_email = normalize_email(email)
        now = _utcnow()
        with self._lock:
            duplicate = self._find_duplicate(cv_hash, message_id, normalized_email)
            if duplicate is not None:
                self._conn.execute(
                    "UPDATE applicants SET last_seen_at = ?, updated_at = ?, "
                    "seen_count = seen_count + 1 WHERE id = ?",
                    (now, now, duplicate["id"]),
                )
                self._conn.commit()
                return "duplicate", int(duplicate["id"])

            cursor = self._conn.execute(
                """
                INSERT INTO applicants (
                    full_name, email, normalized_email, github_username, specialization,
                    classification_confidence, skills, experience_years, fit_score,
                    status, cv_hash, message_id, source_subject, source_date, resume_text,
                    created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    full_name, email, normalized_email, github_username, specialization,
                    confidence, json.dumps(skills or []), float(experience_years),
                    int(fit_score), cv_hash, message_id, source_subject, source_date,
                    resume_text, now, now, now,
                ),
            )
            self._conn.commit()
            return "new", int(cursor.lastrowid)

    def update_screening(self, applicant_id: int, state: dict) -> None:
        decision = (state.get("decision") or "").upper()
        status = {"INVITE": "invited", "REJECT": "rejected"}.get(decision, "screened")
        job = state.get("matched_job") or {}
        with self._lock:
            self._conn.execute(
                """
                UPDATE applicants SET
                    fit_score = ?, matched_job_id = ?, gaps = ?, questions = ?,
                    draft_email = ?, decision = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(state.get("fit_score", 0)), job.get("job_id"),
                    json.dumps(state.get("gaps", [])), json.dumps(state.get("questions", [])),
                    state.get("draft_email", ""), decision, status, _utcnow(), applicant_id,
                ),
            )
            self._conn.commit()

    def set_status(self, applicant_id: int, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE applicants SET status = ?, updated_at = ? WHERE id = ?",
                (status, _utcnow(), applicant_id),
            )
            self._conn.commit()

    def delete(self, applicant_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM applicants WHERE id = ?", (applicant_id,))
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, applicant_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM applicants WHERE id = ?", (applicant_id,)
            ).fetchone()
        return _row_to_dict(row)

    def list(
        self,
        *,
        specialization: Optional[str] = None,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        order_by: str = "fit_score",
        descending: bool = True,
        limit: Optional[int] = None,
    ) -> list[dict]:
        clauses, params = [], []
        if specialization:
            clauses.append("specialization = ?")
            params.append(specialization)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if min_score is not None:
            clauses.append("fit_score >= ?")
            params.append(int(min_score))

        column = order_by if order_by in _ORDERABLE else "fit_score"
        direction = "DESC" if descending else "ASC"
        query = "SELECT * FROM applicants"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += f" ORDER BY {column} {direction}, id ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    def group_by_specialization(
        self, *, min_score: Optional[int] = None, descending: bool = True
    ) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {name: [] for name in get_specializations()}
        for applicant in self.list(min_score=min_score, descending=descending):
            bucket = applicant.get("specialization") or "Other"
            grouped.setdefault(bucket, []).append(applicant)
        return grouped

    def count(self, status: Optional[str] = None) -> int:
        with self._lock:
            if status:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM applicants WHERE status = ?", (status,)
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM applicants").fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _find_duplicate(
        self, cv_hash: Optional[str], message_id: Optional[str], normalized_email: Optional[str]
    ) -> Optional[sqlite3.Row]:
        for column, value in (
            ("cv_hash", cv_hash),
            ("message_id", message_id),
            ("normalized_email", normalized_email),
        ):
            if not value:
                continue
            row = self._conn.execute(
                f"SELECT * FROM applicants WHERE {column} = ? LIMIT 1", (value,)
            ).fetchone()
            if row is not None:
                return row
        return None


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    result = dict(row)
    for column in _JSON_COLUMNS:
        result[column] = json.loads(result.get(column) or "[]")
    return result
