"""Crash-resilient progress tracking for model_metrics.py and baseline_extraction.py.

Caches per-source API/LM payloads in a SQLite DB so a resumed run can skip
sources that have already been successfully processed and re-attempt sources
whose previous run failed.

Status values stored per source_id:
  - success         : payload column holds the full cached JSON blob
  - source_missing  : terminal; /api/sources/<id> returned 404/None
  - no_v1_state     : terminal; source exists but has no /api/logs version 1
                      (only emitted by model_metrics.py)
  - failed          : transient; an exception was raised mid-fetch / LM call

`success`, `source_missing`, `no_v1_state` are treated as terminal — they will
not be re-fetched on the next run (their answer cannot change for a fixed ID).
`failed` rows are automatically re-attempted by every subsequent run; pass
--reset-progress to wipe the table entirely.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_runs (
    source_id   TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    error       TEXT,
    payload     TEXT,
    updated_at  TEXT NOT NULL
);
"""

_INDEX = "CREATE INDEX IF NOT EXISTS idx_status ON source_runs(status);"

TERMINAL_STATUSES = {"success", "source_missing", "no_v1_state"}
VALID_STATUSES = TERMINAL_STATUSES | {"failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProgressDB:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(_SCHEMA)
        self.conn.execute(_INDEX)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get_status(self, source_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM source_runs WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        return row["status"] if row else None

    def load_payload(self, source_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT payload FROM source_runs "
            "WHERE source_id = ? AND status = 'success'",
            (source_id,),
        ).fetchone()
        if row is None or row["payload"] is None:
            return None
        return json.loads(row["payload"])

    def record_success(self, source_id: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO source_runs "
            "(source_id, status, error, payload, updated_at) "
            "VALUES (?, 'success', NULL, ?, ?)",
            (source_id, json.dumps(payload, default=str), _now()),
        )
        self.conn.commit()

    def record_terminal_skip(self, source_id: str, status: str) -> None:
        if status not in {"source_missing", "no_v1_state"}:
            raise ValueError(f"Not a terminal skip status: {status!r}")
        self.conn.execute(
            "INSERT OR REPLACE INTO source_runs "
            "(source_id, status, error, payload, updated_at) "
            "VALUES (?, ?, NULL, NULL, ?)",
            (source_id, status, _now()),
        )
        self.conn.commit()

    def record_failure(self, source_id: str, error: str | None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO source_runs "
            "(source_id, status, error, payload, updated_at) "
            "VALUES (?, 'failed', ?, NULL, ?)",
            (source_id, error, _now()),
        )
        self.conn.commit()

    def reset(self) -> None:
        self.conn.execute("DELETE FROM source_runs")
        self.conn.commit()

    def counts_by_status(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM source_runs GROUP BY status"
        ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def iter_failed(self) -> Iterator[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT source_id, error FROM source_runs WHERE status = 'failed'"
        ).fetchall()
        for row in rows:
            yield row["source_id"], row["error"] or ""
