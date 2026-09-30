"""Bounded, account-scoped local MCP job journal; never store exception text or payloads."""

import json
import os
from datetime import UTC, datetime

from mi_fitness_mcp.storage import Database

MAX_HISTORY = 500
STATE_FIELDS = {
    "sync_id",
    "status",
    "created_at",
    "started_at",
    "finished_at",
    "data_types_synced",
    "records_added",
    "records_updated",
    "records_skipped",
    "error_code",
}
RESULT_FIELDS = {"data_type", "status", "added", "updated", "skipped", "error_code"}


class SyncHistory:
    def __init__(self, db: Database, user_id: str):
        self.db = db
        self.user_id = user_id
        self._lock_file = None
        with db._get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS mcp_sync_jobs (
                sync_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
            )""")
            conn.execute("""CREATE INDEX IF NOT EXISTS mcp_sync_jobs_account_date
                ON mcp_sync_jobs(user_id, created_at, sync_id)""")
            conn.commit()

    def acquire(self) -> None:
        """One MCP server per database; OS releases this lock even after a crash.

        Do not unlink the lock file: a second process may already have opened it.
        CLI commands are not covered by this MCP lifetime lock.
        """
        handle = self.db.db_path.with_suffix(self.db.db_path.suffix + ".mcp.lock").open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("Another MCP server is using this database") from exc
        self._lock_file = handle

    def close(self) -> None:
        if self._lock_file is not None:
            self._lock_file.close()
            self._lock_file = None

    def save(self, state: dict) -> None:
        # Allowlist rather than redaction: errors can contain tokens, URLs, or health data.
        safe = {key: value for key, value in state.items() if key in STATE_FIELDS}
        if "results" in state:
            safe["results"] = [
                {key: value for key, value in result.items() if key in RESULT_FIELDS}
                for result in state["results"]
            ]
        with self.db._get_connection() as conn:
            conn.execute(
                """INSERT INTO mcp_sync_jobs VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(sync_id) DO UPDATE SET status=excluded.status,
                   payload=excluded.payload WHERE user_id=excluded.user_id""",
                (
                    safe["sync_id"],
                    self.user_id,
                    safe["created_at"],
                    safe["status"],
                    json.dumps(safe),
                ),
            )
            conn.execute(
                """DELETE FROM mcp_sync_jobs WHERE user_id=?
                   AND status NOT IN ('queued', 'running') AND sync_id NOT IN (
                       SELECT sync_id FROM mcp_sync_jobs WHERE user_id=?
                       AND status NOT IN ('queued', 'running')
                       ORDER BY created_at DESC, sync_id DESC LIMIT ?
                   )""",
                (self.user_id, self.user_id, MAX_HISTORY),
            )
            conn.commit()

    def get(self, sync_id: str) -> dict | None:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT payload FROM mcp_sync_jobs WHERE user_id=? AND sync_id=?",
                (self.user_id, sync_id),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def query(self, limit: int = 20, offset: int = 0) -> list[dict]:
        with self.db._get_connection() as conn:
            rows = conn.execute(
                """SELECT payload FROM mcp_sync_jobs WHERE user_id=?
                   ORDER BY created_at DESC, sync_id DESC LIMIT ? OFFSET ?""",
                (self.user_id, limit, offset),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def recover_interrupted(self) -> None:
        """Single-server startup: a previous process cannot still own these jobs."""
        with self.db._get_connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM mcp_sync_jobs WHERE user_id=? AND status IN ('queued','running')",
                (self.user_id,),
            ).fetchall()
        for row in rows:
            state = json.loads(row["payload"])
            state.update(status="interrupted", finished_at=datetime.now(UTC).isoformat())
            self.save(state)
