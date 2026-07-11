"""
Database — SQLite with WAL mode, connection management.
=======================================================
1GB RAM optimized: single persistent connection, WAL mode, no connection pool overhead.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite database with WAL mode and connection management."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    # ── Connection ───────────────────────────────────────────────────────

    def connect(self) -> None:
        """Initialize connection and WAL mode."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-8000")         # 8MB cache
        self._conn.execute("PRAGMA mmap_size=268435456")      # 256MB mmap
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        logger.info("SQLite connected: %s (WAL mode)", self.db_path)

    def close(self) -> None:
        """Close connection."""
        if self._conn:
            self._conn.close()
            logger.info("SQLite connection closed")

    # ── Operations ───────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL with lock."""
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """Execute SQL many with lock."""
        with self._lock:
            return self._conn.executemany(sql, params_list)

    def fetch_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Fetch all rows."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Fetch single row."""
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def commit(self) -> None:
        """Commit transaction."""
        with self._lock:
            self._conn.commit()

    def vacuum(self) -> None:
        """VACUUM to reclaim space."""
        with self._lock:
            self._conn.execute("VACUUM")
        logger.info("Database vacuumed")

    def backup(self, backup_path: str | Path) -> None:
        """Backup database to file."""
        backup = sqlite3.connect(str(backup_path))
        with self._lock:
            self._conn.backup(backup, pages=1000)
        backup.close()
        logger.info("Database backed up to %s", backup_path)

    # ── Schema ───────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id       TEXT PRIMARY KEY,
                    key_hash     TEXT NOT NULL,
                    key_prefix   TEXT NOT NULL,
                    server_name  TEXT NOT NULL,
                    tier         TEXT NOT NULL DEFAULT 'free',
                    rate_limit   INTEGER NOT NULL DEFAULT 60,
                    enabled      INTEGER NOT NULL DEFAULT 1,
                    expires_at   REAL,
                    created_at   REAL NOT NULL DEFAULT (strftime('%s','now')),
                    last_used    REAL
                );

                CREATE TABLE IF NOT EXISTS rate_limits (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id     TEXT NOT NULL REFERENCES api_keys(key_id),
                    timestamp  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rate_limits_key_ts
                    ON rate_limits(key_id, timestamp);

                CREATE TABLE IF NOT EXISTS rate_limits_global (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rate_limits_global_ts
                    ON rate_limits_global(timestamp);

                CREATE TABLE IF NOT EXISTS training_samples (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    category       TEXT NOT NULL,
                    features_json  TEXT NOT NULL,
                    label          REAL,
                    label_source   TEXT,
                    server_id      TEXT,
                    client_version TEXT,
                    ping           INTEGER,
                    tps            REAL,
                    jitter         INTEGER,
                    player_uuid    TEXT,
                    created_at     REAL NOT NULL DEFAULT (strftime('%s','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_training_samples_cat
                    ON training_samples(category, label);

                CREATE TABLE IF NOT EXISTS model_versions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name  TEXT NOT NULL,
                    version     TEXT NOT NULL,
                    file_path   TEXT,
                    auc         REAL,
                    f1_score    REAL,
                    samples     INTEGER,
                    trees       INTEGER,
                    is_active   INTEGER DEFAULT 0,
                    created_at  REAL NOT NULL DEFAULT (strftime('%s','now'))
                );

                CREATE TABLE IF NOT EXISTS prediction_log (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name     TEXT NOT NULL,
                    risk           REAL,
                    confidence     REAL,
                    latency_ms     INTEGER,
                    server_id      TEXT,
                    status         TEXT DEFAULT 'ok',
                    created_at     REAL NOT NULL DEFAULT (strftime('%s','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_pred_log_model
                    ON prediction_log(model_name, created_at);
            """)
        self.commit()

    def store_sample(self, category: str, features: list[float],
                     label: float | None, label_source: str | None,
                     server_id: str | None, client_version: str | None,
                     ping: int | None, tps: float | None,
                     jitter: int | None, player_uuid: str | None) -> None:
        """Store a training sample."""
        self.execute(
            """INSERT INTO training_samples
               (category, features_json, label, label_source, server_id,
                client_version, ping, tps, jitter, player_uuid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (category, json.dumps(features), label, label_source,
             server_id, client_version, ping, tps, jitter, player_uuid),
        )

    def get_labeled_samples(self, category: str,
                            min_label_weight: float = 0.3,
                            max_days: int = 30,
                            limit: int = 50000) -> tuple[list[list[float]], list[float]]:
        """Get labeled training samples with minimum label weight."""
        cutoff = time.time() - max_days * 86400
        rows = self.fetch_all(
            """SELECT features_json, label FROM training_samples
               WHERE category = ? AND label IS NOT NULL
               AND created_at > ?
               ORDER BY created_at DESC LIMIT ?""",
            (category, cutoff, limit),
        )
        features, labels = [], []
        for row in rows:
            features.append(json.loads(row["features_json"]))
            labels.append(row["label"])
        return features, labels
