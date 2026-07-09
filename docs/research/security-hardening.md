# Security & Production Hardening — Cloud ML Inference Server (1GB RAM VPS)

> **Target:** Single 1GB RAM VPS, 20-100 game servers, ~300+ tree ensemble ML model  
> **Goal:** Production-grade security, anti-abuse, monitoring, and deployment hardening  
> **Constraints:** No Redis (insufficient RAM), no Docker overhead, SQLite for persistence

---

## Table of Contents

1. [API Key Management](#1-api-key-management)
2. [Rate Limiting Implementation](#2-rate-limiting-implementation)
3. [DoS Protection](#3-dos-protection)
4. [Model Stealing Prevention](#4-model-stealing-prevention)
5. [Input Validation](#5-input-validation)
6. [HTTPS + SSL](#6-https--ssl)
7. [Nginx Security Configuration](#7-nginx-security-configuration)
8. [systemd Service Hardening](#8-systemd-service-hardening)
9. [Monitoring & Metrics](#9-monitoring--metrics)
10. [Backup Strategy](#10-backup-strategy)
11. [Logging](#11-logging)
12. [SQLite WAL & Performance Tuning](#12-sqlite-wal--performance-tuning)
13. [Deployment Checklist](#13-deployment-checklist)

---

## 1. API Key Management

### 1.1 Key Generation (UUID v4)

```python
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

def generate_api_key() -> str:
    """Generate a URL-safe API key with prefix for identification."""
    prefix = "acml"  # ac-ml prefix for easy identification
    random_part = secrets.token_hex(24)  # 48 chars of hex = 192 bits
    key = f"{prefix}_{random_part}"
    return key

def generate_key_id(key: str) -> str:
    """Derive a key_id from the full key for database lookups.
    
    Key ID is a SHA-256 hash of the full key, truncated to 16 bytes.
    This allows O(1) lookup without storing the full key in plaintext.
    """
    return hashlib.sha256(key.encode()).hexdigest()[:32]

# Usage
api_key = generate_api_key()
# => "acml_1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f"
key_id = generate_key_id(api_key)
```

### 1.2 bcrypt Hashing in SQLite

The full API key is shown **once** at creation and must be stored as a bcrypt hash. The `key_id` (SHA-256 of the full key) is used for lookups — mapping `key_id -> bcrypt_hash`.

```python
import bcrypt

def hash_api_key(api_key: str) -> str:
    """Hash API key with bcrypt (cost factor 10 — good balance)."""
    return bcrypt.hashpw(
        api_key.encode('utf-8'),
        bcrypt.gensalt(rounds=10)
    ).decode('utf-8')

def verify_api_key(api_key: str, hashed: str) -> bool:
    """Verify an API key against its bcrypt hash."""
    return bcrypt.checkpw(
        api_key.encode('utf-8'),
        hashed.encode('utf-8')
    )
```

### 1.3 Database Schema

```sql
-- API Keys table
CREATE TABLE IF NOT EXISTS api_keys (
    key_id          TEXT PRIMARY KEY,          -- SHA-256 truncated, for lookups
    key_prefix      TEXT NOT NULL,             -- First 12 chars: "acml_1a2b3c4d" for UI display
    key_hash        TEXT NOT NULL,             -- bcrypt hash of full key
    server_id       TEXT NOT NULL UNIQUE,      -- "server_01", "server_02", etc.
    tier            TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','basic','pro','enterprise')),
    created_at      INTEGER NOT NULL,          -- Unix timestamp
    expires_at      INTEGER NOT NULL,          -- Unix timestamp (created_at + 365 days)
    revoked         INTEGER NOT NULL DEFAULT 0,-- 0 = active, 1 = revoked
    last_used_at    INTEGER,                   -- Last usage timestamp
    label           TEXT DEFAULT ''            -- Optional human label
);

CREATE INDEX idx_api_keys_server_id ON api_keys(server_id);
CREATE INDEX idx_api_keys_active ON api_keys(revoked) WHERE revoked = 0;

-- Rate limits table (sliding window)
CREATE TABLE IF NOT EXISTS rate_limits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL REFERENCES api_keys(key_id),
    timestamp   REAL NOT NULL,                 -- Unix timestamp with millis
    endpoint    TEXT DEFAULT ''
);

CREATE INDEX idx_rate_limits_key_id ON rate_limits(key_id);
CREATE INDEX idx_rate_limits_ts ON rate_limits(timestamp);
```

### 1.4 Key Lifecycle

```python
import time
from dataclasses import dataclass
from typing import Optional

@dataclass
class APIKeyRecord:
    key_id: str
    key_prefix: str
    server_id: str
    tier: str
    created_at: int
    expires_at: int
    revoked: bool
    last_used_at: Optional[int] = None

class APIKeyManager:
    """Manages API key creation, verification, rotation, and revocation."""
    
    KEY_DURATION_SECONDS = 365 * 24 * 3600  # 365 days
    TIER_LIMITS = {
        'free': 60,
        'basic': 600,
        'pro': 3000,
        'enterprise': 999999,
    }
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def create_key(self, server_id: str, tier: str = 'free',
                   label: str = '') -> tuple[str, APIKeyRecord]:
        """Create a new API key. Returns (full_key, record).
        
        The full key is returned ONCE and cannot be retrieved again.
        Store it securely on the client side.
        """
        api_key = generate_api_key()
        key_id = generate_key_id(api_key)
        key_hash = hash_api_key(api_key)
        now = int(time.time())
        
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO api_keys 
                    (key_id, key_prefix, key_hash, server_id, tier,
                     created_at, expires_at, label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key_id, api_key[:12], key_hash, server_id, tier,
                now, now + self.KEY_DURATION_SECONDS, label
            ))
            conn.commit()
            
            record = APIKeyRecord(
                key_id=key_id,
                key_prefix=api_key[:12],
                server_id=server_id,
                tier=tier,
                created_at=now,
                expires_at=now + self.KEY_DURATION_SECONDS,
                revoked=False
            )
            return api_key, record
        finally:
            conn.close()
    
    def verify_key(self, api_key: str) -> Optional[APIKeyRecord]:
        """Verify an API key. Returns record if valid, None otherwise."""
        key_id = generate_key_id(api_key)
        
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("""
                SELECT * FROM api_keys WHERE key_id = ?
            """, (key_id,)).fetchone()
            
            if row is None:
                return None
            
            # Check revocation
            if row['revoked']:
                return None
            
            # Check expiry
            now = int(time.time())
            if now > row['expires_at']:
                return None
            
            # Verify bcrypt hash
            if not verify_api_key(api_key, row['key_hash']):
                return None
            
            # Update last_used_at (async in production)
            conn.execute("""
                UPDATE api_keys SET last_used_at = ? WHERE key_id = ?
            """, (now, key_id))
            conn.commit()
            
            return APIKeyRecord(
                key_id=row['key_id'],
                key_prefix=row['key_prefix'],
                server_id=row['server_id'],
                tier=row['tier'],
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                revoked=bool(row['revoked']),
                last_used_at=row.get('last_used_at')
            )
        finally:
            conn.close()
    
    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key immediately."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "UPDATE api_keys SET revoked = 1 WHERE key_id = ?",
                (key_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def rotate_key(self, server_id: str, tier: str = 'free',
                   label: str = '') -> tuple[str, APIKeyRecord]:
        """Rotate key for a server: revoke old, create new."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            # Revoke all existing keys for this server
            conn.execute(
                "UPDATE api_keys SET revoked = 1 WHERE server_id = ?",
                (server_id,)
            )
            conn.commit()
        finally:
            conn.close()
        
        return self.create_key(server_id, tier, label)
```

### 1.5 Admin Key (Environment Variable)

The admin key bypasses the database entirely — it is set via environment variable and checked at startup:

```python
import os
import secrets

class AdminKeyManager:
    """Admin key is stored ONLY as an environment variable, never in DB.
    
    The admin key:
    - Can access /admin/* endpoints
    - Can create/revoke/rotate API keys
    - Bypasses rate limits
    - Must be set via ML_ADMIN_KEY env var
    - If not set, generate a strong one on first start and log it (for initial setup)
    """
    
    def __init__(self):
        self.admin_key = os.environ.get('ML_ADMIN_KEY')
        if not self.admin_key:
            # Generate a strong admin key and warn
            self.admin_key = f"acml_admin_{secrets.token_hex(32)}"
            import warnings
            warnings.warn(
                f"WARNING: ML_ADMIN_KEY not set. Generated temporary key:\n"
                f"  {self.admin_key}\n"
                f"  Set ML_ADMIN_KEY in environment or systemd unit!\n"
                f"  THIS KEY WILL CHANGE ON RESTART."
            )
    
    def verify(self, key: str) -> bool:
        """Constant-time comparison to prevent timing attacks."""
        if not self.admin_key:
            return False
        return secrets.compare_digest(key, self.admin_key)
```

### 1.6 Admin Endpoints (FastAPI)

```python
from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional

router = APIRouter(prefix="/admin", tags=["admin"])

async def require_admin(x_api_key: str = Header(alias="X-API-Key")):
    """Dependency: require valid admin key."""
    admin_mgr = AdminKeyManager()
    if not admin_mgr.verify(x_api_key):
        raise HTTPException(status_code=403, detail="Forbidden")
    return True

@router.post("/keys")
async def create_key(
    server_id: str,
    tier: str = "free",
    label: str = "",
    _=Depends(require_admin)
):
    """Create a new API key for a server."""
    key_mgr = APIKeyManager("data/acml.db")
    api_key, record = key_mgr.create_key(server_id, tier, label)
    return {
        "api_key": api_key,  # Shown ONCE
        "key_id": record.key_id,
        "server_id": record.server_id,
        "tier": record.tier,
        "expires_at": record.expires_at,
        "warning": "Save this key — it will not be shown again."
    }

@router.post("/keys/rotate")
async def rotate_key(
    server_id: str,
    tier: str = "free",
    label: str = "",
    _=Depends(require_admin)
):
    """Rotate key for a server (revokes all existing keys)."""
    key_mgr = APIKeyManager("data/acml.db")
    api_key, record = key_mgr.rotate_key(server_id, tier, label)
    return {
        "api_key": api_key,
        "key_id": record.key_id,
        "server_id": record.server_id,
        "tier": record.tier,
        "expires_at": record.expires_at,
        "warning": "Previous keys for this server have been revoked."
    }

@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, _=Depends(require_admin)):
    """Revoke an API key immediately."""
    key_mgr = APIKeyManager("data/acml.db")
    if key_mgr.revoke_key(key_id):
        return {"status": "revoked", "key_id": key_id}
    raise HTTPException(status_code=404, detail="Key not found")

@router.get("/keys")
async def list_keys(_=Depends(require_admin)):
    """List all API keys (without full key, only prefix)."""
    import sqlite3
    conn = sqlite3.connect("data/acml.db")
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT key_id, key_prefix, server_id, tier, created_at,
                   expires_at, revoked, last_used_at, label
            FROM api_keys ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

---

## 2. Rate Limiting Implementation

### 2.1 SQLite-Based Sliding Window

On a 1GB RAM VPS, Redis is not viable. SQLite with WAL mode handles this efficiently — tested at ~2000+ inserts/sec on a cheap VPS.

```python
import time
import sqlite3
from functools import wraps
from typing import Optional, Callable

TIER_LIMITS = {
    'free': 60,          # 60 requests per minute
    'basic': 600,        # 600 requests per minute
    'pro': 3000,         # 3000 requests per minute
    'enterprise': 999999 # effectively unlimited
}

WINDOW_SECONDS = 60  # 1-minute sliding window

class RateLimiter:
    """SQLite-based sliding window rate limiter.
    
    Design decisions:
    - Uses a single SQLite table with index on (key_id, timestamp)
    - Automatic cleanup of expired entries on every check
    - WAL mode for concurrent reads without write contention
    - Periodic VACUUM to prevent unbounded growth
    """
    
    def __init__(self, db_path: str = "data/acml.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id      TEXT NOT NULL,
                    timestamp   REAL NOT NULL,
                    endpoint    TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rl_lookup 
                ON rate_limits(key_id, timestamp)
            """)
            conn.commit()
        finally:
            conn.close()
    
    def check(self, key_id: str, tier: str) -> tuple[bool, int, int]:
        """Check rate limit. Returns (allowed, current_count, limit).
        
        Cleanup strategy: delete expired entries on every check.
        For production with high traffic, also run a periodic cleanup
        via cron every 5 minutes.
        """
        limit = TIER_LIMITS.get(tier, 60)
        now = time.time()
        window_start = now - WINDOW_SECONDS
        
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            # Step 1: Delete expired entries for this key
            conn.execute("""
                DELETE FROM rate_limits 
                WHERE key_id = ? AND timestamp < ?
            """, (key_id, window_start))
            
            # Step 2: Count current window entries
            count = conn.execute("""
                SELECT COUNT(*) FROM rate_limits 
                WHERE key_id = ? AND timestamp > ?
            """, (key_id, window_start)).fetchone()[0]
            
            if count >= limit:
                conn.commit()
                return False, count, limit
            
            # Step 3: Record this request
            conn.execute("""
                INSERT INTO rate_limits (key_id, timestamp) 
                VALUES (?, ?)
            """, (key_id, now))
            conn.commit()
            
            return True, count + 1, limit
        finally:
            conn.close()
    
    def cleanup_old_entries(self, cutoff_hours: int = 2):
        """Bulk cleanup of old entries (run via cron every 5-10 minutes).
        
        Since we delete on every check, this is mainly for keys that
        have stopped being used.
        """
        cutoff = time.time() - (cutoff_hours * 3600)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
            conn.commit()
        finally:
            conn.close()
    
    def get_usage_stats(self, key_id: str) -> dict:
        """Get current usage statistics for a key."""
        now = time.time()
        window_start = now - WINDOW_SECONDS
        
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("""
                SELECT COUNT(*) FROM rate_limits 
                WHERE key_id = ? AND timestamp > ?
            """, (key_id, window_start)).fetchone()[0]
            
            return {
                "current_usage": count,
                "window_seconds": WINDOW_SECONDS,
                "resets_in": max(0, WINDOW_SECONDS - (now % WINDOW_SECONDS))
            }
        finally:
            conn.close()
```

### 2.2 FastAPI Middleware

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting.
    
    Headers returned:
    - X-RateLimit-Limit: max requests per window
    - X-RateLimit-Remaining: remaining requests in window
    - X-RateLimit-Reset: seconds until window resets
    - Retry-After: seconds to wait (only on 429)
    """
    
    def __init__(self, app, db_path: str = "data/acml.db"):
        super().__init__(app)
        self.limiter = RateLimiter(db_path)
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health and admin endpoints
        if request.url.path in ('/health', '/metrics') or \
           request.url.path.startswith('/admin/'):
            return await call_next(request)
        
        # Get API key from header
        api_key = request.headers.get('X-API-Key', '')
        if not api_key:
            return Response(
                content='{"detail":"Missing X-API-Key header"}',
                status_code=401,
                media_type='application/json'
            )
        
        # Verify key and get tier
        key_mgr = APIKeyManager("data/acml.db")
        record = key_mgr.verify_key(api_key)
        if record is None:
            return Response(
                content='{"detail":"Invalid API key"}',
                status_code=403,
                media_type='application/json'
            )
        
        # Check rate limit
        allowed, current, limit = self.limiter.check(record.key_id, record.tier)
        
        if not allowed:
            retry_after = int(time.time() % 60)
            return Response(
                content=f'{{"detail":"Rate limit exceeded","retry_after":{retry_after}}}',
                status_code=429,
                media_type='application/json',
                headers={
                    'X-RateLimit-Limit': str(limit),
                    'X-RateLimit-Remaining': '0',
                    'X-RateLimit-Reset': str(retry_after),
                    'Retry-After': str(retry_after),
                }
            )
        
        # Store key info in request state for downstream use
        request.state.api_key_record = record
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers['X-RateLimit-Limit'] = str(limit)
        response.headers['X-RateLimit-Remaining'] = str(limit - current)
        response.headers['X-RateLimit-Reset'] = str(
            int(WINDOW_SECONDS - (time.time() % WINDOW_SECONDS))
        )
        
        return response
```

### 2.3 Periodic Cleanup Cron

```bash
# /etc/cron.d/acml-rate-limit-cleanup
# Clean up old rate limit entries every 10 minutes
*/10 * * * * acml /opt/ac-ml/venv/bin/python /opt/ac-ml/scripts/cleanup_rate_limits.py
```

```python
# /opt/ac-ml/scripts/cleanup_rate_limits.py
"""Cleanup script for rate limits table. Run via cron every 10 minutes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rate_limiter import RateLimiter

limiter = RateLimiter("data/acml.db")
limiter.cleanup_old_entries(cutoff_hours=2)
print(f"[{__import__('datetime').datetime.now()}] Rate limit cleanup complete")
```

---

## 3. DoS Protection

### 3.1 Multi-Layer Defense Architecture

```
                    Internet
                       |
                [Cloud/ISP-level]
                (DDoS mitigation if available)
                       |
                  [iptables]
             (rate limit by IP, port)
                       |
               [Nginx limit_req]
          (1000 req/min per IP, burst 200)
                       |
             [FastAPI Middleware]
         (global rate limit: 5000 req/min)
                       |
              [Application Logic]
          (SQLite rate limiter per key)
```

### 3.2 iptables (Initial Filter)

```bash
# /etc/iptables/rules.v4 (persistent rules)

# *filter
# :INPUT DROP [0:0]
# :FORWARD DROP [0:0]
# :OUTPUT ACCEPT [0:0]

# --- Connection limits ---
# Limit concurrent connections per IP to 16
-A INPUT -p tcp --dport 443 -m connlimit --connlimit-above 16 \
    --connlimit-mask 32 -j REJECT --reject-with tcp-reset

# --- Rate limit new connections ---
-A INPUT -p tcp --dport 443 --syn -m state --state NEW \
    -m recent --name acml_conn --set
-A INPUT -p tcp --dport 443 --syn -m state --state NEW \
    -m recent --name acml_conn --update --seconds 10 --hitcount 20 \
    -j DROP

# --- Drop invalid packets ---
-A INPUT -m state --state INVALID -j DROP
-A INPUT -p tcp --tcp-flags ALL NONE -j DROP
-A INPUT -p tcp --tcp-flags ALL ALL -j DROP
```

### 3.3 Nginx Rate Limiting

```nginx
# /etc/nginx/nginx.conf (inside http block)

# Rate limiting zones
limit_req_zone $binary_remote_addr zone=acml_global:10m rate=1000r/m;
limit_req_zone $binary_remote_addr zone=acml_burst:10m rate=500r/m burst=200;

# Connection limiting
limit_conn_zone $binary_remote_addr zone=acml_conn:10m;

# Request size
client_body_buffer_size 2k;
client_body_timeout 2s;
client_header_timeout 2s;
client_max_body_size 10k;
large_client_header_buffers 2 1k;

# Timeouts
keepalive_timeout 10;
keepalive_requests 100;
send_timeout 2s;

# Hide Nginx version
server_tokens off;
```

### 3.4 Nginx Server Block

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ml.ac.yourdomain.com;
    
    # SSL configuration (see Section 6)
    ssl_certificate /etc/letsencrypt/live/ml.ac.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ml.ac.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.3;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1h;
    ssl_session_tickets off;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "0" always;  # Deprecated, but harmless
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header Permissions-Policy "microphone=(), camera=(), geolocation=()" always;
    add_header Cache-Control no-store always;
    
    # Rate limiting
    limit_req zone=acml_global burst=200 nodelay;
    limit_conn acml_conn 16;
    
    # Root location
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_read_timeout 3s;
        proxy_connect_timeout 2s;
        proxy_send_timeout 2s;
        
        # Disable buffering for streaming responses
        proxy_buffering off;
        proxy_buffer_size 4k;
    }
    
    # Health check — restricted to internal IPs
    location /health {
        proxy_pass http://127.0.0.1:8080;
        access_log off;
        proxy_read_timeout 2s;
        
        allow 127.0.0.1;
        allow 10.0.0.0/8;   # Internal VPC
        allow YOUR_HOME_IP;  # Your IP
        deny all;
    }
    
    # Metrics — restricted to admin
    location /metrics {
        proxy_pass http://127.0.0.1:8080;
        access_log off;
        allow 127.0.0.1;
        allow YOUR_HOME_IP;
        deny all;
    }
    
    # Deny access to dotfiles
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
    
    location = /favicon.ico {
        access_log off;
        log_not_found off;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name ml.ac.yourdomain.com;
    
    # For Let's Encrypt ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    location / {
        return 301 https://$host$request_uri;
    }
}
```

### 3.5 fail2ban Configuration

```ini
# /etc/fail2ban/jail.local

[DEFAULT]
bantime = 900          # 15 minutes
findtime = 600          # 10 minute window
maxretry = 5            # 5 failures before ban
ignoreip = 127.0.0.1/8 ::1 YOUR_HOME_IP

[acml-auth]
enabled = true
port = http,https
filter = acml-auth
logpath = /opt/ac-ml/data/logs/access.json
maxretry = 5
findtime = 600
bantime = 900
```

```ini
# /etc/fail2ban/filter.d/acml-auth.conf

[Definition]
failregex = ^.*"status": 40[13].*"client_ip": "<HOST>".*"path": "/predict".*$
            ^.*"status": 429.*"client_ip": "<HOST>".*$
ignoreregex =
```

```bash
# Reload fail2ban
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
sudo fail2ban-client status acml-auth
```

### 3.6 Application-Level Global Rate Limit

```python
from collections import defaultdict
import time
import asyncio

class GlobalRateLimiter:
    """Simple in-memory global rate limiter as a last resort.
    
    Limits total requests across ALL keys to prevent runaway load
    from overwhelming the ML model (CPU-bound, ~10-50ms per prediction).
    
    5000 req/min global = ~83 req/s, well above expected traffic.
    """
    
    def __init__(self, max_requests: int = 5000, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = asyncio.Lock()
        self._requests: list[float] = []
    
    async def check(self) -> bool:
        """Check if global request is allowed. Thread-safe via asyncio.Lock."""
        now = time.time()
        cutoff = now - self.window_seconds
        
        async with self._lock:
            # Clean old entries
            self._requests = [t for t in self._requests if t > cutoff]
            
            if len(self._requests) >= self.max_requests:
                return False
            
            self._requests.append(now)
            return True
    
    async def cleanup(self):
        """Periodic cleanup placeholder (in-memory, runs on each check)."""
        pass  # Cleanup is done inline in check()
```

### 3.7 Request Size & Timeout Enforcement

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Enforce request size limits and timeouts at the application level."""
    
    MAX_BODY_SIZE = 10 * 1024  # 10KB
    REQUEST_TIMEOUT = 5.0  # seconds
    
    async def dispatch(self, request: Request, call_next):
        # Check Content-Length
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            return Response(
                content='{"detail":"Request too large"}',
                status_code=413,
                media_type='application/json'
            )
        
        # Process with timeout
        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.REQUEST_TIMEOUT
            )
            return response
        except asyncio.TimeoutError:
            return Response(
                content='{"detail":"Request timeout"}',
                status_code=408,
                media_type='application/json'
            )
```

---

## 4. Model Stealing Prevention

### 4.1 Threat Model

| Attack Vector | Risk | Mitigation |
|---|---|---|
| Mass querying with synthetic data | Medium | Rate limiting + feature distribution checks |
| Reconstructing tree structure | Low | 300+ tree ensemble makes reconstruction impractical |
| Extracting feature importance | High (if exposed) | Never return model metadata |
| Input perturbation probing | Medium | Detect abnormal feature distribution |
| Output-only extraction | Low | 3-decimal rounding destroys precision |

### 4.2 Rate Limiting (Primary Defense)

The most effective defense against model stealing is aggressive rate limiting. With 60 req/min for free tier and 600 for basic, extracting enough data points to reconstruct a 300+ tree gradient boosting model would take:

- Free tier (60 req/min): ~28 days for 1M queries
- Basic tier (600 req/min): ~2.8 days for 1M queries

By the time an attacker gathers useful data, the key would have been rotated or the pattern detected.

### 4.3 No Model Metadata

```python
from pydantic import BaseModel

class PredictResponse(BaseModel):
    """Prediction response — returns ONLY the risk score.
    
    NEVER expose:
    - Feature importance (no SHAP, no permutation importance)
    - Tree structure or depth
    - Leaf node assignments
    - Per-tree predictions
    - Model confidence or uncertainty (outside metrics endpoint)
    """
    risk: float
    
    class Config:
        # Prevent adding extra fields
        extra = 'forbid'
```

### 4.4 Input Perturbation Detection

```python
import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Optional

@dataclass
class FeatureProfile:
    """Expected distribution of each feature (derived from training data)."""
    means: np.ndarray
    stds: np.ndarray
    mins: np.ndarray
    maxs: np.ndarray

class AnomalyDetector:
    """Detect abnormal query patterns that suggest model stealing attempts.
    
    Signals of model stealing:
    1. Features follow a grid pattern (systematic probing)
    2. Features have near-zero variance across requests
    3. Features are at extremes (tail of distribution)
    4. Inter-request time is suspiciously consistent (scripted)
    """
    
    def __init__(self, profile: FeatureProfile, window_size: int = 100):
        self.profile = profile
        self.window_size = window_size
        self._recent_features: deque = deque(maxlen=window_size)
        self._recent_times: deque = deque(maxlen=window_size)
    
    def check(self, features: np.ndarray, timestamp: float) -> Optional[str]:
        """Check if request looks like model stealing. Returns reason or None."""
        reasons = []
        
        # 1. Check for NaN or Inf (should be caught by validation, but defense in depth)
        if np.any(np.isnan(features)) or np.any(np.isinf(features)):
            reasons.append("invalid_features")
        
        # 2. Check for extreme values (more than 5 standard deviations from mean)
        if self.profile.stds is not None:
            z_scores = np.abs((features - self.profile.means) / (self.profile.stds + 1e-10))
            extreme_count = np.sum(z_scores > 5)
            if extreme_count >= 3:  # 3+ features at extreme values
                reasons.append("extreme_values")
        
        # 3. Check for grid-like patterns (systematic probing)
        self._recent_features.append(features)
        if len(self._recent_features) >= 10:
            arr = np.array(self._recent_features)
            # Check for low variance across rows (same/similar inputs)
            col_stds = np.std(arr, axis=0)
            if np.any(col_stds < 1e-6) and len(self._recent_features) >= 20:
                reasons.append("suspiciously_identical_features")
            
            # Check for grid pattern (values repeating in cycle)
            for col in range(arr.shape[1]):
                unique_vals = np.unique(arr[-10:, col])
                if len(unique_vals) <= 2 and len(self._recent_features) >= 20:
                    reasons.append("grid_probing_detected")
                    break
        
        # 4. Check for robotic timing
        self._recent_times.append(timestamp)
        if len(self._recent_times) >= 10:
            intervals = np.diff(list(self._recent_times))
            if len(intervals) >= 5:
                interval_std = np.std(intervals)
                if interval_std < 0.01:  # Less than 10ms variance = bot
                    reasons.append("robotic_timing")
        
        return reasons[0] if reasons else None
```

### 4.5 Output Rounding

```python
def predict_risk(model, features: np.ndarray) -> float:
    """Run prediction and round to 3 decimal places.
    
    Rounding destroys fine-grained output differences that attackers
    use to reconstruct decision boundaries. With 300+ trees, rounding
    to 3 decimal places makes extraction exponentially harder.
    """
    raw_prediction = model.predict_proba(features.reshape(1, -1))[0, 1]
    return round(float(raw_prediction), 3)

# For ensemble models with multiple trees:
def predict_with_noise(model, features: np.ndarray, epsilon: float = 1e-8) -> float:
    """Add infinitesimal noise before rounding to prevent boundary detection."""
    raw = model.predict_proba(features.reshape(1, -1))[0, 1]
    # Tiny noise within rounding precision — prevents boundary walking
    noise = np.random.uniform(-epsilon, epsilon)
    return round(float(raw) + noise, 3)
```

### 4.6 Rate Limit Escalation on Suspicious Activity

```python
class EscalatingRateLimiter(RateLimiter):
    """Increase rate limiting strictness when model stealing is suspected."""
    
    def __init__(self, db_path: str = "data/acml.db"):
        super().__init__(db_path)
        self._suspicious_keys: dict[str, float] = {}  # key_id -> timestamp
    
    def mark_suspicious(self, key_id: str, duration_seconds: int = 300):
        """Mark a key as suspicious — reduces rate limit for 5 minutes."""
        self._suspicious_keys[key_id] = time.time() + duration_seconds
    
    def check(self, key_id: str, tier: str) -> tuple[bool, int, int]:
        # If key is marked suspicious, enforce strictest limit
        if key_id in self._suspicious_keys:
            if time.time() > self._suspicious_keys[key_id]:
                del self._suspicious_keys[key_id]
            else:
                # Downgrade to free-tier limits during suspicion period
                tier = 'free'
        
        return super().check(key_id, tier)
```

---

## 5. Input Validation

### 5.1 Pydantic Models with Strict Validation

```python
from pydantic import BaseModel, Field, validator, Extra
import numpy as np
from typing import Optional

class AimPredictRequest(BaseModel):
    """Strictly validated prediction request.
    
    Constraints:
    - features: exactly 6 floats, each in [-100, 100], no NaN/Inf
    - ping: 0-1000ms
    - tps: 0-20
    - jitter: 0-500ms
    - model_version: optional, must match known versions
    """
    
    features: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Exactly 6 feature values"
    )
    ping: int = Field(
        ...,
        ge=0,
        le=1000,
        description="Ping in milliseconds (0-1000)"
    )
    tps: float = Field(
        ...,
        ge=0,
        le=20,
        description="Ticks per second (0-20)"
    )
    jitter: int = Field(
        ...,
        ge=0,
        le=500,
        description="Jitter in milliseconds (0-500)"
    )
    model_version: Optional[str] = Field(
        None,
        min_length=1,
        max_length=20,
        description="Model version identifier"
    )
    
    @validator('features')
    def validate_features(cls, v):
        """Validate each feature value."""
        for i, f in enumerate(v):
            if np.isnan(f) or np.isinf(f):
                raise ValueError(f"Feature {i} is NaN or Infinity")
            if f < -100 or f > 100:
                raise ValueError(f"Feature {i} out of range [-100, 100]: {f}")
        return v
    
    @validator('model_version')
    def validate_model_version(cls, v):
        """Validate model version if provided."""
        if v is not None:
            valid_versions = {'v1', 'v1.1', 'v2', 'v2.1'}
            if v not in valid_versions:
                raise ValueError(f"Unknown model version: {v}. Valid: {valid_versions}")
        return v
    
    class Config:
        extra = Extra.forbid  # Reject unknown fields
        json_schema_extra = {
            "example": {
                "features": [0.5, -0.3, 0.1, 0.7, -0.2, 0.4],
                "ping": 45,
                "tps": 15.5,
                "jitter": 12,
                "model_version": "v2"
            }
        }
```

### 5.2 Response Model

```python
from pydantic import BaseModel, Field
from typing import Literal

class AimPredictResponse(BaseModel):
    """Prediction response with risk score and metadata."""
    
    risk: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Predicted risk score (0.0-1.0)"
    )
    model_version: str = Field(
        ...,
        description="Model version used for prediction"
    )
    
    class Config:
        extra = Extra.forbid

class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    error_code: Optional[str] = None
    
    class Config:
        extra = Extra.forbid
```

### 5.3 Sanitization Layer

```python
import json
import re
from typing import Any

class InputSanitizer:
    """Defense-in-depth sanitization before Pydantic validation.
    
    Strips:
    - SQL injection patterns
    - NoSQL injection patterns (if used)
    - Command injection in string fields
    - Extremely long strings
    """
    
    SQL_PATTERN = re.compile(
        r"(\b(union|select|insert|drop|delete|alter|create|update|'
          r'exec|eval|sleep|benchmark|load_file|into\s+outfile)\b)",
        re.IGNORECASE
    )
    SHELL_META = re.compile(r'[;&|`$(){}\[\]<>]')
    
    @classmethod
    def sanitize_string(cls, value: str, max_length: int = 100) -> str:
        if len(value) > max_length:
            raise ValueError(f"String exceeds max length {max_length}")
        if cls.SQL_PATTERN.search(value):
            raise ValueError("SQL keywords not allowed")
        if cls.SHELL_META.search(value):
            raise ValueError("Shell metacharacters not allowed")
        return value.strip()
    
    @classmethod
    def validate_content_type(cls, body: bytes, content_type: str):
        """Validate request content type."""
        if 'application/json' not in content_type.lower():
            raise ValueError("Only application/json accepted")
        if len(body) > 10 * 1024:
            raise ValueError("Body exceeds 10KB limit")
```

---

## 6. HTTPS + SSL

### 6.1 Let's Encrypt with Certbot

```bash
# Install certbot
sudo apt update
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx \
    -d ml.ac.yourdomain.com \
    --non-interactive \
    --agree-tos \
    --email your-email@example.com \
    --redirect

# Verify auto-renewal
sudo certbot renew --dry-run
```

### 6.2 Auto-Renewal (systemd Timer)

Certbot installs a systemd timer automatically, but verify and harden it:

```bash
# Check certbot timer status
sudo systemctl status certbot.timer

# The timer file is at:
# /lib/systemd/system/certbot.timer
```

```ini
# /lib/systemd/system/certbot.service
[Unit]
Description=Certbot automatic renewal
Documentation=https://certbot.eff.org

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --post-hook "systemctl reload nginx"
PrivateTmp=true
```

```ini
# /lib/systemd/system/certbot.timer
[Unit]
Description=Run certbot renewal twice daily

[Timer]
OnCalendar=*-*-* 00:00,12:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
```

### 6.3 TLS 1.3 Only Configuration

```nginx
# /etc/nginx/conf.d/ssl.conf
ssl_protocols TLSv1.3;
ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;
ssl_prefer_server_ciphers off;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1h;
ssl_session_tickets off;

# OCSP Stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 1.1.1.1 8.8.8.8 valid=300s;
resolver_timeout 5s;

# DH parameters (generate with: openssl dhparam -out /etc/nginx/dhparam.pem 2048)
ssl_dhparam /etc/nginx/dhparam.pem;
```

```bash
# Generate DH parameters (run once, takes a few minutes on 1GB VPS)
sudo openssl dhparam -out /etc/nginx/dhparam.pem 2048
```

### 6.4 SSL Test

```bash
# After deployment, test your SSL configuration:
# 1. https://www.ssllabs.com/ssltest/
# 2. Command line:
openssl s_client -connect ml.ac.yourdomain.com:443 -tls1_3
# 3. Check certificate details:
echo | openssl s_client -servername ml.ac.yourdomain.com \
    -connect ml.ac.yourdomain.com:443 2>/dev/null | openssl x509 -noout -dates
```

---

## 7. Nginx Security Configuration

### 7.1 Complete Nginx Configuration

```nginx
# /etc/nginx/nginx.conf
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 256;        # Reduced for 1GB RAM
    multi_accept on;
    use epoll;
    # Limit total connections
    # worker_connections * worker_processes = max connections
}

http {
    ##
    # Basic Settings
    ##
    sendfile on;
    tcp_nopush on;
    types_hash_max_size 2048;
    server_tokens off;             # Hide Nginx version
    
    # Server names hash
    server_names_hash_bucket_size 64;
    
    ##
    # MIME Types
    ##
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    ##
    # Logging
    ##
    access_log /var/log/nginx/acml-access.log;
    error_log /var/log/nginx/acml-error.log;
    
    ##
    # Rate Limiting Zones
    ##
    limit_req_zone $binary_remote_addr zone=acml_global:10m rate=1000r/m;
    limit_req_zone $binary_remote_addr zone=acml_burst:10m rate=500r/m burst=200;
    limit_conn_zone $binary_remote_addr zone=acml_conn:10m;
    
    ##
    # Security: Request Limits
    ##
    client_body_buffer_size 2k;
    client_body_timeout 2s;
    client_header_timeout 2s;
    client_max_body_size 10k;
    large_client_header_buffers 2 1k;
    
    ##
    # Timeouts
    ##
    keepalive_timeout 10;
    keepalive_requests 100;
    send_timeout 2s;
    
    ##
    # SSL Settings
    ##
    ssl_protocols TLSv1.3;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1h;
    ssl_session_tickets off;
    
    ##
    # Gzip Settings (disable for API — adds latency with minimal benefit for JSON)
    ##
    gzip off;
    
    ##
    # Virtual Host Configs
    ##
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

### 7.2 Nginx Security Checklist

- [ ] `server_tokens off` — hide Nginx version
- [ ] `client_max_body_size 10k` — prevent large request DoS
- [ ] `client_body_buffer_size 2k` — reduce buffer allocation
- [ ] Timeouts set to 2-3 seconds
- [ ] `limit_req_zone` configured with appropriate rates
- [ ] `limit_conn_zone` configured
- [ ] TLS 1.3 only
- [ ] Strong ciphers only
- [ ] HSTS with `includeSubDomains; preload`
- [ ] Health endpoint restricted to internal IPs
- [ ] No directory listing
- [ ] `.well-known` only for ACME
- [ ] `X-Frame-Options: DENY`
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `Permissions-Policy` — disable all unnecessary features

---

## 8. systemd Service Hardening

### 8.1 Main Service Unit

```ini
# /etc/systemd/system/acml.service
[Unit]
Description=AC ML Inference Server
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=acml
Group=acml
WorkingDirectory=/opt/ac-ml

# Environment
Environment=ML_ADMIN_KEY=sk-acml-prod-xxxxxx
Environment=ML_DB_PATH=/opt/ac-ml/data/acml.db
Environment=ML_MODEL_PATH=/opt/ac-ml/data/models
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

# Exec
ExecStart=/opt/ac-ml/venv/bin/uvicorn \
    --app-dir /opt/ac-ml \
    app.main:app \
    --host 127.0.0.1 \
    --port 8080 \
    --workers 1 \
    --loop uvloop \
    --http httptools \
    --no-access-log \
    --timeout-keep-alive 5
ExecReload=/bin/kill -s HUP $MAINPID

# Restart
Restart=always
RestartSec=5

# --- Resource Limits ---
# Memory (1GB VPS: leave ~100MB for OS + Nginx + monitoring)
MemoryMax=900M
MemoryHigh=800M
CPUQuota=80%
TasksMax=32

# File descriptors
LimitNOFILE=4096
LimitNPROC=256

# --- Security Hardening ---
# File system
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ac-ml/data /opt/ac-ml/data/logs

# Kernel
NoNewPrivileges=true
CapabilityBoundingSet=
AmbientCapabilities=
Capabilities=

# Processes
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectControlGroups=true
ProtectProc=invisible
ProcSubset=pid

# Network
# If only connecting to DB on same host:
PrivateNetwork=false  # Set true if no outbound connections needed

# Runtime
PrivateTmp=true
RemoveIPC=true

# System calls
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM

# Sandboxing
LockPersonality=true
RestrictRealtime=true
RestrictSUIDSGID=true
MemoryDenyWriteExecute=false  # Set true if using PyPy/numpy (may break some native libs)

[Install]
WantedBy=multi-user.target
```

### 8.2 Create Service User

```bash
# Create dedicated user for the ML service
sudo groupadd --system acml
sudo useradd --system --gid acml --no-create-home --shell /usr/sbin/nologin acml

# Create directories
sudo mkdir -p /opt/ac-ml/data/models
sudo mkdir -p /opt/ac-ml/data/logs

# Set ownership
sudo chown -R acml:acml /opt/ac-ml
sudo chmod 750 /opt/ac-ml
sudo chmod 750 /opt/ac-ml/data
sudo chmod 750 /opt/ac-ml/data/models
sudo chmod 770 /opt/ac-ml/data/logs  # Writable for logs
```

### 8.3 Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable acml
sudo systemctl start acml
sudo systemctl status acml

# View logs
sudo journalctl -u acml -f
sudo journalctl -u acml --since "1 hour ago"
```

### 8.4 Hardening Verification

```bash
# Check which protections are active
sudo systemd-analyze security acml

# Expected: Exposure level should be "SAFE" or "MEDIUM"
# If it shows "UNSAFE", review the recommendations

# Specific checks
sudo systemctl show acml -p MemoryMax
sudo systemctl show acml -p ProtectSystem
sudo systemctl show acml -p NoNewPrivileges
```

### 8.5 systemd Timer for Maintenance

```ini
# /etc/systemd/system/acml-maintenance.service
[Unit]
Description=AC ML maintenance tasks

[Service]
Type=oneshot
User=acml
WorkingDirectory=/opt/ac-ml
ExecStart=/opt/ac-ml/venv/bin/python /opt/ac-ml/scripts/maintenance.py
```

```ini
# /etc/systemd/system/acml-maintenance.timer
[Unit]
Description=Run AC ML maintenance daily

[Timer]
OnCalendar=daily
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable acml-maintenance.timer
sudo systemctl start acml-maintenance.timer
```

---

## 9. Monitoring & Metrics

### 9.1 Prometheus Metrics with `prometheus_client`

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from prometheus_client import start_http_server
import psutil
import time
import asyncio
from typing import Optional

# --- Inference Metrics ---

PREDICT_LATENCY = Histogram(
    'acml_predict_latency_milliseconds',
    'Inference latency in milliseconds',
    buckets=[5, 10, 25, 50, 100, 200, 500, 1000],
    labelnames=['model_version']
)

PREDICT_REQUESTS = Counter(
    'acml_predict_requests_total',
    'Total number of predict requests',
    labelnames=['model_version', 'status']  # status: ok, error, rate_limited, auth_failed
)

PREDICT_RISK_SCORE = Histogram(
    'acml_predict_risk_score',
    'Distribution of predicted risk scores',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    labelnames=['model_version']
)

# --- System Metrics ---

MEMORY_USAGE = Gauge(
    'acml_memory_usage_megabytes',
    'Process memory usage in MB',
    labelnames=['type']  # type: rss, vms, shared
)

CPU_USAGE = Gauge(
    'acml_cpu_usage_percent',
    'Process CPU usage percent'
)

ACTIVE_CONNECTIONS = Gauge(
    'acml_active_connections',
    'Number of currently active connections'
)

# --- Model Metrics ---

MODEL_UNCERTAINTY = Gauge(
    'acml_model_uncertainty',
    'Model prediction uncertainty (prediction entropy)',
    labelnames=['model_version']
)

MODEL_FEATURE_COUNT = Gauge(
    'acml_model_feature_count',
    'Number of features used by the model',
    labelnames=['model_version']
)

DB_QUERY_LATENCY = Histogram(
    'acml_db_query_latency_milliseconds',
    'Database query latency in milliseconds',
    buckets=[1, 5, 10, 25, 50, 100],
    labelnames=['query_type']  # query_type: read, write, rate_limit
)
```

### 9.2 Metrics Collection Loop

```python
class MetricsCollector:
    """Background task that collects system metrics every 15 seconds."""
    
    def __init__(self, interval_seconds: int = 15):
        self.interval = interval_seconds
        self._process = psutil.Process()
    
    async def run(self):
        """Run the collection loop (call from startup event)."""
        while True:
            try:
                with self._process.oneshot():
                    mem = self._process.memory_info()
                    cpu = self._process.cpu_percent()
                    
                    MEMORY_USAGE.labels(type='rss').set(mem.rss / 1024 / 1024)
                    MEMORY_USAGE.labels(type='vms').set(mem.vms / 1024 / 1024)
                    CPU_USAGE.set(cpu)
                    
                    # System-level memory
                    sys_mem = psutil.virtual_memory()
                    MEMORY_USAGE.labels(type='shared').set(
                        sys_mem.used / 1024 / 1024
                    )
                    
            except Exception as e:
                # Log but don't crash the loop
                import logging
                logging.warning(f"Metrics collection error: {e}")
            
            await asyncio.sleep(self.interval)
```

### 9.3 Metrics Endpoint

```python
from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

metrics_router = APIRouter()

@metrics_router.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint.
    
    Protected at Nginx level (restricted to internal IPs).
    Accessible by:
    - Prometheus server (scrape)
    - Admin monitoring dashboard
    """
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )
```

### 9.4 Prometheus Scrape Config (External Prometheus Server)

```yaml
# /etc/prometheus/prometheus.yml (on monitoring server)
scrape_configs:
  - job_name: 'acml-inference'
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: /metrics
    scheme: https
    static_configs:
      - targets: ['ml.ac.yourdomain.com:443']
    basic_auth:
      username: 'prometheus'
      password: 'your-prometheus-password'
    
  - job_name: 'acml-node'
    scrape_interval: 30s
    static_configs:
      - targets: ['YOUR_VPS_IP:9100']  # node_exporter
```

### 9.5 Grafana Dashboard Variables

- **Panel: Request Latency (p50, p95, p99)**
  - Query: `histogram_quantile(0.50, rate(acml_predict_latency_milliseconds_bucket[5m]))`
  - Query: `histogram_quantile(0.95, rate(acml_predict_latency_milliseconds_bucket[5m]))`
  - Query: `histogram_quantile(0.99, rate(acml_predict_latency_milliseconds_bucket[5m]))`

- **Panel: Request Rate**
  - Query: `rate(acml_predict_requests_total[5m])`

- **Panel: Error Rate**
  - Query: `rate(acml_predict_requests_total{status="error"}[5m]) / rate(acml_predict_requests_total[5m]) * 100`

- **Panel: Memory Usage**
  - Query: `acml_memory_usage_megabytes{type="rss"}`

- **Panel: Risk Score Distribution**
  - Query: `rate(acml_predict_risk_score_bucket[30m])`

### 9.6 Alert Rules

```yaml
# /etc/prometheus/alert.rules.yml
groups:
  - name: acml
    rules:
      - alert: HighErrorRate
        expr: rate(acml_predict_requests_total{status="error"}[5m]) / rate(acml_predict_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Error rate > 5% for 2 minutes"
          
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(acml_predict_latency_milliseconds_bucket[5m])) > 200
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "p95 latency > 200ms"
          
      - alert: MemoryNearLimit
        expr: acml_memory_usage_megabytes{type="rss"} > 700
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory usage > 700MB (approaching limit)"
          
      - alert: HighRateLimiting
        expr: rate(acml_predict_requests_total{status="rate_limited"}[5m]) > 10
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "High rate limiting activity"
```

---

## 10. Backup Strategy

### 10.1 Backup Script

```python
#!/usr/bin/env python3
# /opt/ac-ml/scripts/backup.py
"""Daily backup script. Run via systemd timer or cron.
Backups:
1. SQLite database (using .backup command for consistency)
2. Model files (tar.gz)
3. Configuration files

Retention: 7 daily backups
Off-site: S3 sync (optional, configurable)
"""

import shutil
import tarfile
import time
import os
from pathlib import Path
import sqlite3
import subprocess

BACKUP_DIR = Path("/opt/ac-ml/backups")
DATA_DIR = Path("/opt/ac-ml/data")
MODELS_DIR = Path("/opt/ac-ml/data/models")
CONFIG_FILES = [
    "/etc/nginx/sites-enabled/acml",
    "/etc/systemd/system/acml.service",
    "/etc/fail2ban/jail.local",
]
RETENTION_DAYS = 7

def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

def backup_database():
    """Backup SQLite database using .backup command (consistent snapshot)."""
    db_path = DATA_DIR / "acml.db"
    backup_path = BACKUP_DIR / f"db_{timestamp()}.sqlite"
    
    conn = sqlite3.connect(str(db_path))
    try:
        backup_conn = sqlite3.connect(str(backup_path))
        conn.backup(backup_conn, pages=1000)  # 1000 pages per iteration
        backup_conn.close()
    finally:
        conn.close()
    
    # Compress
    subprocess.run(
        ["gzip", str(backup_path)],
        check=True
    )
    return str(backup_path) + ".gz"

def backup_models():
    """Archive all model files."""
    backup_path = BACKUP_DIR / f"models_{timestamp()}.tar.gz"
    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(MODELS_DIR, arcname="models")
    return str(backup_path)

def backup_configs():
    """Backup configuration files."""
    backup_path = BACKUP_DIR / f"config_{timestamp()}.tar.gz"
    with tarfile.open(backup_path, "w:gz") as tar:
        for path in CONFIG_FILES:
            p = Path(path)
            if p.exists():
                tar.add(str(p), arcname=f"config/{p.name}")
    return str(backup_path)

def prune_old_backups():
    """Remove backups older than RETENTION_DAYS."""
    cutoff = time.time() - (RETENTION_DAYS * 86400)
    for f in BACKUP_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            print(f"Removed old backup: {f.name}")

def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"[{timestamp()}] Starting backup...")
    
    try:
        db_backup = backup_database()
        print(f"  Database: {db_backup}")
    except Exception as e:
        print(f"  Database backup FAILED: {e}")
    
    try:
        model_backup = backup_models()
        print(f"  Models: {model_backup}")
    except Exception as e:
        print(f"  Model backup FAILED: {e}")
    
    try:
        config_backup = backup_configs()
        print(f"  Configs: {config_backup}")
    except Exception as e:
        print(f"  Config backup FAILED: {e}")
    
    prune_old_backups()
    print(f"[{timestamp()}] Backup complete")

if __name__ == "__main__":
    main()
```

### 10.2 Backup Cron

```bash
# /etc/cron.d/acml-backup
# Run daily backup at 3 AM
0 3 * * * acml /opt/ac-ml/venv/bin/python /opt/ac-ml/scripts/backup.py >> /opt/ac-ml/data/logs/backup.log 2>&1
```

### 10.3 Off-Site Sync (Optional — S3/rsync)

```bash
# /opt/ac-ml/scripts/sync_backups.sh
#!/bin/bash
# Sync backups to S3 (optional: requires AWS CLI configured)
set -e

BACKUP_DIR="/opt/ac-ml/backups"
S3_BUCKET="s3://ac-ml-backups"

aws s3 sync "$BACKUP_DIR" "$S3_BUCKET/$(date +%Y/%m/%d)/" \
    --storage-class STANDARD_IA \
    --delete

echo "[$(date)] Backup sync to S3 complete"
```

---

## 11. Logging

### 11.1 JSON Structured Logging

```python
import json
import logging
import time
import uuid
from typing import Optional
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging.
    
    Format:
    {
        "timestamp": "2025-01-15T10:30:00.123Z",
        "level": "INFO",
        "logger": "acml",
        "request_id": "abc-123",
        "message": "Prediction completed",
        "model": "v2",
        "latency_ms": 45.2,
        "status": "ok",
        "client_ip": "192.168.x.xx",  # Anonymized
        "tier": "pro",
        "server_id": "server_01",
        "extra": { ... }
    }
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add request context if available
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        if hasattr(record, 'client_ip'):
            log_entry["client_ip"] = self._anonymize_ip(record.client_ip)
        if hasattr(record, 'model'):
            log_entry["model"] = record.model
        if hasattr(record, 'latency_ms'):
            log_entry["latency_ms"] = round(record.latency_ms, 2)
        if hasattr(record, 'status'):
            log_entry["status"] = record.status
        if hasattr(record, 'tier'):
            log_entry["tier"] = record.tier
        if hasattr(record, 'server_id'):
            log_entry["server_id"] = record.server_id
        
        # Add exception info
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }
        
        # Add extra fields dict
        if hasattr(record, 'extra') and record.extra:
            log_entry["extra"] = record.extra
        
        return json.dumps(log_entry, default=str)
    
    @staticmethod
    def _anonymize_ip(ip: str) -> str:
        """Anonymize IP address to last octet (GDPR compliance).
        
        192.168.1.42 -> 192.168.1.xx
        10.0.0.5 -> 10.0.0.xx
        ::1 -> ::xx
        """
        if '.' in ip:
            parts = ip.rsplit('.', 1)
            return f"{parts[0]}.xx"
        elif ':' in ip:
            return "::xx"
        return "unknown"
```

### 11.2 Logger Setup

```python
import logging
import sys
from pathlib import Path

def setup_logging(log_dir: str = "data/logs", level: str = "INFO"):
    """Configure structured JSON logging for the application."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Remove default handlers
    root_logger.handlers.clear()
    
    # File handler (JSON format)
    file_handler = logging.FileHandler(
        log_path / "acml.log",
        encoding='utf-8'
    )
    file_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(file_handler)
    
    # Error-specific file handler
    error_handler = logging.FileHandler(
        log_path / "acml-error.log",
        encoding='utf-8'
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(error_handler)
    
    # Console handler (human-readable for development)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root_logger.addHandler(console_handler)
    
    # Set uvicorn access log to WARNING to reduce noise
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    return root_logger


class RequestLogger:
    """Convenience class for logging with request context."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def log_request(self, request_id: str, client_ip: str, method: str,
                    path: str, status: int, latency_ms: float,
                    **kwargs):
        """Log an API request with context."""
        extra = {
            'request_id': request_id,
            'client_ip': client_ip,
            'method': method,
            'path': path,
            'status': status,
            'latency_ms': latency_ms,
        }
        extra.update(kwargs)
        
        self.logger.info(
            f"{method} {path} -> {status} ({latency_ms:.1f}ms)",
            extra=extra
        )
```

### 11.3 FastAPI Logging Middleware

```python
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time
import uuid

class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all requests with context and timing."""
    
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start_time = time.monotonic()
        
        # Store request_id in request state for downstream use
        request.state.request_id = request_id
        
        # Anonymize IP
        client_ip = request.client.host if request.client else "unknown"
        
        response = await call_next(request)
        
        latency_ms = (time.monotonic() - start_time) * 1000
        
        # Get logger and log
        logger = logging.getLogger("acml.request")
        request_logger = RequestLogger(logger)
        
        # Get extra context if available
        extra = {}
        if hasattr(request.state, 'api_key_record'):
            record = request.state.api_key_record
            extra['tier'] = record.tier
            extra['server_id'] = record.server_id
            extra['key_prefix'] = record.key_prefix
        
        request_logger.log_request(
            request_id=request_id,
            client_ip=client_ip,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
            **extra
        )
        
        # Add request_id to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response
```

### 11.4 Logrotate Configuration

```ini
# /etc/logrotate.d/acml
/opt/ac-ml/data/logs/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    dateext
    dateformat -%Y%m%d
    create 640 acml acml
    sharedscripts
    postrotate
        # Send SIGUSR1 to the Python process to reopen log files
        PID=$(systemctl show --property MainPID acml | cut -d= -f2)
        if [ "$PID" -gt 1 ]; then
            kill -USR1 $PID 2>/dev/null || true
        fi
    endscript
}

# Nginx logs
/var/log/nginx/acml-*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    create 640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 $(cat /var/run/nginx.pid)
    endscript
}
```

---

## 12. SQLite WAL & Performance Tuning

### 12.1 SQLite Configuration for High-Write Workload

```python
import sqlite3

def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a SQLite connection optimized for concurrent reads + writes."""
    conn = sqlite3.connect(
        db_path,
        timeout=30,          # Wait up to 30 seconds before raising timeout
        check_same_thread=False,  # Allow usage across threads (use with care)
        isolation_level=None  # Manual transaction control via BEGIN/COMMIT
    )
    
    # Performance PRAGMAs
    conn.execute("PRAGMA journal_mode=WAL")       # Write-Ahead Logging for concurrent reads
    conn.execute("PRAGMA synchronous=NORMAL")      # Balance between safety and speed
    conn.execute("PRAGMA cache_size=-8000")        # 8MB cache (negative = KB)
    conn.execute("PRAGMA page_size=4096")          # 4KB pages (default, explicit)
    conn.execute("PRAGMA temp_store=MEMORY")       # Temporary tables in memory
    conn.execute("PRAGMA mmap_size=268435456")     # 256MB memory-mapped I/O
    conn.execute("PRAGMA busy_timeout=5000")       # Wait 5s before failing on locked DB
    
    # Enable WAL autocheckpoint for crash recovery
    conn.execute("PRAGMA wal_autocheckpoint=1000") # Checkpoint every 1000 pages
    
    return conn
```

### 12.2 WAL Mode Benefits

| Feature | Default | WAL |
|---|---|---|
| Concurrent reads during writes | Blocked | Allowed |
| Write performance | ~200 writes/s | ~2000+ writes/s |
| Read performance (during write) | Slow | Fast (no lock) |
| Crash recovery | Rollback journal | WAL replay |
| Disk usage | Smaller | WAL file (~4MB typical) |

### 12.3 VACUUM Schedule

Run weekly to reclaim disk space from deleted rate limit entries:

```bash
# /etc/cron.weekly/acml-vacuum
#!/bin/bash
sqlite3 /opt/ac-ml/data/acml.db "VACUUM;"
sqlite3 /opt/ac-ml/data/acml.db "PRAGMA integrity_check;" >> /opt/ac-ml/data/logs/vacuum.log 2>&1
```

### 12.4 Optimizing Rate Limit Writes with Batch Insert

```python
class BatchRateLimiter(RateLimiter):
    """Rate limiter with batched inserts for higher throughput.
    
    Instead of INSERT per request, accumulate in memory and flush
    periodically. This trades a small amount of consistency for 
    drastically reduced write contention.
    """
    
    def __init__(self, db_path: str = "data/acml.db", batch_size: int = 100):
        super().__init__(db_path)
        self.batch_size = batch_size
        self._buffer: list[tuple[str, float]] = []
        self._buffer_lock = asyncio.Lock()
    
    async def check(self, key_id: str, tier: str) -> tuple[bool, int, int]:
        limit = TIER_LIMITS.get(tier, 60)
        now = time.time()
        window_start = now - WINDOW_SECONDS
        
        conn = get_connection(self.db_path)
        try:
            # Delete expired entries
            conn.execute("""
                DELETE FROM rate_limits 
                WHERE key_id = ? AND timestamp < ?
            """, (key_id, window_start))
            
            # Count current window entries
            count = conn.execute("""
                SELECT COUNT(*) FROM rate_limits 
                WHERE key_id = ? AND timestamp > ?
            """, (key_id, window_start)).fetchone()[0]
            
            # Include buffered entries in count
            async with self._buffer_lock:
                buffered_count = sum(
                    1 for k, t in self._buffer 
                    if k == key_id and t > window_start
                )
            
            total_count = count + buffered_count
            
            if total_count >= limit:
                conn.commit()
                return False, total_count, limit
            
            # Add to buffer instead of immediate INSERT
            async with self._buffer_lock:
                self._buffer.append((key_id, now))
                
                if len(self._buffer) >= self.batch_size:
                    conn.executemany(
                        "INSERT INTO rate_limits (key_id, timestamp) VALUES (?, ?)",
                        self._buffer
                    )
                    conn.commit()
                    self._buffer.clear()
            
            return True, total_count + 1, limit
        finally:
            conn.close()
    
    async def flush_buffer(self):
        """Flush any remaining buffered entries."""
        async with self._buffer_lock:
            if not self._buffer:
                return
            
            conn = get_connection(self.db_path)
            try:
                conn.executemany(
                    "INSERT INTO rate_limits (key_id, timestamp) VALUES (?, ?)",
                    self._buffer
                )
                conn.commit()
            finally:
                conn.close()
            
            self._buffer.clear()
```

---

## 13. Deployment Checklist

### 13.1 Pre-Deployment

| | Item | Status |
|---|---|---|
| [ ] | VPS provisioned (1GB RAM, 1-2 vCPU) |
| [ ] | OS: Ubuntu 22.04 LTS (minimal install) |
| [ ] | All packages updated: `apt update && apt upgrade` |
| [ ] | System configured: `timedatectl set-timezone UTC` |
| [ ] | Swap configured: 1GB swap file |
| [ ] | Firewall: only ports 22, 80, 443 open |
| [ ] | SSH: key-only auth, disable root login |

### 13.2 Installation

| | Item | Status |
|---|---|---|
| [ ] | Nginx installed and hardened |
| [ ] | certbot installed, SSL obtained |
| [ ] | fail2ban installed and configured |
| [ ] | `acml` system user created |
| [ ] | `/opt/ac-ml` directories created |
| [ ] | Python venv created (`python3 -m venv venv`) |
| [ ] | Dependencies installed |
| [ ] | SQLite database initialized |
| [ ] | Model files copied to `/opt/ac-ml/data/models/` |
| [ ] | `ML_ADMIN_KEY` set in systemd unit |
| [ ] | systemd unit enabled and started |

### 13.3 Security Verification

| | Item | Command/Check |
|---|---|---|
| [ ] | TLS 1.3 only | `openssl s_client -connect localhost:443 -tls1_2` should fail |
| [ ] | HSTS header | `curl -sI https://ml.ac.yourdomain.com | grep -i strict` |
| [ ] | Rate limiting | `curl -X POST ...` 60+ times; should get 429 |
| [ ] | Request size limit | Send >10KB body; should get 413 |
| [ ] | Health endpoint locked | Access from external IP; should get 403 |
| [ ] | Admin key required | Access `/admin/*` without key; should get 403 |
| [ ] | fail2ban active | `sudo fail2ban-client status acml-auth` |
| [ ] | No server tokens | `curl -sI ... | grep Server` should show "nginx" only |

### 13.4 Monitoring Verification

| | Item | Status |
|---|---|---|
| [ ] | `/metrics` endpoint accessible from authorized IPs |
| [ ] | Metrics collector running |
| [ ] | Prometheus scraping successfully |
| [ ] | Grafana dashboard configured |
| [ ] | Alert rules loaded |
| [ ] | Logging to JSON files |
| [ ] | Logrotate configured and tested |

### 13.5 Operational Procedures

#### Key Rotation
```bash
# Rotate a server key (admin API)
curl -X POST https://ml.ac.yourdomain.com/admin/keys/rotate \
  -H "X-API-Key: $ML_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"server_id": "server_01", "tier": "pro"}'
```

#### Key Revocation
```bash
# Revoke a compromised key
curl -X POST https://ml.ac.yourdomain.com/admin/keys/abc123/revoke \
  -H "X-API-Key: $ML_ADMIN_KEY"
```

#### Service Restart
```bash
sudo systemctl restart acml
# Check logs immediately:
sudo journalctl -u acml -n 50 -f
```

#### Disaster Recovery
```bash
# 1. Restore database
gunzip -c backups/db_20250115_030000.sqlite.gz > data/acml.db
# 2. Restore models
tar -xzf backups/models_20250115_030000.tar.gz -C data/
# 3. Restart service
sudo systemctl restart acml
```

### 13.6 1GB RAM Budget Allocation

| Component | RAM Allocation | Notes |
|---|---|---|
| OS (Ubuntu 22.04) | ~150-200MB | Idle, after boot |
| Nginx | ~20-30MB | Lightweight, handles proxying |
| **ML Service** | **~600-700MB** | **Prediction + model loading** |
| SQLite | ~50-100MB | WAL cache + page cache |
| fail2ban | ~20-30MB | Minimal |
| Monitoring agents | ~30-50MB | Node exporter, promtail |
| Buffer | ~50-100MB | Peak handling overhead |
| **Total** | **~950MB** | **Safe margin** |

#### Swap Configuration
```bash
# Create 1GB swap file (crucial for 1GB RAM VPS)
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Set swappiness low — prefer keeping ML model in RAM
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
```

---

## References

- [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [Nginx Rate Limiting](https://docs.nginx.com/nginx/admin-guide/security-controls/controlling-access-proxied-http/)
- [Certbot Documentation](https://certbot.eff.org/docs/)
- [systemd.service Resource Control](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)
- [Fail2ban Wiki](https://www.fail2ban.org/wiki/index.php/MANUAL_0_8)
- [Let's Encrypt Rate Limits](https://letsencrypt.org/docs/rate-limits/)
