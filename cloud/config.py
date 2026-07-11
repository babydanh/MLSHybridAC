"""
MLSHybridAC — Cloud Inference Server Configuration
==================================================
1GB RAM VPS optimized. All settings via env vars with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Config:
    # ── Server ────────────────────────────────────────────────────────────
    host: str = os.getenv("ML_HOST", "127.0.0.1")
    port: int = int(os.getenv("ML_PORT", "8080"))
    workers: int = int(os.getenv("ML_WORKERS", "1"))           # 1GB RAM → 1 worker
    max_concurrency: int = int(os.getenv("ML_MAX_CONCURRENCY", "16"))
    max_requests: int = int(os.getenv("ML_MAX_REQUESTS", "10000"))  # restart sau N req
    request_max_size: int = int(os.getenv("ML_REQUEST_MAX_SIZE", "10240"))  # 10KB

    # ── Paths ────────────────────────────────────────────────────────────
    data_dir: Path = Path(os.getenv("ML_DATA_DIR", "/opt/ac-ml/data"))
    model_dir: Path = Path(os.getenv("ML_MODEL_DIR", "/opt/ac-ml/data/models"))
    training_dir: Path = Path(os.getenv("ML_TRAINING_DIR", "/opt/ac-ml/data/training"))
    db_path: Path = Path(os.getenv("ML_DB_PATH", "/opt/ac-ml/data/vnac.db"))

    # ── Auth ─────────────────────────────────────────────────────────────
    admin_key: str = os.getenv("ML_ADMIN_KEY", "")             # Bắt buộc set trong production
    jwt_secret: str = os.getenv("ML_JWT_SECRET", "change-me-in-production")

    # ── Rate Limiting ───────────────────────────────────────────────────
    rate_limit_tiers: dict[str, int] = field(default_factory=lambda: {
        "free": 60,          # 60 req/min
        "basic": 600,        # 600 req/min
        "pro": 3000,         # 3000 req/min
        "enterprise": 999999,
    })
    global_rate_limit: int = int(os.getenv("ML_GLOBAL_RATE_LIMIT", "5000"))

    # ── Model ────────────────────────────────────────────────────────────
    model_ttl_seconds: int = int(os.getenv("ML_MODEL_TTL", "300"))     # 5 min unload
    model_cache_size: int = int(os.getenv("ML_MODEL_CACHE", "3"))      # max models in mem
    prediction_timeout: float = float(os.getenv("ML_PREDICTION_TIMEOUT", "5.0"))
    model_version: str = os.getenv("ML_MODEL_VERSION", "stable")

    # ── Features ─────────────────────────────────────────────────────────
    aim_feature_count: int = 6
    click_feature_count: int = 5
    session_feature_count: int = 8

    AIM_FEATURE_NAMES: tuple[str, ...] = (
        "yawJerkStd", "pitchJerkStd", "aimSmoothness",
        "rotationEntropy", "gcdError", "snapFreq",
    )
    CLICK_FEATURE_NAMES: tuple[str, ...] = (
        "cooldownAccuracy", "missRatio", "hitMissRatio",
        "criticalRatio", "perfectStreak",
    )
    SESSION_FEATURE_NAMES: tuple[str, ...] = (
        "cooldownAccuracy", "missRatio", "mouseSensitivity",
        "pitchDeltaMean", "yawDeltaMean", "gcdConsistency",
        "rotationEntropy", "normalizedSessionDuration",
    )

    # ── Safety / FP Prevention ──────────────────────────────────────────
    max_risk_cap: float = 0.985          # Không bao giờ trả risk > 0.985
    min_samples_for_training: int = 1000  # Cần 1000+ labeled samples mới train
    min_auc_to_deploy: float = 0.75       # AUC tối thiểu để deploy model mới
    anomaly_std_threshold: float = 3.0    # z-score threshold cho anomaly detection

    # ── Monitoring ───────────────────────────────────────────────────────
    metrics_enabled: bool = os.getenv("ML_METRICS", "true").lower() == "true"
    log_level: str = os.getenv("ML_LOG_LEVEL", "INFO")
    log_json: bool = os.getenv("ML_LOG_JSON", "true").lower() == "true"

    # ── Derived ──────────────────────────────────────────────────────────
    def __post_init__(self):
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "model_dir", Path(self.model_dir))
        object.__setattr__(self, "training_dir", Path(self.training_dir))
        object.__setattr__(self, "db_path", Path(self.db_path))

    @property
    def all_feature_counts(self) -> dict[str, int]:
        return {
            "aim": self.aim_feature_count,
            "click": self.click_feature_count,
            "session": self.session_feature_count,
        }

    @property
    def all_feature_names(self) -> dict[str, tuple[str, ...]]:
        return {
            "aim": self.AIM_FEATURE_NAMES,
            "click": self.CLICK_FEATURE_NAMES,
            "session": self.SESSION_FEATURE_NAMES,
        }


config = Config()

# Validation — admin key must be set in production
if config.admin_key == "":
    import warnings
    warnings.warn(
        "ML_ADMIN_KEY is not set! Set it in production to secure admin endpoints.",
        RuntimeWarning,
    )
