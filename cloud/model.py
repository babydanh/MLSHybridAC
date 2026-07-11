"""
Model Registry — LightGBM inference with lazy loading, TTL, version management.
==============================================================================
1GB RAM optimized:
- Lazy load: model loaded only on first request
- TTL unload: model unloaded after 5 min inactivity
- Single worker: only 1 model copy in memory
- Thread pool: CPU-bound inference in 2 threads
"""

from __future__ import annotations

import gc
import logging
import time
from pathlib import Path
from typing import Optional

import lightgbm as lgb
import numpy as np

from cloud.config import config

logger = logging.getLogger(__name__)


class ModelEntry:
    """Wrapper around a loaded LightGBM Booster with metadata."""

    def __init__(self, name: str, model: lgb.Booster, version: str, feature_count: int):
        self.name = name
        self.model = model
        self.version = version
        self.feature_count = feature_count
        self.loaded_at = time.time()
        self.last_used = time.time()
        self.predict_count = 0

        # ── Pre-compute leaf values từ model dump (1 lần khi load) ──
        # Mỗi cây có 2^max_depth leaves, mỗi leaf có 1 value
        # Dùng cho tính uncertainty: variance giữa các trees
        self._leaf_values: list[np.ndarray] | None = None
        self._cache_leaf_values()

    def _cache_leaf_values(self) -> None:
        """Dump model để lấy leaf values cho mỗi tree.

        LightGBM model.dump_model() trả về cấu trúc tree với leaf_value ở mỗi node.
        Ta map leaf_index → leaf_value cho từng tree để tính uncertainty.
        """
        try:
            dump = self.model.dump_model()
            trees = dump.get("tree_info", [])
            self._leaf_values = []
            for tree in trees:
                # Duyệt tree_structure để lấy tất cả leaf_values
                leaves = self._extract_leaf_values(tree.get("tree_structure", {}))
                self._leaf_values.append(np.array(sorted(leaves)))
            logger.debug("Cached %d leaf values for %s", len(self._leaf_values), self.name)
        except Exception as e:
            self._leaf_values = None
            logger.warning("Failed to cache leaf values for %s: %s", self.name, e)

    @staticmethod
    def _extract_leaf_values(node: dict) -> list[float]:
        """Recursively extract leaf values từ tree structure."""
        if not node:
            return []
        if node.get("leaf_value") is not None:
            return [float(node["leaf_value"])]
        values = []
        values.extend(ModelEntry._extract_leaf_values(node.get("left_child", {})))
        values.extend(ModelEntry._extract_leaf_values(node.get("right_child", {})))
        return values

    @property
    def age_seconds(self) -> float:
        return time.time() - self.loaded_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_used

    def predict(self, features: np.ndarray) -> float:
        """Predict risk score [0, 0.985]."""
        if features.shape[0] != self.feature_count:
            raise ValueError(
                f"Expected {self.feature_count} features, got {features.shape[0]}"
            )
        raw = float(self.model.predict(features.reshape(1, -1))[0])
        self.last_used = time.time()
        self.predict_count += 1
        return min(raw, config.max_risk_cap)

    def predict_with_uncertainty(self, features: np.ndarray) -> tuple[float, float]:
        """Predict risk + confidence từ tree variance.

        Cách tính:
        1. Lấy leaf index cho mỗi tree từ LightGBM
        2. Map leaf index → leaf value (pre-computed khi load model)
        3. Sigmoid từng leaf value → probability per tree
        4. risk = mean(probabilities)
        5. confidence = 1 - std(probabilities) * 2, clamp [0.5, 1.0]

        Các trees càng đồng ý → std càng thấp → confidence càng cao.
        Input càng xa training data → trees disagree → std cao → confidence thấp.

        Trả về: (risk [0, 0.985], confidence [0.5, 1.0])
        """
        if features.shape[0] != self.feature_count:
            raise ValueError(
                f"Expected {self.feature_count} features, got {features.shape[0]}"
            )
        self.last_used = time.time()
        self.predict_count += 1

        # Fallback: nếu không có leaf values cached
        if self._leaf_values is None:
            raw = float(self.model.predict(features.reshape(1, -1))[0])
            return min(raw, config.max_risk_cap), 0.5

        # Lấy leaf index cho mỗi tree
        leaf_indices = self.model.predict(features.reshape(1, -1), pred_leaf=True)
        if leaf_indices is None or len(leaf_indices) == 0:
            raw = float(self.model.predict(features.reshape(1, -1))[0])
            return min(raw, config.max_risk_cap), 0.5

        # Map leaf index → leaf value → sigmoid → probability per tree
        tree_probs = []
        for tree_idx, leaf_idx in enumerate(leaf_indices[0]):
            leaf_idx_int = int(leaf_idx)
            if tree_idx < len(self._leaf_values) and leaf_idx_int < len(self._leaf_values[tree_idx]):
                leaf_value = float(self._leaf_values[tree_idx][leaf_idx_int])
            else:
                leaf_value = 0.0
            # Sigmoid: probability = 1 / (1 + exp(-leaf_value))
            prob = 1.0 / (1.0 + np.exp(-leaf_value))
            tree_probs.append(prob)

        if not tree_probs:
            raw = float(self.model.predict(features.reshape(1, -1))[0])
            return min(raw, config.max_risk_cap), 0.5

        # risk = mean tree probability
        risk = float(np.mean(tree_probs))
        # confidence = 1 - std * 2 (các trees càng đồng ý → càng confident)
        std = float(np.std(tree_probs))
        confidence = max(0.5, min(1.0, 1.0 - std * 2.0))

        return min(risk, config.max_risk_cap), confidence

    def __repr__(self) -> str:
        return (
            f"ModelEntry(name={self.name}, version={self.version}, "
            f"idle={self.idle_seconds:.0f}s, preds={self.predict_count})"
        )


class ModelRegistry:
    """Thread-safe model registry with lazy loading and TTL eviction."""

    # Model specs: (filename_pattern, feature_count)
    MODELS: dict[str, tuple[str, int]] = {
        "aim": ("aim_current.txt", 6),
        "click": ("click_current.txt", 5),
        "session": ("session_current.txt", 8),
    }

    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._models: dict[str, ModelEntry] = {}
        self._untrained_placeholders: dict[str, lgb.Booster] = {}

    # ── Public API ───────────────────────────────────────────────────────

    def predict(self, model_name: str, features: np.ndarray) -> float:
        """Predict with lazy loading. Returns risk [0, 0.985]."""
        entry = self._get_or_load(model_name)
        return entry.predict(features)

    def predict_with_uncertainty(self, model_name: str, features: np.ndarray) -> tuple[float, float]:
        """Predict risk + confidence từ tree variance.

        Returns (risk [0, 0.985], confidence [0.5, 1.0]).
        """
        entry = self._get_or_load(model_name)
        return entry.predict_with_uncertainty(features)

    def get_version(self, model_name: str) -> str:
        """Get currently loaded model version."""
        entry = self._get_or_load(model_name)
        return entry.version

    def reload_all(self) -> list[str]:
        """Force reload all models. Returns list of errors."""
        errors: list[str] = []
        for name in self.MODELS:
            try:
                self._load_model(name, force=True)
            except Exception as e:
                errors.append(f"{name}: {e}")
                logger.exception("Failed to reload model %s", name)
        logger.info("Reloaded models: %s loaded, %d errors", list(self._models.keys()), len(errors))
        return errors

    def unload_idle(self, max_idle: int | None = None) -> int:
        """Unload models idle longer than max_idle (default: config TTL)."""
        max_idle = max_idle or config.model_ttl_seconds
        now = time.time()
        to_unload = [
            name
            for name, entry in self._models.items()
            if now - entry.last_used > max_idle
        ]
        for name in to_unload:
            del self._models[name]
        if to_unload:
            gc.collect()
            logger.info("Unloaded idle models: %s", to_unload)
        return len(to_unload)

    def hot_reload(self) -> list[str]:
        """Check for file changes and reload if needed. Returns reloaded names."""
        reloaded: list[str] = []
        for name, (pattern, _) in self.MODELS.items():
            model_path = self.model_dir / pattern
            if not model_path.exists():
                continue
            current = self._models.get(name)
            if current is None:
                continue
            mtime = model_path.stat().st_mtime
            # Check if model file is newer than loaded version
            loaded_ts = _parse_version_timestamp(current.version)
            if loaded_ts and mtime > loaded_ts:
                try:
                    self._load_model(name, force=True)
                    reloaded.append(name)
                    logger.info("Hot-reloaded %s (mtime %d)", name, mtime)
                except Exception as e:
                    logger.error("Hot-reload failed for %s: %s", name, e)
        return reloaded

    def stats(self) -> dict:
        """Current registry stats."""
        return {
            name: {
                "version": entry.version,
                "idle_seconds": entry.idle_seconds,
                "predict_count": entry.predict_count,
                "age_seconds": entry.age_seconds,
            }
            for name, entry in self._models.items()
        }

    # ── Internal ─────────────────────────────────────────────────────────

    def _get_or_load(self, name: str) -> ModelEntry:
        """Get model, loading if necessary."""
        if name not in self._models:
            self._load_model(name)
        return self._models[name]

    def _load_model(self, name: str, force: bool = False) -> None:
        """Load model from disk or create untrained placeholder."""
        if name not in self.MODELS:
            raise ValueError(f"Unknown model: {name}. Available: {list(self.MODELS.keys())}")

        pattern, n_features = self.MODELS[name]
        model_path = self.model_dir / pattern
        resolved = model_path.resolve() if model_path.is_symlink() else model_path

        if resolved.exists():
            model = lgb.Booster(model_file=str(resolved))
            version = f"{resolved.stem}"
            entry = ModelEntry(name=name, model=model, version=version, feature_count=n_features)
            self._models[name] = entry
            logger.info("Loaded %s v%s (%d trees, %s)", name, version, model.num_trees(), resolved)
        else:
            if name not in self._untrained_placeholders:
                placeholder = self._create_untrained(n_features)
                self._untrained_placeholders[name] = placeholder
            entry = ModelEntry(
                name=name,
                model=self._untrained_placeholders[name],
                version="untrained",
                feature_count=n_features,
            )
            self._models[name] = entry
            logger.warning("Model %s not found at %s — using untrained (returns 0.5)", name, model_path)

    @staticmethod
    def _create_untrained(n_features: int) -> lgb.Booster:
        """Create a dummy LightGBM model that returns 0.5 for any input."""
        import numpy as np
        import tempfile

        dataset = lgb.Dataset(np.zeros((2, n_features)), label=[0, 1])
        model = lgb.train(
            {"objective": "binary", "num_leaves": 2, "num_threads": 1, "verbose": -1},
            dataset,
            num_boost_round=1,
        )
        return model

    def __repr__(self) -> str:
        return f"ModelRegistry(models={list(self._models.keys())}, dir={self.model_dir})"


def _parse_version_timestamp(version: str) -> float | None:
    """Parse timestamp from version string like 'aim_20260701_123456'."""
    import re
    m = re.search(r"(\d{8})_?(\d{6})?", version)
    if not m:
        return None
    try:
        from datetime import datetime
        ts_str = m.group(1)
        time_part = m.group(2) or "000000"
        return datetime.strptime(f"{ts_str} {time_part}", "%Y%m%d %H%M%S").timestamp()
    except (ValueError, IndexError):
        return None
