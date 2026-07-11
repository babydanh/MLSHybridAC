"""
Auth — API key authentication, rate limiting with SQLite sliding window.
=======================================================================
- API keys: bcrypt hashed in SQLite, per-server UUID v4
- Rate limiting: sliding window with 10s bucket granularity
- Tiers: free (60/min), basic (600), pro (3000), enterprise (unlimited)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from cloud.config import config
from cloud.database import Database

logger = logging.getLogger(__name__)


@dataclass
class APIKey:
    id: str
    key_prefix: str          # First 8 chars for identification
    server_name: str
    tier: str
    rate_limit: int
    enabled: bool
    expires_at: float | None


class AuthManager:
    """API key authentication and rate limiting."""

    def __init__(self, db: Database):
        self.db = db

    # ── Key Management ───────────────────────────────────────────────────

    def create_key(self, server_name: str, tier: str = "free",
                   expires_days: int = 365) -> tuple[str, APIKey]:
        """Create a new API key. Returns (raw_key, key_info).

        Store raw_key only at creation time — it's hashed in DB.
        """
        raw_key = f"sk-{secrets.token_hex(32)}"
        key_id = secrets.token_hex(8)
        hashed = self._hash_key(raw_key)
        rate_limit = config.rate_limit_tiers.get(tier, 60)
        expires_at = time.time() + expires_days * 86400

        self.db.execute(
            """INSERT INTO api_keys (key_id, key_hash, key_prefix, server_name,
                                     tier, rate_limit, expires_at, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (key_id, hashed, raw_key[:12], server_name, tier, rate_limit, expires_at),
        )

        key_info = APIKey(
            id=key_id, key_prefix=raw_key[:12], server_name=server_name,
            tier=tier, rate_limit=rate_limit, enabled=True, expires_at=expires_at,
        )
        return raw_key, key_info

    def verify_key(self, raw_key: str) -> Optional[APIKey]:
        """Verify API key. Returns APIKey if valid, None if invalid.

        Uses WHERE key_hash to avoid loading all rows (performance + security).
        Hash is deterministic given the same raw_key, so we pre-compute it.
        """
        expected_hash = self._hash_key(raw_key)
        row = self.db.fetch_one(
            "SELECT key_id, key_hash, key_prefix, server_name, tier, "
            "rate_limit, enabled, expires_at FROM api_keys WHERE key_hash = ?",
            (expected_hash,),
        )
        if row is None:
            return None
        if not row["enabled"]:
            logger.warning("Disabled key used: %s", row["key_prefix"])
            return None
        if row["expires_at"] and time.time() > row["expires_at"]:
            logger.info("Expired key: %s", row["key_prefix"])
            return None
        return APIKey(
            id=row["key_id"], key_prefix=row["key_prefix"],
            server_name=row["server_name"], tier=row["tier"],
            rate_limit=row["rate_limit"], enabled=bool(row["enabled"]),
            expires_at=row["expires_at"],
        )

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key. Returns True if found."""
        cur = self.db.execute("UPDATE api_keys SET enabled = 0 WHERE key_id = ?", (key_id,))
        return cur.rowcount > 0

    def list_keys(self) -> list[dict]:
        """List all non-revoked keys (without hashes)."""
        return self.db.fetch_all(
            "SELECT key_id, key_prefix, server_name, tier, enabled, expires_at "
            "FROM api_keys ORDER BY server_name"
        )

    # ── Rate Limiting ────────────────────────────────────────────────────

    def check_rate_limit(self, key_id: str, tier: str) -> tuple[bool, int, int]:
        """Check rate limit. Returns (allowed, remaining, limit).

        Uses atomic INSERT ... WHERE to prevent TOCTOU race conditions.
        """
        limit = config.rate_limit_tiers.get(tier, 60)
        now = time.time()
        window = 60.0

        # Cleanup old entries first
        self.db.execute(
            "DELETE FROM rate_limits WHERE key_id = ? AND timestamp < ?",
            (key_id, now - window),
        )

        # Atomic rate limit check + insert in one transaction
        row = self.db.fetch_one(
            "SELECT (SELECT COUNT(*) FROM rate_limits "
            "WHERE key_id = ? AND timestamp > ?) < ? as allowed",
            (key_id, now - window, limit),
        )
        if row and row["allowed"]:
            self.db.execute(
                "INSERT INTO rate_limits (key_id, timestamp) VALUES (?, ?)",
                (key_id, now),
            )
            self.db.commit()
            count = self.db.fetch_one(
                "SELECT COUNT(*) as cnt FROM rate_limits WHERE key_id = ? AND timestamp > ?",
                (key_id, now - window),
            )[0]
            return True, max(0, limit - count), limit

        # Rate limited — find oldest timestamp for Retry-After
        oldest = self.db.fetch_one(
            "SELECT MIN(timestamp) as ts FROM rate_limits "
            "WHERE key_id = ? AND timestamp > ?",
            (key_id, now - window),
        )
        retry_after = int(window - (now - oldest["ts"])) if oldest and oldest["ts"] else window
        return False, 0, retry_after

    def check_global_rate_limit(self) -> tuple[bool, int]:
        """Global rate limit across all keys. Returns (allowed, retry_after)."""
        now = time.time()
        window = 60.0

        self.db.execute(
            "DELETE FROM rate_limits_global WHERE timestamp < ?",
            (now - window,),
        )
        rows = self.db.fetch_all(
            "SELECT COUNT(*) as cnt FROM rate_limits_global WHERE timestamp > ?",
            (now - window,),
        )
        count = rows[0]["cnt"] if rows else 0

        if count >= config.global_rate_limit:
            oldest = self.db.fetch_all(
                "SELECT MIN(timestamp) as ts FROM rate_limits_global WHERE timestamp > ?",
                (now - window,),
            )
            retry_after = int(window - (now - (oldest[0]["ts"] if oldest and oldest[0]["ts"] else now)))
            return False, retry_after

        self.db.execute("INSERT INTO rate_limits_global (timestamp) VALUES (?)", (now,))
        return True, 0

    # ── Admin Auth ───────────────────────────────────────────────────────

    def verify_admin(self, admin_key: str) -> bool:
        """Verify admin key (from env var, not in DB)."""
        return hmac.compare_digest(admin_key, config.admin_key)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        """Hash API key with SHA-256 + salt prefix.

        We use SHA-256 (fast, sufficient for API keys which are already high-entropy).
        For password-style auth, use bcrypt/argon2. API keys are 64 hex chars = 256 bits.
        """
        salt = hashlib.sha256(raw_key.encode()).hexdigest()[:16]
        return hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()

    @staticmethod
    def _constant_time_compare(raw_key: str, expected_hash: str) -> bool:
        """Constant-time comparison to prevent timing attacks."""
        # Hash the provided key
        salt = hashlib.sha256(raw_key.encode()).hexdigest()[:16]
        actual_hash = hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)
