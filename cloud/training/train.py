"""
Trainer — LightGBM model training pipeline for anticheat ML.
============================================================
1GB RAM optimized: single-threaded, early stopping, minimal memory footprint.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import lightgbm as lgb
import numpy as np

from cloud.config import config
from cloud.database import Database

logger = logging.getLogger(__name__)


class Trainer:
    """LightGBM model trainer for anticheat detection."""

    FEATURE_NAMES = {
        "aim": ["yawJerkStd", "pitchJerkStd", "aimSmoothness",
                "rotationEntropy", "gcdError", "snapFreq"],
        "click": ["cooldownAccuracy", "missRatio", "hitMissRatio",
                  "criticalRatio", "perfectStreak"],
        "session": ["cooldownAccuracy", "missRatio", "mouseSensitivity",
                    "pitchDeltaMean", "yawDeltaMean", "gcdConsistency",
                    "rotationEntropy", "normalizedSessionDuration"],
    }

    LGBM_PARAMS = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "max_depth": 6,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "min_data_in_leaf": 20,
        "num_threads": 1,
        "verbose": -1,
    }

    def __init__(self, db: Database, model_dir: str):
        self.db = db  # Use shared Database instance (WAL mode, thread-safe)
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def train(self, category: str = "all") -> dict:
        """Train model(s). category: aim|click|session|all"""
        if category == "all":
            results = {}
            for cat in ["aim", "click", "session"]:
                try:
                    results[cat] = self._train_single(cat)
                except Exception as e:
                    logger.error("Train %s failed: %s", cat, e)
                    results[cat] = {"status": "error", "error": str(e)}
            return results
        return self._train_single(category)

    def _train_single(self, category: str) -> dict:
        """Train a single model."""
        X, y = self._load_data(category)
        if X is None:
            return {"status": "skipped", "reason": f"Insufficient samples (< {config.min_samples_for_training})"}

        n_features = X.shape[1]
        n_samples = len(X)
        pos_ratio = float(y.mean())
        logger.info("Training %s: %d samples, %d features, %.2f%% positive",
                    category, n_samples, n_features, pos_ratio * 100)

        # Check for single-class data
        unique_classes = set(y)
        if len(unique_classes) < 2:
            logger.warning("Single-class data (%s) for %s — training impossible", unique_classes, category)
            return {"status": "skipped", "reason": f"Single-class data ({unique_classes}), need both cheat and legit"}

        # Stratified split
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        # Dynamic class weight (handle single-class gracefully)
        params = self.LGBM_PARAMS.copy()
        n_neg = len(y_train[y_train == 0])
        n_pos = len(y_train[y_train == 1])
        if n_pos > 0 and n_neg > 0:
            pos_weight = n_neg / n_pos
            params["scale_pos_weight"] = min(pos_weight, 100.0)
        else:
            # Should not reach here due to check above, but be safe
            params["scale_pos_weight"] = 1.0

        # Train
        train_data = lgb.Dataset(X_train, y_train, feature_name=self.FEATURE_NAMES.get(category))
        test_data = lgb.Dataset(X_test, y_test, reference=train_data)

        model = lgb.train(
            params, train_data,
            num_boost_round=500,
            valid_sets=[test_data],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
        )

        # Evaluate
        y_pred = model.predict(X_test)
        from sklearn.metrics import roc_auc_score, f1_score
        auc = float(roc_auc_score(y_test, y_pred))
        y_pred_bin = (y_pred > 0.5).astype(int)
        f1 = float(f1_score(y_test, y_pred_bin, zero_division=0))

        logger.info("Model %s: AUC=%.4f, F1=%.4f, trees=%d",
                    category, auc, f1, model.num_trees())

        # Save
        version = f"{category}_{datetime.now():%Y%m%d_%H%M%S}"
        model_path = self.model_dir / f"{version}.txt"
        model.save_model(str(model_path))
        logger.info("Saved %s to %s", version, model_path)

        # Update symlink
        symlink = self.model_dir / f"{category}_current.txt"
        if symlink.exists():
            symlink.unlink()
        symlink.symlink_to(model_path.name)

        return {
            "status": "done",
            "version": version,
            "auc": auc,
            "f1": f1,
            "samples": n_samples,
            "positive_ratio": float(pos_ratio),
            "trees": model.num_trees(),
            "features": n_features,
        }

    def _load_data(self, category: str, max_days: int = 30):
        """Load labeled data from shared Database (WAL-mode, thread-safe)."""
        import time
        cutoff = time.time() - max_days * 86400
        rows = self.db.fetch_all(
            """SELECT features_json, label FROM training_samples
               WHERE category = ? AND label IS NOT NULL AND created_at > ?
               ORDER BY created_at DESC LIMIT 50000""",
            (category, cutoff),
        )

        if len(rows) < config.min_samples_for_training:
            return None, None

        features, labels = [], []
        for row in rows:
            feat = json.loads(row["features_json"])
            features.append(feat)
            labels.append(row["label"])

        return np.array(features, dtype=np.float32), np.array(labels, dtype=np.float32)
