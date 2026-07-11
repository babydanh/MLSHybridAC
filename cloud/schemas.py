"""
Schemas — Pydantic models for request/response validation.
==========================================================
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field, field_validator


# ── Predict Request / Response ───────────────────────────────────────────

class AimPredictRequest(BaseModel):
    features: list[float] = Field(..., min_length=6, max_length=6)
    ping: int = Field(..., ge=0, le=1000)
    tps: float = Field(..., ge=0, le=20)
    jitter: int = Field(..., ge=0, le=500)
    client_version: str | None = None

    @field_validator("features")
    @classmethod
    def validate_features(cls, v: list[float]) -> list[float]:
        for i, f in enumerate(v):
            if np.isnan(f) or np.isinf(f):
                raise ValueError(f"Feature {i} is NaN or Infinity")
            if f < -100 or f > 100:
                raise ValueError(f"Feature {i} out of range: {f}")
        return v


class ClickPredictRequest(BaseModel):
    features: list[float] = Field(..., min_length=5, max_length=5)
    ping: int = Field(..., ge=0, le=1000)
    tps: float = Field(..., ge=0, le=20)
    jitter: int = Field(..., ge=0, le=500)
    client_version: str | None = None

    @field_validator("features")
    @classmethod
    def validate_features(cls, v: list[float]) -> list[float]:
        for i, f in enumerate(v):
            if np.isnan(f) or np.isinf(f):
                raise ValueError(f"Feature {i} is NaN or Infinity")
        return v


class SessionPredictRequest(BaseModel):
    features: list[float] = Field(..., min_length=8, max_length=8)
    ping: int = Field(..., ge=0, le=1000)
    tps: float = Field(..., ge=0, le=20)
    jitter: int = Field(..., ge=0, le=500)
    client_version: str | None = None

    @field_validator("features")
    @classmethod
    def validate_features(cls, v: list[float]) -> list[float]:
        for i, f in enumerate(v):
            if np.isnan(f) or np.isinf(f):
                raise ValueError(f"Feature {i} is NaN or Infinity")
        return v


class PredictAllRequest(BaseModel):
    aim_features: list[float] = Field(..., min_length=6, max_length=6)
    click_features: list[float] = Field(..., min_length=5, max_length=5)
    session_features: list[float] = Field(..., min_length=8, max_length=8)
    ping: int = Field(..., ge=0, le=1000)
    tps: float = Field(..., ge=0, le=20)
    jitter: int = Field(..., ge=0, le=500)
    client_version: str | None = None
    whitebox_certainties: dict[str, float] = Field(default_factory=dict)
    player_uuid: str | None = None


class PredictionResponse(BaseModel):
    risk: float = Field(..., ge=0.0, le=0.985)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    model_version: str = "untrained"
    server_timestamp: int = 0


class CompositeResponse(BaseModel):
    aim_risk: float = Field(default=0.5, ge=0.0, le=0.985)
    aim_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    click_risk: float = Field(default=0.5, ge=0.0, le=0.985)
    click_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    session_risk: float = Field(default=0.5, ge=0.0, le=0.85)
    session_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    composite_risk: float = Field(default=0.5, ge=0.0, le=0.985)
    model_version: str = "untrained"
    server_timestamp: int = 0


# ── Training ─────────────────────────────────────────────────────────────

class TrainingSampleRequest(BaseModel):
    category: str = Field(..., pattern=r"^(aim|click|session)$")
    features: list[float] = Field(..., min_length=1, max_length=16)
    label: float | None = Field(None, ge=0.0, le=1.0)
    label_source: str | None = Field(None, pattern=r"^(staff_ban|staff_unban|clean_window|watchdog_bot|whitebox_high|vanilla_fingerprint|semi_supervised|synthetic_legit|unlabeled)?$")
    server_id: str | None = None
    client_version: str | None = None
    ping: int = Field(default=0, ge=0, le=1000)
    tps: float = Field(default=20.0, ge=0, le=20)
    jitter: int = Field(default=0, ge=0, le=500)
    player_uuid: str | None = None


class TrainTriggerRequest(BaseModel):
    category: str | None = Field(None, pattern=r"^(aim|click|session|all)?$")


class TrainingStatus(BaseModel):
    status: str = "queued"     # queued | running | done | failed
    job_id: str = ""
    category: str = ""
    model_version: str | None = None
    auc: float | None = None
    f1: float | None = None
    samples: int = 0
    trees: int = 0
    error: str | None = None


# ── Admin ────────────────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    server_name: str = Field(..., min_length=1, max_length=128)
    tier: str = Field(default="free", pattern=r"^(free|basic|pro|enterprise)$")
    expires_days: int = Field(default=365, ge=1, le=3650)


class CreateKeyResponse(BaseModel):
    raw_key: str = ""
    key_id: str = ""
    server_name: str = ""
    tier: str = ""


class RevokeKeyRequest(BaseModel):
    key_id: str = Field(..., min_length=1)


# ── Health ───────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    uptime: float = 0.0
    models_loaded: list[str] = []
    memory_mb: float = 0.0
    total_predictions: int = 0
    db_size_mb: float = 0.0
