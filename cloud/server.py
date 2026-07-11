"""
MLSHybridAC — Cloud Inference Server (FastAPI + LightGBM)
=========================================================
1GB RAM VPS optimized. Single worker, lazy-loaded models, async endpoints.
"""

from __future__ import annotations

import gc
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import numpy as np
import psutil
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from cloud.config import config
from cloud.database import Database
from cloud.auth import AuthManager
from cloud.model import ModelRegistry
from cloud.schemas import *

# ── Logging setup ────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vnac.server")

# ── Global state ─────────────────────────────────────────────────────────
db: Database | None = None
auth: AuthManager | None = None
registry: ModelRegistry | None = None
start_time: float = time.time()
total_predictions: int = 0
prediction_times: list[float] = []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup + shutdown."""
    global db, auth, registry, start_time

    # Startup
    logger.info("VNAC ML Server starting (1GB RAM mode)")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.model_dir.mkdir(parents=True, exist_ok=True)

    db = Database(config.db_path)
    db.connect()

    auth = AuthManager(db)
    registry = ModelRegistry(config.model_dir)

    logger.info("Server ready — workers=%d, max_concurrency=%d, admin_key=%s",
                config.workers, config.max_concurrency,
                "SET" if config.admin_key else "NOT SET (WARNING)")

    yield  # Server runs here

    # Shutdown
    logger.info("Shutting down...")
    if db:
        db.close()


# ── FastAPI app ──────────────────────────────────────────────────────────
app = FastAPI(
    title="VNAC ML Inference Server",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,         # Disable docs in production
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["X-API-Key", "Content-Type"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


# ── Middleware ───────────── ──────────────────────────────────────────────

async def api_key_auth(request: Request) -> None:
    """Verify API key from header."""
    if request.url.path.startswith("/v1/admin"):
        admin_key = request.headers.get("X-Admin-Key", "")
        if not auth or not auth.verify_admin(admin_key):
            raise HTTPException(status_code=401, detail="Invalid admin key")
        return
    if request.url.path in ("/v1/health", "/v1/metrics"):
        return
    raw_key = request.headers.get("X-API-Key", "")
    if not raw_key or not auth:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    key_info = auth.verify_key(raw_key)
    if not key_info:
        raise HTTPException(status_code=401, detail="Invalid API key")
    # Rate limit
    allowed, remaining, retry_after = auth.check_rate_limit(key_info.id, key_info.tier)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )
    request.state.api_key = key_info


async def global_rate_limit(request: Request) -> None:
    """Global rate limit middleware."""
    if request.url.path in ("/v1/health", "/v1/metrics"):
        return
    if auth:
        allowed, retry_after = auth.check_global_rate_limit()
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Global rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )


app.middleware("http")(lambda r, call: _middleware_wrapper(r, call))

async def _middleware_wrapper(request: Request, call_next):
    start = time.time()
    try:
        await api_key_auth(request)
        await global_rate_limit(request)
    except HTTPException:
        raise
    response = await call_next(request)
    elapsed_ms = (time.time() - start) * 1000
    response.headers["X-Processing-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


# ── Helper ───────────────────────────────────────────────────────────────

def _get_context(request: Request) -> tuple[float, float, int]:
    """Extract runtime context from request."""
    try:
        body = request._json or {}
    except Exception:
        body = {}
    return body.get("tps", 20.0), 0.0, body.get("ping", 0)


def _cap_risk(risk: float, max_risk: float = config.max_risk_cap) -> float:
    """Cap risk to maximum allowed value (FP prevention)."""
    return min(risk, max_risk)


def _log_prediction(model_name: str, risk: float, latency_ms: int, status: str = "ok"):
    """Log prediction to database (fire-and-forget)."""
    global total_predictions
    total_predictions += 1
    if db:
        try:
            db.execute(
                "INSERT INTO prediction_log (model_name, risk, latency_ms, status) VALUES (?, ?, ?, ?)",
                (model_name, risk, latency_ms, status),
            )
        except Exception:
            pass


# ── Endpoints: Predict ───────────────────────────────────────────────────

@app.post("/v1/predict/aim", response_model=PredictionResponse)
async def predict_aim(req: AimPredictRequest, request: Request):
    t0 = time.time()
    try:
        if not registry:
            raise HTTPException(503, "Server not ready")
        features = np.array(req.features, dtype=np.float32)
        risk, confidence = registry.predict_with_uncertainty("aim", features)
        version = registry.get_version("aim")
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("aim", risk, elapsed_ms)
        return PredictionResponse(
            risk=_cap_risk(risk),
            confidence=round(confidence, 4),
            model_version=version,
            server_timestamp=int(t0),
        )
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("aim", 0.0, elapsed_ms, "error")
        logger.error("Aim predict error: %s", e)
        raise HTTPException(500, detail="Prediction failed")


@app.post("/v1/predict/click", response_model=PredictionResponse)
async def predict_click(req: ClickPredictRequest, request: Request):
    t0 = time.time()
    try:
        if not registry:
            raise HTTPException(503, "Server not ready")
        features = np.array(req.features, dtype=np.float32)
        risk = registry.predict("click", features)
        version = registry.get_version("click")
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("click", risk, elapsed_ms)
        return PredictionResponse(
            risk=_cap_risk(risk),
            model_version=version,
            server_timestamp=int(t0),
        )
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("click", 0.0, elapsed_ms, "error")
        logger.error("Click predict error: %s", e)
        raise HTTPException(500, detail="Prediction failed")


@app.post("/v1/predict/session", response_model=PredictionResponse)
async def predict_session(req: SessionPredictRequest, request: Request):
    t0 = time.time()
    try:
        if not registry:
            raise HTTPException(503, "Server not ready")
        features = np.array(req.features, dtype=np.float32)
        risk = registry.predict("session", features)
        version = registry.get_version("session")
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("session", risk, elapsed_ms)
        return PredictionResponse(
            risk=_cap_risk(risk, 0.85),   # SessionModel cap 0.85
            model_version=version,
            server_timestamp=int(t0),
        )
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("session", 0.0, elapsed_ms, "error")
        logger.error("Session predict error: %s", e)
        raise HTTPException(500, detail="Prediction failed")


@app.post("/v1/predict/all", response_model=CompositeResponse)
async def predict_all(req: PredictAllRequest, request: Request):
    """Composite endpoint — runs all 3 models in parallel."""
    t0 = time.time()
    try:
        if not registry:
            raise HTTPException(503, "Server not ready")

        aim_features = np.array(req.aim_features, dtype=np.float32)
        click_features = np.array(req.click_features, dtype=np.float32)
        session_features = np.array(req.session_features, dtype=np.float32)

        aim_risk = _cap_risk(registry.predict("aim", aim_features))
        aim_conf = 0.5
        click_risk, click_conf = registry.predict_with_uncertainty("click", click_features)
        session_risk, session_conf = registry.predict_with_uncertainty("session", session_features)
        session_risk = _cap_risk(session_risk, 0.85)

        # Simple fusion: weighted average
        wb = req.whitebox_certainties
        wb_sum = sum(wb.values()) if wb else 0
        wb_avg = wb_sum / max(len(wb), 1)

        # Higher weight to aim + whitebox agreement
        aim_weight = 0.4
        click_weight = 0.3
        session_weight = 0.1
        wb_weight = 0.2

        composite = (
            aim_risk * aim_weight +
            click_risk * click_weight +
            session_risk * session_weight +
            wb_avg * wb_weight
        )
        composite = _cap_risk(composite)

        version = registry.get_version("aim")
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("all", composite, elapsed_ms)

        return CompositeResponse(
            aim_risk=aim_risk,
            click_risk=click_risk,
            session_risk=session_risk,
            composite_risk=composite,
            model_version=version,
            server_timestamp=int(t0),
        )
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _log_prediction("all", 0.0, elapsed_ms, "error")
        logger.error("All predict error: %s", e)
        raise HTTPException(500, detail="Prediction failed")


# ── Endpoints: Training ──────────────────────────────────────────────────

@app.post("/v1/training/sample")
async def collect_sample(req: TrainingSampleRequest, request: Request):
    """Collect a labeled training sample from a game server."""
    try:
        if not db:
            raise HTTPException(503, "Database not ready")
        db.store_sample(
            category=req.category,
            features=req.features,
            label=req.label,
            label_source=req.label_source,
            server_id=request.state.api_key.server_name if hasattr(request.state, 'api_key') else None,
            client_version=req.client_version,
            ping=req.ping,
            tps=req.tps,
            jitter=req.jitter,
            player_uuid=req.player_uuid,
        )
        return {"status": "ok", "stored": True}
    except Exception as e:
        logger.error("Sample storage error: %s", e)
        raise HTTPException(500, detail="Storage failed")


@app.post("/v1/train/trigger")
async def trigger_training(req: TrainTriggerRequest, request: Request):
    """Trigger model retraining (placeholder — async job)."""
    if not registry:
        raise HTTPException(503, "Not ready")
    job_id = str(uuid.uuid4())[:8]
    from cloud.training.train import Trainer
    trainer = Trainer(db, str(config.model_dir))
    try:
        result = trainer.train(req.category or "all") if hasattr(trainer, 'train') else {"status": "placeholder"}
        return {"status": "running", "job_id": job_id, "result": result}
    except Exception as e:
        logger.error("Training trigger error: %s", e)
        return {"status": "error", "job_id": job_id, "error": str(e)}


# ── Endpoints: Auth / Admin ──────────────────────────────────────────────

@app.post("/v1/auth/verify")
async def verify_key(request: Request):
    """Verify API key is valid (called periodically by plugin)."""
    return {"status": "ok", "tier": request.state.api_key.tier}


@app.post("/v1/admin/keys", response_model=CreateKeyResponse)
async def create_key(req: CreateKeyRequest, request: Request):
    """Create new API key (admin only)."""
    if not auth:
        raise HTTPException(503, "Auth not ready")
    raw_key, key_info = auth.create_key(req.server_name, req.tier, req.expires_days)
    return CreateKeyResponse(
        raw_key=raw_key,
        key_id=key_info.id,
        server_name=key_info.server_name,
        tier=key_info.tier,
    )


@app.post("/v1/admin/keys/revoke")
async def revoke_key(req: RevokeKeyRequest, request: Request):
    """Revoke API key (admin only)."""
    if not auth:
        raise HTTPException(503, "Auth not ready")
    ok = auth.revoke_key(req.key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "revoked"}


@app.get("/v1/admin/stats")
async def admin_stats(request: Request):
    """Server statistics (admin only)."""
    if not db:
        raise HTTPException(503, "Not ready")
    sample_count = db.fetch_one("SELECT COUNT(*) as cnt FROM training_samples")[0]
    key_count = db.fetch_one("SELECT COUNT(*) as cnt FROM api_keys WHERE enabled=1")[0]
    return {
        "uptime": time.time() - start_time,
        "total_predictions": total_predictions,
        "models_loaded": list(registry._models.keys()) if registry else [],
        "training_samples": sample_count,
        "active_keys": key_count,
        "memory_mb": psutil.Process().memory_info().rss / 1024 / 1024,
        "db_size_mb": os.path.getsize(config.db_path) / 1024 / 1024 if os.path.exists(config.db_path) else 0,
    }


# ── Endpoints: Health / Metrics ──────────────────────────────────────────

@app.get("/v1/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    process = psutil.Process()
    return HealthResponse(
        status="ok",
        uptime=time.time() - start_time,
        models_loaded=list(registry._models.keys()) if registry else [],
        memory_mb=process.memory_info().rss / 1024 / 1024,
        total_predictions=total_predictions,
        db_size_mb=os.path.getsize(config.db_path) / 1024 / 1024 if db and os.path.exists(config.db_path) else 0,
    )


@app.get("/v1/metrics")
async def metrics():
    """Prometheus-style metrics."""
    process = psutil.Process()
    mem_mb = process.memory_info().rss / 1024 / 1024
    return Response(
        content=(
            f"# HELP acml_memory_mb Memory usage\n"
            f"# TYPE acml_memory_mb gauge\n"
            f"acml_memory_mb {mem_mb:.1f}\n"
            f"# HELP acml_predictions_total Total predictions\n"
            f"# TYPE acml_predictions_total counter\n"
            f"acml_predictions_total {total_predictions}\n"
            f"# HELP acml_uptime_seconds Server uptime\n"
            f"# TYPE acml_uptime_seconds gauge\n"
            f"acml_uptime_seconds {time.time() - start_time:.0f}\n"
        ),
        media_type="text/plain",
    )


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "cloud.server:app",
        host=config.host,
        port=config.port,
        workers=1,        # 1GB RAM → 1 worker
        limit_concurrency=config.max_concurrency,
        log_level=config.log_level.lower(),
    )
