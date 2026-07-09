# Cloud Inference Server — FastAPI cho MLSHybridAC

> **Mục tiêu:** Thiết kế production-ready FastAPI inference server cho Minecraft anticheat ML system.  
> **Kiến trúc:** Cloud SaaS — Plugin chỉ gửi feature + nhận action. Model hoàn toàn trên backend.  
> **RAM giới hạn:** 1GB VPS. **Không dùng container orchestration** — single uvicorn worker.

---

## Mục Lục

1. [File Structure](#1-file-structure)
2. [FastAPI Server Architecture](#2-fastapi-server-architecture)
3. [All API Endpoints (Chi Tiết)](#3-all-api-endpoints-chi-tit)
4. [Model Registry Pattern](#4-model-registry-pattern)
5. [Error Handling Strategy](#5-error-handling-strategy)
6. [Rate Limiting Implementation](#6-rate-limiting-implementation)
7. [1GB RAM Optimization](#7-1gb-ram-optimization)
8. [Data Layer](#8-data-layer)
9. [Deployment](#9-deployment)
10. [Full Code Files](#10-full-code-files)
11. [Testing](#11-testing)

---

## 1. File Structure

```
D:\Duancanhan\AC\cloud\
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app creation, lifespan, middleware
│   ├── config.py                  # Environment-based configuration
│   ├── models/
│   │   ├── __init__.py
│   │   ├── registry.py            # ModelRegistry singleton — lazy load + TTL unload
│   │   ├── aim_model.py           # LightGBM wrapper cho AimModel
│   │   ├── click_model.py         # Logistic Regression + online train
│   │   └── session_model.py       # SessionModel — weighted ensemble
│   ├── api/
│   │   ├── __init__.py
│   │   ├── schemas.py             # Pydantic request/response models
│   │   ├── predict.py             # /v1/predict/* endpoints
│   │   ├── training.py            # /v1/training/* endpoints
│   │   ├── admin.py               # /v1/admin/* endpoints
│   │   └── health.py              # /v1/health endpoint
│   ├── services/
│   │   ├── __init__.py
│   │   ├── fusion.py              # FusionEngine (Python port từ Java)
│   │   ├── rate_limiter.py        # Sliding window rate limiter
│   │   └── background.py          # Background tasks (model reload, cleanup)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py          # SQLite connection pool (single conn, WAL mode)
│   │   └── migrations.py          # Schema init + migrations
│   └── utils/
│       ├── __init__.py
│       ├── metrics.py             # Prometheus metrics (optional)
│       └── logger.py              # Structured logging setup
├── models/                        # Trained model files (symlinks + versioned)
│   ├── aim_v1.txt                 # LightGBM model (text format)
│   ├── aim_current.txt -> aim_20260701_v3.txt
│   ├── click_v1.json
│   ├── click_current.json -> click_20260701_v2.json
│   ├── session_v1.json
│   └── session_current.json -> session_20260701_v1.json
├── data/
│   ├── vnac.db                    # SQLite database
│   └── training/                  # Training samples CSV
│       ├── aim_samples.csv
│       ├── click_samples.csv
│       └── session_samples.csv
├── requirements.txt
├── Dockerfile
├── docker-compose.yml             # (optional) For local dev only
├── nginx.conf                     # Nginx reverse proxy config
├── vnac-ml.service                # systemd service file
└── logrotate.conf                 # Logrotate config
```

### So sánh với file structure cũ

| Cũ (`ml/`) | Mới (`cloud/`) | Lý do |
|---|---|---|
| `ml_server.py` — 500 dòng monolithic | `app/` — modular package | Maintainability, testing |
| Models inline trong server | `app/models/registry.py` + wrappers | Lazy loading, TTL unload, thread-safety |
| Không có config riêng | `app/config.py` | Environment-based, type-safe |
| Schema rải rác | `app/api/schemas.py` | Single source of truth |
| Fusion engine trong predict endpoint | `app/services/fusion.py` | Isolated, testable |
| models trong `/data/models/` | `models/` — symlinks + versioned | Hot-reload, version tracking |

---

## 2. FastAPI Server Architecture

### 2.1 App Lifespan Pattern

Sử dụng **lifespan** context manager (FastAPI >= 0.93) thay vì deprecated `startup` / `shutdown` events:

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.db.connection import DatabaseManager
from app.models.registry import ModelRegistry
from app.services.background import BackgroundTasks

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    # 1. Init database (WAL mode, create tables)
    db = DatabaseManager()
    await db.initialize()
    app.state.db = db

    # 2. Init model registry (NO preloading — lazy load)
    registry = ModelRegistry(model_dir=settings.MODEL_DIR)
    app.state.registry = registry

    # 3. Start background tasks
    bg = BackgroundTasks(registry)
    await bg.start()
    app.state.bg = bg

    yield  # Server is running

    # ── Shutdown ──
    # 1. Stop background tasks
    await bg.stop()

    # 2. Unload all models (release memory)
    await registry.unload_all()

    # 3. Close database
    await db.close()
```

### 2.2 Middleware Stack

```
Request
  │
  ▼
┌──────────────────────────────┐
│ 1. TrustedHostMiddleware     │ ← Chỉ allow domain/IP list
├──────────────────────────────┤
│ 2. CORSMiddleware            │ ← Allow specific origins
├──────────────────────────────┤
│ 3. RequestLoggingMiddleware  │ ← Log every request (method, path, status, duration)
├──────────────────────────────┤
│ 4. ConcurrencyMiddleware     │ ← Semaphore: max 16 concurrent predictions
├──────────────────────────────┤
│ 5. GCCollectMiddleware       │ ← gc.collect() mỗi 100 requests
├──────────────────────────────┤
│ 6. Route handlers            │
└──────────────────────────────┘
```

### 2.3 Async vs Sync — Quyết Định Kiến Trúc

**Nguyên tắc:** I/O-bound tasks dùng async, CPU-bound tasks chạy trong thread pool.

| Task | Async/Sync | Lý do |
|---|---|---|
| Request parsing/validation | `async` | FastAPI native, non-blocking |
| Database queries (SQLite) | `async` via `aiosqlite` | I/O-bound, tránh block event loop |
| Rate limit checking | `sync` (short) | < 1ms, không đáng kể |
| **Model inference (LightGBM)** | **`sync` in thread pool** | CPU-bound, block event loop |
| Fusion engine | `sync` | Pure math, microseconds |
| Logging | `async` | Fire-and-forget, non-blocking |
| Training trigger | `async` | Queued background job |

**Implementation detail** — chạy model inference trong thread pool:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
import functools

# Thread pool cho CPU-bound tasks
_inference_executor = ThreadPoolExecutor(max_workers=2)

async def run_inference_sync(fn, *args, **kwargs):
    """Run a synchronous model inference in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _inference_executor,
        functools.partial(fn, *args, **kwargs)
    )
```

### 2.4 Connection Pooling

Vì SQLite chỉ support 1 writer, không cần pool phức tạp. Dùng **single persistent connection** với WAL mode:

```python
# app/db/connection.py
import aiosqlite
from app.config import settings

class DatabaseManager:
    """Singleton DatabaseManager — single connection, WAL mode."""

    def __init__(self):
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self):
        self._conn = await aiosqlite.connect(settings.DB_PATH)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA cache_size=-4000")  # 4MB cache
        await self.run_migrations()

    async def execute(self, sql: str, params=None):
        async with self._conn.execute(sql, params or ()) as cursor:
            await self._conn.commit()
            return cursor

    async def fetchone(self, sql: str, params=None):
        async with self._conn.execute(sql, params or ()) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params=None):
        async with self._conn.execute(sql, params or ()) as cursor:
            return await cursor.fetchall()

    async def close(self):
        if self._conn:
            await self._conn.close()
```

### 2.5 Graceful Shutdown

Khi nhận SIGTERM/SIGINT:

1. **Stop accepting new requests** — uvicorn tự làm
2. **Drain active requests** — chờ semaphore release hết
3. **Unload models** — ModelRegistry.unload_all() → free memory
4. **Close DB** — WAL checkpoint + close connection
5. **Save training state** — flush any buffered samples

```python
# Trong lifespan shutdown:
async def shutdown(self):
    logger.info("Shutting down...")

    # Wait for active inferences to complete (max 30s)
    await self.active_requests.acquire()  # block until all done
    self.active_requests.release()

    # Release models
    registry = self.app.state.registry
    await registry.unload_all()

    # Checkpoint WAL + close
    db = self.app.state.db
    async with db._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"):
        pass
    await db.close()

    logger.info("Shutdown complete.")
```

---

## 3. All API Endpoints (Chi Tiết)

### 3.1 POST `/v1/predict/aim`

**Mục đích:** Dự đoán risk score cho aim behavior (rotation analysis).

**Input:**
```json
{
    "features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67],
    "ping": 45,
    "tps": 20.0,
    "jitter": 5.2
}
```

**Feature mapping:**
| Index | Name | Range | Source |
|---|---|---|---|
| 0 | yawJerkStdDev | [0, ∞) | `computeYawJerkStdDev() / sqrt(ping/50)` |
| 1 | pitchJerkStdDev | [0, ∞) | `computePitchJerkStdDev() / sqrt(ping/50)` |
| 2 | aimSmoothness | [0, 1] | Correlation between consecutive rotation deltas |
| 3 | rotationEntropy | [0, ~5] | Shannon entropy of rotation bins |
| 4 | gcdError | [0, ~0.5] | GCD error — low when aim assist repeating |
| 5 | snapFrequency | [0, ∞) | Rotation snaps per second > threshold |

**Output:**
```json
{
    "risk": 0.873,
    "confidence": 0.82,
    "model_version": "aim_20260701_v3"
}
```

**Logic (chi tiết):**
```python
@app.post("/v1/predict/aim")
async def predict_aim(req: AimRequest, auth=Depends(verify_key)):
    # 1. Validate features
    validated = validate_features(req.features, 6)

    # 2. Rate limit check
    rate_info = await check_rate_limit(auth["key_id"])

    # 3. Get model (lazy load)
    model = app.state.registry.get("aim")

    # 4. Predict in thread pool
    session = app.state.registry.current_version("aim")
    risk = await run_inference_sync(model.predict, validated)

    # 5. Apply runtime penalty
    penalty = compute_runtime_penalty(req.ping, req.tps, req.jitter)
    effective_risk = risk * (1.0 - penalty)

    # 6. Cap at 0.985 (model never says 100% certain)
    final_risk = min(effective_risk, 0.985)

    # 7. Compute confidence
    confidence = model.get_confidence(validated)

    # 8. Log request
    await log_request_async(auth["key_id"], "/v1/predict/aim", {
        "ping": req.ping, "tps": req.tps, "risk": final_risk
    })

    return AimResponse(
        risk=round(final_risk, 4),
        confidence=round(confidence, 4),
        model_version=session
    )
```

### 3.2 POST `/v1/predict/click`

**Input:**
```json
{
    "features": [0.88, 0.12, 0.34, 0.56, 0.03],
    "ping": 30,
    "tps": 20.0,
    "jitter": 3.1
}
```

**Feature mapping:**
| Index | Name | Range | Source |
|---|---|---|---|
| 0 | cooldownAccuracy | [0, 1] | Ratio of clicks at optimal cooldown timing |
| 1 | missRatio | [0, 1] | Ratio of clicks that missed target |
| 2 | hitMissRatio | [0, ∞) | Balance between hit and miss clicks |
| 3 | criticalRatio | [0, 1] | Ratio of critical hits |
| 4 | perfectStreak | [0, ∞) | Consecutive perfectly-timed clicks |

**Logic:**
```python
@app.post("/v1/predict/click")
async def predict_click(req: ClickRequest, auth=Depends(verify_key)):
    validated = validate_features(req.features, 5)
    rate_info = await check_rate_limit(auth["key_id"])
    model = app.state.registry.get("click")
    session = app.state.registry.current_version("click")
    risk = await run_inference_sync(model.predict, validated)

    penalty = compute_runtime_penalty(req.ping, req.tps, req.jitter)
    effective_risk = risk * (1.0 - penalty)
    final_risk = min(effective_risk, 0.985)

    confidence = model.get_confidence(validated)

    await log_request_async(auth["key_id"], "/v1/predict/click", {
        "ping": req.ping, "risk": final_risk
    })

    return PredictResponse(
        risk=round(final_risk, 4),
        confidence=round(confidence, 4),
        model_version=session
    )
```

### 3.3 POST `/v1/predict/session`

**Mục đích:** Behavioral profile — phát hiện ghost client, botting, long-term automation.

**Input:**
```json
{
    "features": [0.45, 0.23, 0.67, 0.12, 0.89, 0.34, 0.56, 0.78],
    "player_id": "uuid-here",
    "session_duration_seconds": 600,
    "ping": 50,
    "tps": 20.0
}
```

**Feature mapping:**
| Index | Feature | Range |
|---|---|---|
| 0 | cooldownAccuracy | [0, 1] |
| 1 | missRatio | [0, 1] |
| 2 | mouseSensitivity | [0, ∞) |
| 3 | pitchDeltaMean | [0, ∞) |
| 4 | yawDeltaMean | [0, ∞) |
| 5 | gcdConsistency | [0, 1] |
| 6 | rotationEntropy | [0, ~5] |
| 7 | normalizedSessionDuration | [0, 1] |

**Logic đặc biệt:** Session model KHÔNG auto-enforce theo Rule R7. Dùng weighted ensemble:
```python
WEIGHTS = [0.15, 0.10, 0.05, 0.10, 0.10, 0.20, 0.20, 0.10]
risk = sum(w * f for w, f in zip(WEIGHTS, features))
risk = 1.0 / (1.0 + math.exp(-4.0 * (risk - 0.5)))  # sigmoid sharpen
```

### 3.4 POST `/v1/predict/all` — Composite Endpoint

**Input:** Gộp tất cả features + context.

```json
{
    "aim_features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67],
    "click_features": [0.88, 0.12, 0.34, 0.56, 0.03],
    "session_features": [0.45, 0.23, 0.67, 0.12, 0.89, 0.34, 0.56, 0.78],
    "whitebox_context": {
        "certainty": 0.65,
        "category": "combat_aim",
        "vl": 15
    },
    "runtime_context": {
        "ping": 45,
        "tps": 20.0,
        "jitter": 5.2,
        "player_id": "uuid-here"
    },
    "server_id": "server-01",
    "client_version": "1.20.4"
}
```

**Output:**
```json
{
    "action": "alert",
    "risk": 0.734,
    "session_risk": 85.5,
    "rule": "R3",
    "confidence": 0.82,
    "model_versions": {
        "aim": "aim_20260701_v3",
        "click": "click_20260701_v2",
        "session": "session_20260701_v1"
    },
    "latency_ms": 4.2
}
```

**Logic:**
```python
@app.post("/v1/predict/all")
async def predict_all(req: PredictAllRequest, auth=Depends(verify_key)):
    start = time.monotonic()

    # 1. Validate all features
    aim_feats = validate_features(req.aim_features, 6) if req.aim_features else None
    click_feats = validate_features(req.click_features, 5) if req.click_features else None
    session_feats = validate_features(req.session_features, 8) if req.session_features else None
    rt = req.runtime_context

    # 2. Run models in parallel (asyncio.gather)
    tasks = []
    if aim_feats:
        tasks.append(run_inference(lambda: app.state.registry.get("aim").predict(aim_feats)))
    if click_feats:
        tasks.append(run_inference(lambda: app.state.registry.get("click").predict(click_feats)))
    if session_feats:
        tasks.append(run_inference(lambda: app.state.registry.get("session").predict(session_feats)))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    aim_risk = results[0] if len(results) > 0 and not isinstance(results[0], Exception) else 0.0
    idx = 0
    if aim_feats: idx += 1
    click_risk = results[idx] if len(results) > idx and not isinstance(results[idx], Exception) else 0.0
    if click_feats: idx += 1
    session_risk_ml = results[idx] if len(results) > idx and not isinstance(results[idx], Exception) else 0.0

    # 3. Whitebox certainty
    wb = req.whitebox_context
    wb_certainty = wb.get("certainty", 0.0)
    if not wb_certainty and "vl" in wb:
        wb_certainty = map_vl_to_certainty(wb.get("vl", 0))

    # 4. Fusion evaluate
    result = fusion_evaluate(
        whitebox_certainty=wb_certainty,
        category=wb.get("category", "unknown"),
        blackbox_risk=max(aim_risk, click_risk, session_risk_ml),
        blackbox_category="ml_ensemble",
        ping=rt.get("ping", 0),
        tps=rt.get("tps", 20.0),
        jitter=rt.get("jitter", 0),
        server_key=req.server_id,
    )

    # 5. Override with individual model scores
    result["risk"] = max(result["risk"], aim_risk, click_risk)
    session_risk = result.get("session_risk", 0)

    # 6. Confidence (use highest available)
    conf = 0.9
    if app.state.registry.get("aim").is_loaded:
        conf = max(conf, app.state.registry.get("aim").get_confidence(aim_feats or []))

    latency = (time.monotonic() - start) * 1000

    return CompositeResponse(
        action=result["action"],
        risk=round(result["risk"], 4),
        session_risk=round(session_risk, 2),
        rule=result["rule"],
        confidence=round(conf, 4),
        model_versions={
            "aim": app.state.registry.current_version("aim"),
            "click": app.state.registry.current_version("click"),
            "session": app.state.registry.current_version("session"),
        },
        latency_ms=round(latency, 1)
    )
```

### 3.5 POST `/v1/training/sample`

**Mục đích:** Thu thập training data từ server. Plugin gửi khi staff label hoặc auto-label từ whitebox.

**Input:**
```json
{
    "category": "aim",
    "features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67],
    "label": 1.0,
    "server_id": "server-01",
    "client_version": "1.20.4",
    "ping": 45,
    "label_source": "staff_review"
}
```

**Validation rules:**
- `category` must be one of: `aim`, `click`, `session`
- `features` length must match category: 6, 5, or 8
- `label` must be 0.0 (legit) or 1.0 (cheat), cho phép float intermediate
- `features` must not contain NaN or Infinity
- `server_id` max 64 chars

**Logic:**
```python
@app.post("/v1/training/sample")
async def collect_sample(req: TrainingSampleRequest, auth=Depends(verify_key)):
    # Validate feature length per category
    expected = {"aim": 6, "click": 5, "session": 8}
    if req.category not in expected:
        raise HTTPException(400, f"Invalid category: {req.category}")
    if len(req.features) != expected[req.category]:
        raise HTTPException(400, f"Expected {expected[req.category]} features, got {len(req.features)}")

    # Validate no NaN/Inf
    if any(math.isnan(f) or math.isinf(f) for f in req.features):
        raise HTTPException(400, "Features contain NaN or Infinity")

    # Store in SQLite
    await app.state.db.execute(
        """INSERT INTO training_samples
           (category, features, label, server_id, client_version, ping, label_source)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (req.category, json.dumps(req.features), req.label,
         req.server_id, req.client_version, req.ping, req.label_source)
    )

    # Append to CSV (for offline training pipeline)
    csv_path = DATA_DIR / "training" / f"{req.category}_samples.csv"
    csv_line = f"{datetime.now().isoformat()},{req.label},{','.join(map(str, req.features))},{req.server_id}\n"
    async with aiofiles.open(csv_path, "a") as f:
        await f.write(csv_line)

    return {"status": "accepted", "sample_id": cursor.lastrowid}
```

### 3.6 POST `/v1/train/trigger`

**Mục đích:** Trigger training job. Dùng để retrain model khi có đủ data mới.

**Auth:** Admin key (Bearer token)

**Input:** (empty body, hoặc optional config)
```json
{
    "model": "aim",
    "hyperparams": {
        "n_estimators": 50,
        "max_depth": 4,
        "learning_rate": 0.1
    }
}
```

**Logic:**
```python
@app.post("/v1/train/trigger")
async def trigger_training(req: TrainTriggerRequest, auth=Depends(verify_admin)):
    job_id = f"train_{uuid.uuid4().hex[:12]}"

    # Store job status in DB
    await app.state.db.execute(
        "INSERT INTO training_jobs (job_id, model, status, created_at) VALUES (?, ?, 'queued', ?)",
        (job_id, req.model or "all", datetime.now().isoformat())
    )

    # Queue to background task
    await app.state.bg.enqueue_training(job_id, req.model)

    return {"job_id": job_id, "status": "queued"}
```

### 3.7 GET `/v1/train/status/{job_id}`

```python
@app.get("/v1/train/status/{job_id}")
async def training_status(job_id: str, auth=Depends(verify_key)):
    row = await app.state.db.fetchone(
        "SELECT job_id, model, status, accuracy, model_version, error, created_at, finished_at FROM training_jobs WHERE job_id = ?",
        (job_id,)
    )
    if not row:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": row["job_id"],
        "model": row["model"],
        "status": row["status"],       # queued | running | done | failed
        "accuracy": row["accuracy"],
        "model_version": row["model_version"],
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"]
    }
```

### 3.8 GET `/v1/health`

```python
@app.get("/v1/health")
async def health():
    registry = app.state.registry
    models_loaded = []
    for name in ["aim", "click", "session"]:
        m = registry.get(name)
        if m.is_loaded:
            models_loaded.append(f"{name}@{registry.current_version(name)}")
        else:
            models_loaded.append(f"{name}:(unloaded)")

    import psutil
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024

    return {
        "status": "ok",
        "uptime": int(time.time() - startup_time),
        "models_loaded": models_loaded,
        "memory_mb": round(memory_mb, 1),
        "database_size_mb": round(os.path.getsize(settings.DB_PATH) / 1024 / 1024, 1),
        "requests_total": await get_total_requests(),
        "requests_today": await get_today_requests(),
        "timestamp": datetime.now().isoformat()
    }
```

### 3.9 POST `/v1/auth/verify`

**Mục đích:** Plugin gọi periodic (mỗi 1h) để verify key còn active.

```python
@app.post("/v1/auth/verify")
async def verify_key_endpoint(auth=Depends(verify_key)):
    return {
        "key_id": auth["key_id"],
        "tier": auth["tier"],
        "remaining": auth["remaining"],
        "status": "active",
        "server_time": datetime.now().isoformat()
    }
```

### 3.10 Admin Endpoints

**POST `/v1/admin/keys`** — Tạo API key:
```python
@app.post("/v1/admin/keys", dependencies=[Depends(verify_admin)])
async def create_key(req: KeyCreateRequest):
    key_id = "sk-" + secrets.token_hex(16)  # 32 hex chars
    expires = (datetime.now() + timedelta(days=req.duration_days)).isoformat()
    await app.state.db.execute(
        "INSERT INTO api_keys (key_id, server_name, tier, rate_limit, expires_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, req.server_name, req.tier, TIER_LIMITS.get(req.tier, 60), expires)
    )
    return {"key_id": key_id, "server_name": req.server_name, "tier": req.tier, "expires_at": expires}
```

**DELETE `/v1/admin/keys/{key_id}`** — Revoke key:
```python
@app.delete("/v1/admin/keys/{key_id}", dependencies=[Depends(verify_admin)])
async def revoke_key(key_id: str):
    await app.state.db.execute("UPDATE api_keys SET enabled = 0 WHERE key_id = ?", (key_id,))
    return {"status": "revoked", "key_id": key_id}
```

**GET `/v1/admin/stats`** — System stats:
```python
@app.get("/v1/admin/stats", dependencies=[Depends(verify_admin)])
async def admin_stats():
    keys = await app.state.db.fetchall("SELECT key_id, server_name, tier, requests_today, enabled FROM api_keys")
    total = await app.state.db.fetchone("SELECT COUNT(*) as cnt FROM request_logs")
    today = await app.state.db.fetchone("SELECT COUNT(*) as cnt FROM request_logs WHERE date(timestamp) = date('now')")
    return {
        "total_keys": len(keys),
        "total_requests": total["cnt"],
        "today_requests": today["cnt"],
        "keys": [
            {"key": k["key_id"][:12] + "...", "name": k["server_name"],
             "tier": k["tier"], "requests": k["requests_today"], "enabled": k["enabled"]}
            for k in keys
        ]
    }
```

---

## 4. Model Registry Pattern

### 4.1 Class Diagram

```
ModelRegistry (singleton)
├── _models: dict[str, BaseModel]
├── _locks: dict[str, asyncio.Lock]
├── _version_map: dict[str, str]
├── _last_access: dict[str, float]
├── _ttl: int = 300 (seconds)
│
├── get(name: str) -> BaseModel        # Lazy load + update last_access
├── unload(name: str)                  # Force unload 1 model
├── unload_all()                       # Unload tất cả (shutdown)
├── reload(name: str)                  # Hot-reload model từ disk
├── current_version(name: str) -> str  # Trả về version string
├── refresh_versions()                 # Scan symlinks, update version_map
│
RegistryTask (background)
├── scan_interval: int = 60 (seconds)
├── async def scan():                  # Check TTL + hot-reload every 60s
└── async def run():                   # Main loop
```

### 4.2 Implementation

```python
# app/models/registry.py
import os
import time
import glob
import logging
import asyncio
from pathlib import Path
from typing import Optional
from app.models.aim_model import AimModel
from app.models.click_model import ClickModel
from app.models.session_model import SessionModel

logger = logging.getLogger(__name__)

MODEL_CLASSES = {
    "aim": AimModel,
    "click": ClickModel,
    "session": SessionModel,
}

class ModelRegistry:
    """Thread-safe singleton model registry with lazy loading + TTL unload."""

    def __init__(self, model_dir: str, ttl: int = 300):
        self.model_dir = Path(model_dir)
        self._models: dict[str, Optional[BaseModel]] = {name: None for name in MODEL_CLASSES}
        self._locks: dict[str, asyncio.Lock] = {name: asyncio.Lock() for name in MODEL_CLASSES}
        self._version_map: dict[str, str] = {name: "unloaded" for name in MODEL_CLASSES}
        self._last_access: dict[str, float] = {name: 0.0 for name in MODEL_CLASSES}
        self._loaded_count: int = 0
        self.ttl = ttl

        # Scan model files on init
        self.refresh_versions()

    def refresh_versions(self):
        """Scan model directory for symlinks and version files."""
        for name in MODEL_CLASSES:
            symlink = self.model_dir / f"{name}_current.txt"
            if symlink.exists() or symlink.is_symlink():
                try:
                    resolved = symlink.resolve()
                    self._version_map[name] = resolved.stem  # e.g., "aim_20260701_v3"
                except (OSError, ValueError):
                    self._version_map[name] = "unknown"

    def find_model_path(self, name: str) -> Optional[Path]:
        """Find model file path: symlink first, then direct file."""
        # Priority 1: symlink
        symlink = self.model_dir / f"{name}_current.txt"
        if symlink.exists():
            return symlink

        # Priority 2: <name>.model (legacy)
        legacy = self.model_dir / f"{name}.model"
        if legacy.exists():
            return legacy

        # Priority 3: <name>_current.json
        json_path = self.model_dir / f"{name}_current.json"
        if json_path.exists():
            return json_path

        # Priority 4: any versioned file matching pattern
        pattern = str(self.model_dir / f"{name}_v*.txt")
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return Path(matches[0])

        pattern = str(self.model_dir / f"{name}_v*.json")
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return Path(matches[0])

        return None

    async def get(self, name: str):
        """Get model instance — lazy load if not loaded."""
        if name not in self._models:
            raise ValueError(f"Unknown model: {name}. Available: {list(self._models.keys())}")

        self._last_access[name] = time.time()

        if self._models[name] is not None:
            return self._models[name]

        # Lazy load with lock (prevent double-load)
        async with self._locks[name]:
            # Double-check after acquiring lock
            if self._models[name] is not None:
                return self._models[name]

            model_path = self.find_model_path(name)
            if model_path is None:
                logger.warning(f"No model file found for {name}, returning untrained model")
                self._models[name] = MODEL_CLASSES[name](path=None)
            else:
                logger.info(f"Loading model '{name}' from {model_path}")
                try:
                    self._models[name] = MODEL_CLASSES[name](path=str(model_path))
                    self._loaded_count += 1
                    self.refresh_versions()
                    logger.info(f"Model '{name}' loaded (v{self._version_map[name]})")
                except Exception as e:
                    logger.error(f"Failed to load model '{name}': {e}")
                    self._models[name] = MODEL_CLASSES[name](path=None)  # Fallback to untrained

            return self._models[name]

    async def unload(self, name: str):
        """Unload a single model to free memory."""
        async with self._locks[name]:
            if self._models[name] is not None:
                self._models[name].unload()
                self._models[name] = None
                self._loaded_count -= 1
                logger.info(f"Model '{name}' unloaded (TTL expired)")

    async def unload_all(self):
        """Unload all models — called during shutdown."""
        for name in list(self._models.keys()):
            await self.unload(name)
        logger.info("All models unloaded")

    async def reload(self, name: str):
        """Hot-reload a model — used when new version detected."""
        await self.unload(name)
        await self.get(name)

    def current_version(self, name: str) -> str:
        return self._version_map.get(name, "unknown")

    def is_loaded(self, name: str) -> bool:
        return self._models.get(name) is not None
```

### 4.3 Background TTL Scanner

```python
# app/services/background.py
class BackgroundTasks:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self._tasks = []

    async def start(self):
        # TTL scanner — chạy mỗi 60s
        self._tasks.append(asyncio.create_task(self._ttl_scanner()))
        # Hot-reload scanner — check model file changes
        self._tasks.append(asyncio.create_task(self._hot_reload_scanner()))
        logger.info("Background tasks started")

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("Background tasks stopped")

    async def _ttl_scanner(self):
        """Unload models that haven't been accessed in TTL seconds."""
        while True:
            await asyncio.sleep(60)  # Check every 60 seconds
            now = time.time()
            for name in self.registry._models:
                if self.registry._models[name] is not None:
                    elapsed = now - self.registry._last_access[name]
                    if elapsed > self.registry.ttl:
                        logger.info(f"Model '{name}' idle for {elapsed:.0f}s, unloading")
                        await self.registry.unload(name)

    async def _hot_reload_scanner(self):
        """Check if model files changed -> reload."""
        last_mtimes = {}
        while True:
            await asyncio.sleep(30)
            for name in ["aim", "click", "session"]:
                path = self.registry.find_model_path(name)
                if path is None:
                    continue
                mtime = path.stat().st_mtime
                cached = last_mtimes.get(name)
                if cached is not None and mtime > cached:
                    logger.info(f"Model '{name}' file changed, hot-reloading...")
                    await self.registry.reload(name)
                last_mtimes[name] = mtime
```

### 4.4 Version Management

```
models/
├── aim_20260701_v1.txt      # Version 1 — trained 2026-07-01
├── aim_20260715_v2.txt      # Version 2 — trained 2026-07-15
├── aim_20260801_v3.txt      # Version 3 — trained 2026-08-01
├── aim_current.txt ──symlink──> aim_20260801_v3.txt
│
├── click_20260701_v1.json
├── click_20260720_v2.json
├── click_current.json ──symlink──> click_20260720_v2.json
│
├── session_20260701_v1.json
└── session_current.json ──symlink──> session_20260701_v1.json
```

**Script update model version:**
```bash
# Khi deploy model mới:
cp /tmp/new_aim.model models/aim_20260801_v3.txt
ln -sf aim_20260801_v3.txt models/aim_current.txt
# Server tự động reload trong 30s
```

### 4.5 BaseModel Interface

```python
# app/models/base.py
from abc import ABC, abstractmethod
from typing import Optional

class BaseModel(ABC):
    """Abstract base class for all ML models."""

    def __init__(self, path: Optional[str] = None):
        self._is_loaded = False
        self._version = "untrained"
        if path:
            self.load(path)

    @abstractmethod
    def load(self, path: str):
        ...

    def unload(self):
        """Free memory. Override if model has large objects."""
        self._model = None
        self._is_loaded = False

    @abstractmethod
    def predict(self, features: list[float]) -> float:
        ...

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def get_confidence(self, features: list[float]) -> float:
        """Default confidence — override for model-specific logic."""
        return 0.9 if self._is_loaded else 0.5
```

---

## 5. Error Handling Strategy

### 5.1 Error Classification

| Error Type | HTTP Status | Response | Recovery |
|---|---|---|---|
| Model not loaded | 503 | `{"detail": "Model not loaded", "retry_after": 5}` | Trigger lazy load |
| Invalid features (NaN/Inf) | 400 | `{"detail": "Invalid features", "field": "features[2]"}` | Log + reject |
| Feature out of range | 200 (clamped) | Risk với warning log | Clamp, không reject |
| LightGBM predict exception | 500 | `{"detail": "Inference failed"}` | Log stack trace, return 0.5 |
| Rate limit exceeded | 429 | `{"detail": "Rate limit", "retry_after": 30}` | Retry-After header |
| Invalid API key | 401 | `{"detail": "Invalid API key"}` | — |
| API key disabled | 403 | `{"detail": "API key disabled"}` | — |
| Request timeout (>10s) | 504 | `{"detail": "Request timeout"}` | asyncio timeout wrapper |
| Training job not found | 404 | `{"detail": "Job not found"}` | — |

### 5.2 Exception Handlers

```python
# app/main.py — custom exception handlers

@app.exception_handler(ModelNotLoadedError)
async def model_not_loaded_handler(request, exc):
    # Trigger lazy load in background
    asyncio.create_task(request.app.state.registry.get(exc.model_name))
    return JSONResponse(
        status_code=503,
        content={"detail": f"Model '{exc.model_name}' not loaded", "retry_after": 5},
        headers={"Retry-After": "5"}
    )

@app.exception_handler(InvalidFeaturesError)
async def invalid_features_handler(request, exc):
    logger.warning(f"Invalid features from {request.client.host}: {exc}")
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc), "field": exc.field}
    )

@app.exception_handler(RateLimitError)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded", "retry_after": exc.retry_after},
        headers={"Retry-After": str(exc.retry_after)}
    )
```

### 5.3 Feature Validation

```python
def validate_features(features: list[float], expected_len: int) -> list[float]:
    """Validate + clamp features. Raise InvalidFeaturesError on NaN/Inf."""
    if len(features) != expected_len:
        raise InvalidFeaturesError(
            f"Expected {expected_len} features, got {len(features)}",
            field="features"
        )

    validated = []
    for i, f in enumerate(features):
        if math.isnan(f) or math.isinf(f):
            raise InvalidFeaturesError(
                f"Feature[{i}] is {f}",
                field=f"features[{i}]"
            )
        # Clamp extreme values — prevent model instability
        if f > 1e6:
            validated.append(1e6)
            logger.warning(f"Feature[{i}] clamped from {f} to 1e6")
        elif f < -1e6:
            validated.append(-1e6)
        else:
            validated.append(f)

    return validated
```

### 5.4 Timeout Handling

```python
async def run_inference_with_timeout(fn, timeout: float = 5.0, *args, **kwargs):
    """Run model inference with hard timeout."""
    try:
        return await asyncio.wait_for(
            run_inference_sync(fn, *args, **kwargs),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error(f"Inference timeout after {timeout}s")
        raise InferenceTimeoutError(f"Model inference timed out after {timeout}s")
```

### 5.5 Graceful Degradation

Khi model inference fail:

```python
# Trong predict endpoint:
try:
    risk = await run_inference_with_timeout(model.predict, timeout=3.0, features=validated)
except (InferenceTimeoutError, Exception) as e:
    logger.error(f"Inference failed for {category}: {e}")
    # Fallback: heuristic default
    risk = 0.5  # Trung lập — không flag ai
    confidence = 0.1  # Rất thấp — fusion sẽ ignore
```

---

## 6. Rate Limiting Implementation

### 6.1 Architecture

```
Sliding Window per API Key
┌─────────────────────────────────────────────┐
│  Window: 60s                                │
│  ┌─────┬─────┬─────┬─────┬─────┬─────┐     │
│  │ 12  │  8  │ 15  │  3  │  0  │  5  │     │
│  └─────┴─────┴─────┴─────┴─────┴─────┘     │
│  Window duration: each bucket = 10s         │
│  Count: 43 requests in last 60s             │
│  Limit: 60 → remaining = 17                 │
└─────────────────────────────────────────────┘
```

### 6.2 Rate Limit SQLite Table

```sql
CREATE TABLE IF NOT EXISTS rate_counters (
    key_id TEXT NOT NULL,
    window_start INTEGER NOT NULL,  -- Unix timestamp (seconds)
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, window_start)
);
```

### 6.3 Tiers

| Tier | Limit | Bucket Fill Rate | Burst |
|---|---|---|---|
| free | 60/min | 1 req/sec | 10 |
| basic | 600/min | 10 req/sec | 50 |
| pro | 3000/min | 50 req/sec | 200 |
| enterprise | unlimited | — | — |
| admin | unlimited | — | — |

### 6.4 Global Rate Limit

```python
GLOBAL_LIMIT_PER_MINUTE = 5000

async def check_global_rate_limit(db):
    """Global rate limit — protect server từ overload."""
    cutoff = int(time.time()) - 60
    row = await db.fetchone(
        "SELECT SUM(count) as total FROM rate_counters WHERE window_start > ?",
        (cutoff,)
    )
    total = row["total"] or 0
    if total >= GLOBAL_LIMIT_PER_MINUTE:
        raise RateLimitError(retry_after=30, detail="Global rate limit exceeded")
    return total
```

### 6.5 Implementation

```python
# app/services/rate_limiter.py
import time
import logging
from fastapi import Header, HTTPException, Depends
from typing import Optional

logger = logging.getLogger(__name__)

TIER_LIMITS = {
    "free": 60,
    "basic": 600,
    "pro": 3000,
    "enterprise": None,  # Unlimited
}

TIER_FREE_TRIAL = {
    "requests_per_day": 10000,
}

GLOBAL_LIMIT_PER_MINUTE = 5000

class RateLimitError(Exception):
    def __init__(self, retry_after: int, detail: str = "Rate limit exceeded"):
        self.retry_after = retry_after
        self.detail = detail
        super().__init__(self.detail)

async def check_rate_limit(key_id: str, db) -> dict:
    """Check rate limit for API key. Raise 429 if exceeded."""
    # Get key info
    row = await db.fetchone(
        "SELECT tier, rate_limit, enabled, requests_today, expires_at FROM api_keys WHERE key_id = ?",
        (key_id,)
    )
    if not row:
        raise HTTPException(403, "Invalid API key")
    if not row["enabled"]:
        raise HTTPException(403, "API key disabled")

    # Check expiry
    if row["expires_at"] and row["expires_at"] < datetime.now().isoformat():
        raise HTTPException(403, "API key expired")

    tier = row["tier"]
    limit = row["rate_limit"] if row["rate_limit"] > 0 else TIER_LIMITS.get(tier, 60)

    # Enterprise = unlimited
    if limit is None:
        return {"tier": tier, "limit": None, "remaining": None}

    # Global rate limit
    await check_global_rate_limit(db)

    # Sliding window: count requests in last 60s
    window_start = int(time.time()) - 60
    row = await db.fetchone(
        "SELECT COALESCE(SUM(count), 0) as total FROM rate_counters WHERE key_id = ? AND window_start > ?",
        (key_id, window_start)
    )
    count = row["total"]
    remaining = max(0, limit - count)

    if remaining == 0:
        # Find when the window expires
        oldest_row = await db.fetchone(
            "SELECT MIN(window_start) as oldest FROM rate_counters WHERE key_id = ? AND window_start > ?",
            (key_id, window_start)
        )
        retry_after = max(1, (oldest_row["oldest"] + 60) - int(time.time()))
        raise RateLimitError(retry_after=retry_after)

    # Increment counter
    current_window = int(time.time()) // 10 * 10  # 10s bucket granularity
    await db.execute(
        "INSERT INTO rate_counters (key_id, window_start, count) VALUES (?, ?, 1) "
        "ON CONFLICT(key_id, window_start) DO UPDATE SET count = count + 1",
        (key_id, current_window)
    )

    # Update daily counter
    await db.execute(
        "UPDATE api_keys SET requests_today = requests_today + 1 WHERE key_id = ?",
        (key_id,)
    )

    return {"tier": tier, "limit": limit, "remaining": remaining - 1}

async def verify_key(authorization: Optional[str] = Header(None)):
    """Dependency: verify API key + rate limit."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    key_id = authorization[7:]

    # Admin bypass
    if key_id == settings.ADMIN_KEY:
        return {"key_id": "admin", "tier": "admin", "remaining": 999999}

    return await check_rate_limit(key_id, app.state.db)
```

---

## 7. 1GB RAM Optimization

### 7.1 Memory Budget Breakdown

| Component | Memory | Notes |
|---|---|---|
| Python runtime + FastAPI | ~40MB | Base overhead |
| Uvicorn + ASGI loop | ~15MB | Single worker |
| aiosqlite + cache | ~8MB | PRAGMA cache_size = -4000 (4MB) |
| LightGBM model (Aim) | ~15MB | 30 trees, depth 4, text format |
| ClickModel | ~1KB | Logistic regression, 5 weights |
| SessionModel | ~100B | 8 weights only |
| Request objects (peak) | ~50MB | 16 concurrent * ~3MB each |
| GC overhead | ~30MB | Python garbage collector |
| OS buffers | ~100MB | File system cache |
| **Total** | **~260MB** | Headroom: ~740MB |

### 7.2 Critical Rules

#### Rule 1: SINGLE UVICORN WORKER

```python
# docker-compose.yml / uvicorn command
# ❌ KHÔNG dùng --workers > 1 — mỗi worker copy model vào RAM
# ✅ Dùng single worker + asyncio concurrency
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "16"]
```

**Giải thích:** Mỗi uvicorn worker là một process riêng. 2 workers = 2 copies của model trong RAM. Với single worker, asyncio vẫn xử lý concurrent requests được nhờ async/await. Model inference chạy trong thread pool (không block event loop).

#### Rule 2: Semaphore — Max 16 Concurrent Predictions

```python
# app/main.py (middleware)
from asyncio import Semaphore

inference_semaphore = Semaphore(16)

@app.middleware("http")
async def concurrency_middleware(request: Request, call_next):
    if request.url.path.startswith("/v1/predict/"):
        async with inference_semaphore:
            return await call_next(request)
    return await call_next(request)
```

**Tại sao 16:**
- 1 thread trong pool => ~1-2ms inference
- 16 concurrent = ~32ms max wait for last request
- Với 1 worker, event loop vẫn phục vụ health check và other endpoints

#### Rule 3: gc.collect() Sau Mỗi 100 Requests

```python
# app/middleware.py
request_counter = 0
GC_INTERVAL = 100

@app.middleware("http")
async def gc_collect_middleware(request: Request, call_next):
    response = await call_next(request)
    global request_counter
    request_counter += 1
    if request_counter >= GC_INTERVAL:
        request_counter = 0
        gc.collect()  # Force garbage collection
    return response
```

#### Rule 4: max_requests = 10000 — Restart để Tránh Memory Leak

```python
# Trong uvicorn command:
uvicorn ... --workers 1 --limit-max-requests 10000
```

Khi uvicorn process đạt 10000 requests, nó sẽ tự graceful shutdown và restart. Điều này clear mọi memory leak tiềm ẩn.

#### Rule 5: Model Lazy Loading + TTL Unload

Đã implement trong Model Registry (Section 4). Models chỉ load khi có request đầu tiên, tự unload sau 5 phút không dùng.

#### Rule 6: ONNX Quantization Path (Future)

Khi model lớn hơn, chuyển sang ONNX với FP16 quantization:

```bash
# Convert LightGBM to ONNX
pip install onnx onnxmltools
python -c "
import onnxmltools
from lightgbm import Booster
model = Booster(model_file='aim_model.txt')
onnx_model = onnxmltools.convert_lightgbm(model, 'feature_vector', [('float_input', FloatTensorType([None, 6]))])
onnxmltools.utils.calculate_estimated_size(onnx_model)  # ~50% smaller
"
```

### 7.3 Thread Pool Configuration

```python
# app/utils/thread_pool.py
from concurrent.futures import ThreadPoolExecutor
import asyncio
import functools

# Chỉ 2 threads là đủ — model inference không phải I/O bound
_inference_pool = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="inference"
)

async def run_inference_sync(fn, *args, **kwargs):
    """Run synchronous function in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _inference_pool,
        functools.partial(fn, *args, **kwargs)
    )
```

**Tại sao 2 threads:** LightGBM predict là CPU-bound. Nếu có 4 threads chạy cùng lúc trên 1 CPU core, context switching overhead sẽ làm chậm hơn. 2 threads = optimal cho single-core VPS.

---

## 8. Data Layer

### 8.1 SQLite Schema

```sql
-- API keys management
CREATE TABLE IF NOT EXISTS api_keys (
    key_id TEXT PRIMARY KEY,
    server_name TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    rate_limit INT NOT NULL DEFAULT 60,
    requests_today INT DEFAULT 0,
    total_requests INT DEFAULT 0,
    expires_at TEXT,
    enabled INT DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Rate limiting counters (sliding window buckets)
CREATE TABLE IF NOT EXISTS rate_counters (
    key_id TEXT NOT NULL,
    window_start INTEGER NOT NULL,  -- Unix timestamp, 10s granularity
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, window_start)
);

-- Request logs
CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT,
    endpoint TEXT,
    ip TEXT,
    response_time_ms REAL,
    risk_score REAL,
    status_code INT,
    timestamp TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_request_logs_key ON request_logs(key_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_ts ON request_logs(timestamp);

-- Training samples collected from servers
CREATE TABLE IF NOT EXISTS training_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,           -- aim | click | session
    features TEXT NOT NULL,           -- JSON array
    label REAL NOT NULL,              -- 0.0 = legit, 1.0 = cheat
    server_id TEXT,
    client_version TEXT,
    ping INT,
    label_source TEXT DEFAULT 'auto',  -- staff_review | whitebox | auto
    weight REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_training_samples_cat ON training_samples(category);

-- Training job tracking
CREATE TABLE IF NOT EXISTS training_jobs (
    job_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
    accuracy REAL,
    model_version TEXT,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT
);

-- Database version tracking for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
```

### 8.2 WAL Mode Configuration

```sql
PRAGMA journal_mode=WAL;       -- Write-Ahead Logging: concurrent reads
PRAGMA synchronous=NORMAL;     -- Balance between safety and speed
PRAGMA busy_timeout=5000;      -- Wait 5s before SQLITE_BUSY
PRAGMA cache_size=-4000;       -- 4MB page cache
PRAGMA temp_store=MEMORY;      -- Temporary tables in memory
PRAGMA mmap_size=268435456;    -- 256MB memory-mapped I/O
```

### 8.3 Daily Maintenance

```sql
-- Cleanup old rate counters (older than 24h)
DELETE FROM rate_counters WHERE window_start < unixepoch('now', '-1 day');

-- Cleanup old request logs (older than 30 days)
DELETE FROM request_logs WHERE timestamp < datetime('now', '-30 days');

-- Reset daily counters
UPDATE api_keys SET requests_today = 0;

-- Vacuum (weekly)
VACUUM;
```

### 8.4 Backup Strategy

```bash
#!/bin/bash
# /usr/local/bin/backup-vnac.sh — chạy daily via cron

BACKUP_DIR="/var/backups/vnac"
DB_PATH="/data/vnac.db"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# Backup using sqlite3 backup API (consistent even during writes)
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/vnac_$DATE.db'"

# Compress
gzip "$BACKUP_DIR/vnac_$DATE.db"

# Keep last 30 days
find "$BACKUP_DIR" -name "vnac_*.db.gz" -mtime +30 -delete

# Copy to remote (optional)
# rclone copy "$BACKUP_DIR" backup-s3:vnac-backups/
```

---

## 9. Deployment

### 9.1 Dockerfile

```dockerfile
# Dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Runtime stage ──
FROM python:3.12-slim

# Create non-root user
RUN useradd -m -u 1000 vnac && \
    mkdir -p /data /models && \
    chown vnac:vnac /data /models

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local /home/vnac/.local
ENV PATH=/home/vnac/.local/bin:$PATH

# Copy application
COPY app/ app/
COPY models/ /models/
COPY requirements.txt .

EXPOSE 8000

USER vnac

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/v1/health || exit 1

# Single worker — 1GB RAM optimization
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--limit-concurrency", "16", \
     "--limit-max-requests", "10000", \
     "--timeout-keep-alive", "30"]
```

### 9.2 Requirements.txt

```txt
# requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.9.0
pydantic-settings>=2.5.0
aiosqlite>=0.20.0
numpy>=1.26.0
scikit-learn>=1.5.0
lightgbm>=4.5.0
psutil>=6.0.0
python-multipart>=0.0.12
```

**Không bao gồm:** pandas, scipy, matplotlib, jupyter — tiết kiệm ~200MB disk + RAM.

### 9.3 systemd Service

```ini
# /etc/systemd/system/vnac-ml.service
[Unit]
Description=VNAC ML Inference Server
After=network.target

[Service]
Type=simple
User=vnac
WorkingDirectory=/app

# Environment
Environment=ML_ADMIN_KEY=sk-admin-prod-change-me
Environment=ML_DATA_DIR=/data
Environment=ML_MODEL_DIR=/models
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

# Memory limit — QUAN TRỌNG cho 1GB VPS
MemoryMax=900M
MemoryHigh=800M

# ExecStart
ExecStart=/home/vnac/.local/bin/uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1 \
    --limit-concurrency 16 \
    --limit-max-requests 10000 \
    --timeout-keep-alive 30

# Restart
Restart=always
RestartSec=5

# OOM
OOMScoreAdjust=500

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/data

[Install]
WantedBy=multi-user.target
```

```bash
# Deploy service
sudo cp vnac-ml.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vnac-ml
sudo systemctl start vnac-ml
sudo systemctl status vnac-ml

# Watch logs
sudo journalctl -u vnac-ml -f

# Check memory
sudo systemctl show vnac-ml -p MemoryCurrent
```

### 9.4 Nginx Reverse Proxy

```nginx
# /etc/nginx/sites-available/vnac-ml
upstream vnac_backend {
    server 127.0.0.1:8000;
    keepalive 16;
}

server {
    listen 80;
    server_name api.vnac.dev;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.vnac.dev;

    # SSL — Let's Encrypt
    ssl_certificate /etc/letsencrypt/live/api.vnac.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.vnac.dev/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";

    # Request size limit
    client_max_body_size 100k;

    # Rate limiting via nginx
    limit_req_zone $binary_remote_addr zone=global:10m rate=100r/s;
    limit_req zone=global burst=200 nodelay;

    location / {
        proxy_pass http://vnac_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;
        proxy_send_timeout 5s;

        # Buffering
        proxy_buffering off;
        proxy_request_buffering off;
    }

    location /v1/health {
        # No rate limit for health checks
        access_log off;
        proxy_pass http://vnac_backend;
        proxy_http_version 1.1;
    }

    access_log /var/log/nginx/vnac-ml.access.log;
    error_log /var/log/nginx/vnac-ml.error.log;
}
```

```bash
# Enable site
sudo ln -sf /etc/nginx/sites-available/vnac-ml /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Let's Encrypt (first time)
sudo certbot --nginx -d api.vnac.dev

# Auto-renewal (certbot adds systemd timer automatically)
sudo systemctl status certbot.timer
```

### 9.5 Logrotate

```ini
# /etc/logrotate.d/vnac-ml
/var/log/nginx/vnac-ml.*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 `cat /var/run/nginx.pid`
    endscript
}

/data/request_logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    copytruncate
    missingok
}
```

### 9.6 Docker Compose (Development Only)

```yaml
# docker-compose.yml — KHÔNG dùng trong production (thiếu systemd memory limit)
version: "3.8"

services:
  vnac-ml:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./models:/models:ro
      - vnac_data:/data
    environment:
      - ML_ADMIN_KEY=sk-dev-key
      - ML_DATA_DIR=/data
      - ML_MODEL_DIR=/models
      - PYTHONUNBUFFERED=1
    deploy:
      resources:
        limits:
          memory: 900M
        reservations:
          memory: 200M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  vnac_data:
```

### 9.7 System Tuning

```bash
# /etc/sysctl.d/99-vnac.conf
# Network tuning for API server
net.core.somaxconn = 1024
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_tw_reuse = 1

# Memory
vm.swappiness = 10
vm.vfs_cache_pressure = 50
```

```bash
# Apply
sudo sysctl --system
```

---

## 10. Full Code Files

### 10.1 `app/config.py`

```python
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Server
    APP_NAME: str = "VNAC ML Server"
    DEBUG: bool = False

    # Paths
    DATA_DIR: str = "/data"
    MODEL_DIR: str = "/models"
    DB_PATH: str = ""  # Auto-set from DATA_DIR

    # Auth
    ADMIN_KEY: str = "sk-admin-change-me"

    # Rate limiting
    GLOBAL_RATE_LIMIT: int = 5000

    # Model
    MODEL_TTL: int = 300  # Seconds before unloading idle model
    MODEL_RELOAD_INTERVAL: int = 30  # Seconds between hot-reload checks

    # Inference
    MAX_CONCURRENT_INFERENCE: int = 16
    INFERENCE_TIMEOUT: float = 5.0
    THREAD_POOL_SIZE: int = 2

    # GC
    GC_INTERVAL: int = 100  # Force gc every N requests

    # Uvicorn
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    MAX_REQUESTS: int = 10000

    def model_post_init(self, __context):
        if not self.DB_PATH:
            self.DB_PATH = f"{self.DATA_DIR}/vnac.db"

    class Config:
        env_file = ".env"
        env_prefix = "ML_"
```

### 10.2 `app/main.py`

```python
"""
VNAC — ML Inference Server (FastAPI)
Production-ready cloud inference server for Minecraft anticheat ML system.

RAM: 1GB VPS optimized — single uvicorn worker, lazy model loading, TTL unload.
"""
import time
import gc
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.db.connection import DatabaseManager
from app.models.registry import ModelRegistry
from app.services.background import BackgroundTasks
from app.api.schemas import (
    AimRequest, ClickRequest, SessionRequest, PredictAllRequest,
    TrainingSampleRequest, TrainTriggerRequest, KeyCreateRequest,
    AimResponse, PredictResponse, CompositeResponse,
    HealthResponse, KeyCreateResponse
)
from app.api.predict import router as predict_router
from app.api.training import router as training_router
from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.utils.logger import setup_logging

settings = Settings()
startup_time = time.time()

# ── Logging setup ──
setup_logging(settings.DEBUG)
logger = logging.getLogger(__name__)

# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.APP_NAME}...")
    db = DatabaseManager(settings.DB_PATH)
    await db.initialize()
    app.state.db = db

    registry = ModelRegistry(model_dir=settings.MODEL_DIR, ttl=settings.MODEL_TTL)
    app.state.registry = registry

    bg = BackgroundTasks(registry)
    await bg.start()
    app.state.bg = bg

    # Global state
    app.state.startup_time = startup_time
    app.state.request_counter = 0
    app.state.settings = settings

    logger.info(f"{settings.APP_NAME} started")
    yield

    # Shutdown
    logger.info("Shutting down...")
    await bg.stop()
    await registry.unload_all()
    await db.close()
    logger.info("Shutdown complete.")

# ── App creation ──
app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ── Middleware ──
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"] if settings.DEBUG else ["api.vnac.dev", "localhost"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["https://api.vnac.dev"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=3600,
)

# ── Custom Middleware ──

inference_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_INFERENCE)

@app.middleware("http")
async def concurrency_middleware(request: Request, call_next):
    """Limit concurrent predictions."""
    if request.url.path.startswith("/v1/predict/"):
        async with inference_semaphore:
            return await call_next(request)
    return await call_next(request)

@app.middleware("http")
async def gc_collect_middleware(request: Request, call_next):
    """Periodic garbage collection."""
    response = await call_next(request)
    app.state.request_counter += 1
    if app.state.request_counter >= settings.GC_INTERVAL:
        app.state.request_counter = 0
        gc.collect()
    return response

# ── Include routers ──
app.include_router(predict_router)
app.include_router(training_router)
app.include_router(admin_router)
app.include_router(health_router)
```

### 10.3 `app/models/aim_model.py`

```python
"""
AimModel — LightGBM Gradient Boosting für rotation analysis.
Detects: AimAssist, KillAura, SmoothAim.
Input: 6 features (yawJerkStd, pitchJerkStd, aimSmoothness, rotationEntropy, gcdError, snapFreq)
Output: risk [0, 0.985]
"""
import json
import logging
import numpy as np
from pathlib import Path
from typing import Optional

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    logging.getLogger(__name__).warning("lightgbm not installed, using sklearn fallback")

from sklearn.ensemble import GradientBoostingClassifier as SklearnGBDT
import pickle

from app.models.base import BaseModel

logger = logging.getLogger(__name__)

class AimModel(BaseModel):
    """LightGBM model for aim/rotation analysis."""

    def __init__(self, path: Optional[str] = None):
        self._model = None
        self._version = "untrained"
        self._feature_importance: Optional[list[float]] = None
        super().__init__(path)

    def load(self, path: str):
        path = Path(path)
        if not path.exists():
            logger.warning(f"Aim model file not found: {path}")
            self._is_loaded = False
            return

        ext = path.suffix.lower()
        try:
            if ext == ".txt":
                # LightGBM text format
                if HAS_LGB:
                    self._model = lgb.Booster(model_file=str(path))
                else:
                    # Fallback to sklearn pickle
                    self._model = pickle.loads(path.read_bytes())
                    logger.info("Loaded sklearn GBDT model (lightgbm not available)")
            elif ext == ".model":
                # Legacy pickle format
                with open(path, "rb") as f:
                    self._model = pickle.load(f)
            else:
                raise ValueError(f"Unknown model format: {ext}")

            # Extract version from filename
            self._version = path.stem
            self._is_loaded = True

            # Try to get feature importance
            try:
                if HAS_LGB and isinstance(self._model, lgb.Booster):
                    self._feature_importance = list(
                        self._model.feature_importance(importance_type='gain')
                    )
                elif isinstance(self._model, SklearnGBDT):
                    # sklearn GBDT
                    self._feature_importance = list(
                        self._model.feature_importances_
                    )
            except Exception:
                pass

            logger.info(f"AimModel loaded: v{self._version} ({path.stat().st_size / 1024:.1f}KB)")

        except Exception as e:
            logger.error(f"Failed to load aim model {path}: {e}")
            self._is_loaded = False
            raise

    def predict(self, features: list[float]) -> float:
        """Predict risk score [0, 0.985]."""
        if not self._is_loaded or self._model is None:
            return 0.5  # Neutral when no model

        arr = np.array([features], dtype=np.float32)

        try:
            if HAS_LGB and isinstance(self._model, lgb.Booster):
                # LightGBM raw output (log-odds)
                raw = self._model.predict(arr)[0]
                risk = 1.0 / (1.0 + np.exp(-raw))  # Sigmoid
            elif isinstance(self._model, SklearnGBDT):
                # sklearn predict_proba returns [P(legit), P(cheat)]
                proba = self._model.predict_proba(arr)[0]
                risk = float(proba[1]) if len(proba) > 1 else float(proba[0])
            else:
                risk = 0.5

            # Cap at 0.985 — model never says 100% certain
            return min(float(risk), 0.985)

        except Exception as e:
            logger.error(f"AimModel predict error: {e}", exc_info=True)
            return 0.5

    def get_confidence(self, features: list[float]) -> float:
        """
        Confidence based on feature importance-weighted distance from decision boundary.
        Returns 0.0 to 1.0.
        """
        if not self._is_loaded:
            return 0.1

        risk = self.predict(features)
        # Distance from 0.5 boundary => confidence
        distance = abs(risk - 0.5) * 2  # 0 at 0.5, 1 at 0.0 or 1.0
        return min(float(distance * 0.95), 0.95)  # Never > 0.95

    @property
    def loaded(self) -> bool:
        return self._is_loaded
```

### 10.4 `app/models/click_model.py`

```python
"""
ClickModel — Logistic Regression with online learning.
Detects: AutoClicker, Butterfly click, Script click.
Input: 5 features (cooldownAccuracy, missRatio, hitMissRatio, criticalRatio, perfectStreak)
Output: risk [0, 0.985]
Training: SGD-based online update.
"""
import json
import math
import logging
from pathlib import Path
from typing import Optional

from app.models.base import BaseModel

logger = logging.getLogger(__name__)

class ClickModel(BaseModel):
    """Logistic Regression model for click pattern analysis."""

    def __init__(self, path: Optional[str] = None, n_features: int = 5):
        self.n_features = n_features
        self.weights: list[float] = [0.0] * n_features
        self.bias: float = 0.0
        self.samples: int = 0
        self.lr: float = 0.01
        super().__init__(path)

    def load(self, path: str):
        path = Path(path)
        if not path.exists():
            logger.warning(f"Click model file not found: {path}")
            self._is_loaded = False
            return

        try:
            data = json.loads(path.read_text())
            self.weights = data.get("weights", [0.0] * self.n_features)
            self.bias = data.get("bias", 0.0)
            self.samples = data.get("samples", 0)
            self.lr = data.get("lr", 0.01)
            self._version = path.stem
            self._is_loaded = True
            logger.info(f"ClickModel loaded: v{self._version} ({self.samples} samples)")

            # Ensure correct length
            while len(self.weights) < self.n_features:
                self.weights.append(0.0)
            self.weights = self.weights[:self.n_features]

        except Exception as e:
            logger.error(f"Failed to load click model {path}: {e}")
            self._is_loaded = False
            raise

    def predict(self, features: list[float]) -> float:
        """Logistic regression: sigmoid(w·x + b)."""
        if len(features) != self.n_features:
            logger.warning(f"ClickModel expected {self.n_features} features, got {len(features)}")
            features = features[:self.n_features] if len(features) >= self.n_features else \
                       features + [0.0] * (self.n_features - len(features))

        z = self.bias + sum(w * f for w, f in zip(self.weights, features))
        z = max(-100, min(100, z))  # Prevent overflow
        risk = 1.0 / (1.0 + math.exp(-z))
        return min(risk, 0.985)

    def train(self, features: list[float], label: float) -> float:
        """
        Online SGD training.
        label: 0.0 (legit) or 1.0 (cheat)
        Returns: loss before update
        """
        if len(features) != self.n_features:
            raise ValueError(f"Expected {self.n_features} features, got {len(features)}")

        pred = self.predict(features)
        err = pred - label
        loss = err * err  # MSE

        for i in range(self.n_features):
            self.weights[i] -= self.lr * err * features[i]
        self.bias -= self.lr * err

        self.samples += 1
        return loss

    def unload(self):
        """Save before unloading."""
        self.save()
        super().unload()

    def save(self, path: Optional[str] = None):
        """Save model to JSON."""
        if path is None:
            path = Path("/models/click_current.json")
        else:
            path = Path(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "weights": self.weights,
            "bias": self.bias,
            "samples": self.samples,
            "lr": self.lr,
            "version": self._version,
        }
        path.write_text(json.dumps(data, indent=2))
        logger.info(f"ClickModel saved: {path} ({self.samples} samples)")

    def get_confidence(self, features: list[float]) -> float:
        if self.samples < 10:
            return 0.3  # Not enough training data
        risk = self.predict(features)
        distance = abs(risk - 0.5) * 2
        return min(float(distance * 0.9), 0.9)
```

### 10.5 `app/models/session_model.py`

```python
"""
SessionModel — Weighted ensemble for behavioral profiling.
Detects: GhostClient, legit aura, baritone.
Input: 8 features (window 10 minutes)
Output: risk [0, 0.85] — NEVER exceeds 0.85 (Rule R7: GHOST_PROFILE only ALERT)
"""
import json
import math
import logging
from pathlib import Path
from typing import Optional

from app.models.base import BaseModel

logger = logging.getLogger(__name__)

# Default weights — calibrated from training data
DEFAULT_WEIGHTS = [0.15, 0.10, 0.05, 0.10, 0.10, 0.20, 0.20, 0.10]
FEATURE_NAMES = [
    "avgHitDistance", "hitDistanceStd", "reactionTimeMs",
    "missPercentage", "aimLockDuration", "targetSwitchSpeed",
    "noBadTickRatio", "movementComplexity"
]

class SessionModel(BaseModel):
    """Weighted ensemble model for session-level behavioral analysis."""

    def __init__(self, path: Optional[str] = None, n_features: int = 8):
        self.n_features = n_features
        self.weights: list[float] = list(DEFAULT_WEIGHTS)
        self.bias: float = 0.0
        self.scale: float = 4.0  # Sigmoid sharpness
        self.threshold: float = 0.5  # Sigmoid midpoint shift
        super().__init__(path)

    def load(self, path: str):
        path = Path(path)
        if not path.exists():
            logger.warning(f"Session model file not found: {path}")
            self._is_loaded = False
            return

        try:
            data = json.loads(path.read_text())
            self.weights = data.get("weights", list(DEFAULT_WEIGHTS))
            self.bias = data.get("bias", 0.0)
            self.scale = data.get("scale", 4.0)
            self.threshold = data.get("threshold", 0.5)
            self._version = path.stem
            self._is_loaded = True
            logger.info(f"SessionModel loaded: v{self._version}")

            # Ensure correct length
            while len(self.weights) < self.n_features:
                self.weights.append(0.0)
            self.weights = self.weights[:self.n_features]

        except Exception as e:
            logger.error(f"Failed to load session model {path}: {e}")
            self._is_loaded = False
            raise

    def predict(self, features: list[float]) -> float:
        """
        Weighted sum + sigmoid.
        Output capped at 0.85 (Rule R7: GHOST_PROFILE only ALERT).
        """
        if len(features) != self.n_features:
            logger.warning(f"SessionModel expected {self.n_features} features, got {len(features)}")
            features = features[:self.n_features] if len(features) >= self.n_features else \
                       features + [0.0] * (self.n_features - len(features))

        # Weighted sum
        raw = self.bias + sum(w * f for w, f in zip(self.weights, features))

        # Sigmoid with scale and threshold
        # f(x) = 1 / (1 + exp(-scale * (raw - threshold)))
        z = self.scale * (raw - self.threshold)
        z = max(-100, min(100, z))
        risk = 1.0 / (1.0 + math.exp(-z))

        # Rule R7: GHOST_PROFILE — NEVER auto-ban, cap at 0.85
        return min(risk, 0.85)

    def get_confidence(self, features: list[float]) -> float:
        return 0.7 if self._is_loaded else 0.2
```

### 10.6 `app/services/fusion.py`

```python
"""
FusionEngine — Python port of FusionEngine.java.
Combines whitebox certainty, blackbox ML risk, session history, and runtime context
to decide the appropriate action.

Rules: R1-R7 (see docs/plan/09-fusion-policy.md)
"""
import time
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Category decay rates (session risk) ──
CATEGORY_DECAY = {
    "movement": 0.001,
    "packet": 0.001,
    "combat_geom": 0.002,
    "scaffold": 0.002,
    "breaking": 0.002,
    "combat_aim": 0.003,
    "click": 0.003,
    "reach": 0.002,
    "killaura": 0.003,
    "aimassist": 0.003,
    "ghost_profile": 0.001,
    "botting": 0.001,
}

# ── Session risk management ──
_session_risks: dict[str, dict] = {}
MAX_SERVERS = 10000  # Prevent memory leak

def _get_server_state(server_key: str) -> dict:
    """Get or create session risk state for a server."""
    now = time.time()
    if server_key not in _session_risks:
        if len(_session_risks) >= MAX_SERVERS:
            # Evict oldest
            oldest = min(_session_risks.keys(), key=lambda k: _session_risks[k]["last_update"])
            del _session_risks[oldest]
        _session_risks[server_key] = {
            "risk": 0.0,
            "last_update": now,
            "flags": []  # Recent flags for audit
        }
    return _session_risks[server_key]


def map_vl_to_certainty(vl: float) -> float:
    """Continuous sigmoid certainty from VL (violation level)."""
    return max(0.10, 0.98 * (1.0 - math.exp(-0.08 * vl)))


def bayesian_posterior(wb: float, bb: float) -> float:
    """
    Bayesian fusion of whitebox and blackbox probabilities.
    P(cheat | wb, bb) = P(wb)P(bb) / [P(wb)P(bb) + (1-P(wb))(1-P(bb))]
    """
    num = wb * bb
    denom = num + (1.0 - wb) * (1.0 - bb)
    return num / denom if denom > 0 else 0.0


def compute_runtime_penalty(ping: float, tps: float, jitter: float = 0.0) -> float:
    """
    Compute runtime penalty factor for blackbox risk.

    Returns penalty [0, 0.6] — higher = more penalty = lower effective risk.
    """
    penalty = 0.0

    # Ping penalty
    if ping > 300:
        penalty = 0.45
    elif ping > 200:
        penalty = 0.25
    elif ping > 100:
        penalty = 0.1

    # TPS penalty
    if tps < 18:
        penalty += 0.25
    elif tps < 19.5:
        penalty += 0.1

    # Jitter penalty
    if jitter > 50:
        penalty += 0.15

    return min(penalty, 0.60)


def fusion_evaluate(
    whitebox_certainty: float,
    category: str,
    blackbox_risk: float = 0.0,
    blackbox_category: str = "",
    ping: float = 0.0,
    tps: float = 20.0,
    jitter: float = 0.0,
    server_key: str = "default",
    session_risk_override: Optional[float] = None,
) -> dict:
    """
    Main fusion evaluation — 7 rules applied in priority order.

    Returns:
        dict with keys: action, risk, session_risk, rule
    """
    now = time.time()
    decay = CATEGORY_DECAY.get(category, 0.002)

    # ── Session risk ──
    sr = _get_server_state(server_key)
    dt = now - sr["last_update"]
    sr["risk"] *= math.exp(-decay * dt)
    sr["last_update"] = now

    if session_risk_override is not None:
        sr["risk"] = session_risk_override

    session_risk = sr["risk"]

    # ── R7: No-auto-enforce domains ──
    if category in ("ghost_profile", "botting"):
        return {
            "action": "alert",
            "risk": blackbox_risk,
            "session_risk": session_risk,
            "rule": "R7"
        }

    # ── R6: Movement/Packet immutable ──
    if category in ("movement", "packet") and whitebox_certainty >= 0.95:
        sr["risk"] += 50
        return {
            "action": "enforce",
            "risk": whitebox_certainty,
            "session_risk": sr["risk"],
            "rule": "R6"
        }

    # ── R1: Deterministic truth ──
    if whitebox_certainty >= 0.98:
        sr["risk"] += 50
        return {
            "action": "enforce",
            "risk": whitebox_certainty,
            "session_risk": sr["risk"],
            "rule": "R1"
        }

    # ── R5: Runtime penalty ──
    penalty = compute_runtime_penalty(ping, tps, jitter)
    effective_bb = blackbox_risk * (1.0 - penalty)

    # ── Bayesian posterior ──
    if category in ("movement", "packet"):
        posterior = whitebox_certainty
    else:
        posterior = bayesian_posterior(whitebox_certainty, effective_bb)

    # ── R2: ML risk cao + whitebox thấp → alert only ──
    if effective_bb >= 0.85 and whitebox_certainty < 0.5:
        sr["risk"] += 15
        return {
            "action": "alert",
            "risk": effective_bb,
            "session_risk": sr["risk"],
            "rule": "R2"
        }

    # ── R3: Hybrid escalation ──
    if 0.5 <= whitebox_certainty < 0.95 and effective_bb > 0.70:
        sr["risk"] += 20
        if sr["risk"] >= 150:
            action = "soft_mitigate"
        else:
            action = "assist"
        return {
            "action": action,
            "risk": posterior,
            "session_risk": sr["risk"],
            "rule": f"R3-{action}"
        }

    # ── R4: Accumulated session risk ──
    if posterior >= 0.4:
        sr["risk"] += 10
        if sr["risk"] >= 300:
            return {
                "action": "enforce",
                "risk": posterior,
                "session_risk": sr["risk"],
                "rule": "R4-enforce"
            }
        elif sr["risk"] >= 150:
            return {
                "action": "soft_mitigate",
                "risk": posterior,
                "session_risk": sr["risk"],
                "rule": "R4-mitigate"
            }
        elif sr["risk"] >= 50:
            return {
                "action": "alert",
                "risk": posterior,
                "session_risk": sr["risk"],
                "rule": "R4-alert"
            }

    # ── Default: observe ──
    return {
        "action": "observe",
        "risk": posterior,
        "session_risk": sr["risk"],
        "rule": "default"
    }


def reset_session(server_key: str):
    """Reset session risk for a server (e.g., on player quit)."""
    if server_key in _session_risks:
        del _session_risks[server_key]


def cleanup_sessions(max_age: float = 3600):
    """Remove sessions older than max_age seconds."""
    now = time.time()
    expired = [
        k for k, v in _session_risks.items()
        if now - v["last_update"] > max_age
    ]
    for k in expired:
        del _session_risks[k]
    if expired:
        logger.debug(f"Cleaned up {len(expired)} stale sessions")
```

### 10.7 `app/api/schemas.py`

```python
"""Pydantic models for all API request/response schemas."""
from pydantic import BaseModel, Field
from typing import Optional


# ── Predict Requests ──

class AimRequest(BaseModel):
    features: list[float] = Field(..., min_length=6, max_length=6)
    ping: int = Field(default=0, ge=0, le=1000)
    tps: float = Field(default=20.0, ge=0, le=20.0)
    jitter: float = Field(default=0.0, ge=0, le=500)


class ClickRequest(BaseModel):
    features: list[float] = Field(..., min_length=5, max_length=5)
    ping: int = Field(default=0, ge=0, le=1000)
    tps: float = Field(default=20.0, ge=0, le=20.0)
    jitter: float = Field(default=0.0, ge=0, le=500)


class SessionRequest(BaseModel):
    features: list[float] = Field(..., min_length=8, max_length=8)
    player_id: str = Field(default="", max_length=64)
    session_duration_seconds: int = Field(default=0, ge=0)
    ping: int = Field(default=0, ge=0, le=1000)
    tps: float = Field(default=20.0, ge=0, le=20.0)


class PredictAllRequest(BaseModel):
    aim_features: Optional[list[float]] = Field(None, min_length=6, max_length=6)
    click_features: Optional[list[float]] = Field(None, min_length=5, max_length=5)
    session_features: Optional[list[float]] = Field(None, min_length=8, max_length=8)
    whitebox_context: dict = Field(default_factory=dict)
    runtime_context: dict = Field(default_factory=dict)
    server_id: str = Field(default="default", max_length=64)
    client_version: Optional[str] = Field(None, max_length=16)


# ── Predict Responses ──

class PredictResponse(BaseModel):
    risk: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    model_version: str


class CompositeResponse(BaseModel):
    action: str
    risk: float = Field(..., ge=0, le=1)
    session_risk: float
    rule: str
    confidence: float = Field(..., ge=0, le=1)
    model_versions: dict
    latency_ms: float


# ── Training ──

class TrainingSampleRequest(BaseModel):
    category: str = Field(..., pattern="^(aim|click|session)$")
    features: list[float]
    label: float = Field(..., ge=0.0, le=1.0)
    server_id: Optional[str] = Field(None, max_length=64)
    client_version: Optional[str] = Field(None, max_length=16)
    ping: int = Field(default=0, ge=0, le=1000)
    label_source: Optional[str] = Field(None, max_length=32)


class TrainTriggerRequest(BaseModel):
    model: Optional[str] = Field(None, pattern="^(aim|click|session|all)$")
    hyperparams: dict = Field(default_factory=dict)


# ── Admin ──

class KeyCreateRequest(BaseModel):
    server_name: str = Field(..., min_length=1, max_length=64)
    tier: str = Field(default="free", pattern="^(free|basic|pro|enterprise)$")
    duration_days: int = Field(default=365, ge=1, le=3650)


class KeyCreateResponse(BaseModel):
    key_id: str
    server_name: str
    tier: str
    expires_at: str


class HealthResponse(BaseModel):
    status: str
    uptime: int
    models_loaded: list
    memory_mb: float
    database_size_mb: float
    requests_total: int
    requests_today: int
    timestamp: str
```

### 10.8 `app/utils/logger.py`

```python
"""Structured logging setup."""
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production — structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in getattr(record, "extra_fields", {}).items():
            log_entry[key] = value

        return json.dumps(log_entry, default=str)


def setup_logging(debug: bool = False):
    """Configure logging for the application."""
    root = logging.getLogger()

    # Remove existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)

    if debug:
        # Human-readable format for local dev
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        root.setLevel(logging.DEBUG)
    else:
        # JSON format for production
        formatter = JSONFormatter()
        root.setLevel(logging.INFO)

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
```

---

## 11. Testing

### 11.1 Unit Test Structure

```
tests/
├── conftest.py            # Fixtures: app, db, registry
├── test_predict.py        # Test predict endpoints
├── test_fusion.py         # Test FusionEngine rules
├── test_rate_limiter.py   # Test rate limiting
├── test_registry.py       # Test model registry
├── test_models.py         # Test individual models
└── test_health.py         # Test health endpoint
```

### 11.2 Load Testing

```python
# tests/load_test.py
"""
Load test using locust or simple asyncio benchmark.
Run: python tests/load_test.py
"""
import asyncio
import aiohttp
import time
import statistics

API_URL = "http://localhost:8000"
API_KEY = "sk-test-key"

async def benchmark_predict(session, semaphore, results):
    async with semaphore:
        start = time.monotonic()
        try:
            async with session.post(
                f"{API_URL}/v1/predict/aim",
                json={
                    "features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67],
                    "ping": 45,
                    "tps": 20.0,
                    "jitter": 5.2
                },
                headers={"Authorization": f"Bearer {API_KEY}"}
            ) as resp:
                elapsed = (time.monotonic() - start) * 1000
                results.append(elapsed)
                return resp.status, elapsed
        except Exception as e:
            results.append(float('inf'))
            return 0, float('inf')

async def main():
    concurrency = 16
    total_requests = 200
    semaphore = asyncio.Semaphore(concurrency)
    results = []

    async with aiohttp.ClientSession() as session:
        tasks = [
            benchmark_predict(session, semaphore, results)
            for _ in range(total_requests)
        ]
        await asyncio.gather(*tasks)

    succeed = [r for r in results if r != float('inf')]
    if succeed:
        print(f"Total: {len(results)}")
        print(f"Success: {len(succeed)}")
        print(f"Mean: {statistics.mean(succeed):.1f}ms")
        print(f"Median: {statistics.median(succeed):.1f}ms")
        print(f"P95: {sorted(succeed)[int(len(succeed)*0.95)]:.1f}ms")
        print(f"P99: {sorted(succeed)[int(len(succeed)*0.99)]:.1f}ms")
        print(f"Max: {max(succeed):.1f}ms")

asyncio.run(main())
```

### 11.3 CURL Test Commands

```bash
# Health check
curl http://localhost:8000/v1/health

# Predict aim
curl -X POST http://localhost:8000/v1/predict/aim \
  -H "Authorization: Bearer sk-test-key" \
  -H "Content-Type: application/json" \
  -d '{"features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67], "ping": 45, "tps": 20.0, "jitter": 5.2}'

# Predict all (composite)
curl -X POST http://localhost:8000/v1/predict/all \
  -H "Authorization: Bearer sk-test-key" \
  -H "Content-Type: application/json" \
  -d '{
    "aim_features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67],
    "click_features": [0.88, 0.12, 0.34, 0.56, 0.03],
    "session_features": [0.45, 0.23, 0.67, 0.12, 0.89, 0.34, 0.56, 0.78],
    "whitebox_context": {"certainty": 0.65, "category": "combat_aim", "vl": 15},
    "runtime_context": {"ping": 45, "tps": 20.0, "jitter": 5.2, "player_id": "test"},
    "server_id": "test-server"
  }'

# Collect training sample
curl -X POST http://localhost:8000/v1/training/sample \
  -H "Authorization: Bearer sk-test-key" \
  -H "Content-Type: application/json" \
  -d '{"category": "aim", "features": [0.32, 0.18, 0.91, 0.45, 0.02, 0.67], "label": 1.0, "server_id": "test", "client_version": "1.20.4", "ping": 45}'

# Auth verify
curl -X POST http://localhost:8000/v1/auth/verify \
  -H "Authorization: Bearer sk-test-key"
```

### 11.4 Performance Targets

| Metric | Target | Critical |
|---|---|---|
| P50 latency | < 5ms | < 10ms |
| P95 latency | < 15ms | < 30ms |
| P99 latency | < 50ms | < 100ms |
| Max throughput | 100 req/s | 50 req/s |
| Memory (idle) | < 100MB | < 200MB |
| Memory (peak) | < 300MB | < 600MB |
| Availability | 99.9% | 99.5% |

---

## Summary

This design document provides a complete blueprint for building a production-ready FastAPI inference server for the MLSHybridAC Minecraft anticheat system. Key design decisions:

1. **Modular package structure** (`app/`) thay vì monolithic `ml_server.py` — dễ maintain, test, deploy.
2. **Lazy loading + TTL unload** — models chỉ consume RAM khi có request, tự giải phóng sau 5 phút không dùng.
3. **Single uvicorn worker** — critical cho 1GB RAM (mỗi worker = model copy).
4. **Semaphore (max 16 concurrent)** — prevent thundering herd trên CPU-bound inference.
5. **gc.collect() sau mỗi 100 requests** + `max_requests=10000` — chống memory leak.
6. **Sliding window rate limiting** — per-key + global, với SQLite counters.
7. **Versioned models với symlinks** — hot-reload không downtime.
8. **FusionEngine port** — 7 rules (R1-R7) từ Java sang Python, giữ nguyên logic.
9. **Graceful degradation** — model fail → return 0.5 (neutral), không crash.
10. **systemd MemoryMax=900M** — hardware limit enforcement.
