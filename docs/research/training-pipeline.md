# MLSHybridAC — Training Pipeline Design Document

> **Version**: 1.0  
> **Last Updated**: 2026-07-10  
> **Scope**: Complete ML training pipeline for Minecraft anticheat (GrimAC / MLSHybridAC)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Collection Strategy](#2-data-collection-strategy)
3. [Database Schema](#3-database-schema)
4. [Label Sources and Reliability](#4-label-sources-and-reliability)
5. [Negative Sampling Strategy](#5-negative-sampling-strategy)
6. [LightGBM Training Pipeline](#6-lightgbm-training-pipeline)
7. [Label Pipeline](#7-label-pipeline)
8. [Auto-training Workflow](#8-auto-training-workflow)
9. [Model Versioning](#9-model-versioning)
10. [Java Integration: Server-Side Label Submission](#10-java-integration-server-side-label-submission)
11. [Evaluation and Monitoring](#11-evaluation-and-monitoring)
12. [Deployment Guide](#12-deployment-guide)
13. [Appendices](#13-appendices)

---

## 1. System Overview

### 1.1 Current Architecture (as-read from codebase)

```
+----------------------------------------------------------+
|                    Minecraft Server                       |
|                                                          |
|  FeatureBridge.java -- feature extraction (6/5/8 feats)  |
|       |                                                  |
|       +--> AimModel (GBDT, 6 features)                   |
|       +--> ClickModel (OnlineLogReg, 5 features)         |
|       +--> SessionModel (Ensemble LogReg, 8 features)    |
|       |                                                  |
|       +--> DataCollector --> per-player CSV (passive)    |
|       +--> MLDataManager --> training CSVs / model files |
|       +--> FusionEngine --> Bayesian posterior -> Action |
|                                                          |
|  train_gbdt.py -- offline sklearn GBDT training          |
|                   30 trees, max_depth=4, learning_rate=0.1|
+----------------------------------------------------------+
```

### 1.2 Target Architecture

```
+----------------------------------------------------------+
|                    Minecraft Server                       |
|                                                          |
|  DataCollector.java  -->  Local CSV (passive logging)    |
|       +                                                 |
|  LabelSubmitter (NEW) --> HTTP POST -> Cloud API         |
|       |                     (labeled samples, JSON)      |
|       |                                                  |
|       v                                                  |
| +---------------------------------------------------+   |
| |              Cloud Backend (Python)                |   |
| |                                                    |   |
| |  /v1/samples --> SQLite/Postgres --> LabelPipeline |   |
| |  /v1/train   --> LightGBM Trainer                  |   |
| |  /v1/predict --> Model Inference API               |   |
| |                                                    |   |
| |  Cron (24h) --> AutoTrainer                        |   |
| |  --> aim_{date}.txt, click_{date}.txt,            |   |
| |      session_{date}.txt                            |   |
| +---------------------------------------------------+   |
|                                                          |
|  Server downloads updated model -> symlink -> restart    |
+----------------------------------------------------------+
```

### 1.3 Key Differences from Current Implementation

| Aspect | Current | Target |
|--------|---------|--------|
| GBDT framework | sklearn GradientBoostingClassifier | LightGBM (faster, better AUC) |
| Model format | Custom binary (GBDT.java) | Same format (backward compat) |
| Training location | Offline, manual Python script | Cloud auto-training (cron 24h) |
| Label sources | None automated | 7 sources (staff, watchdog, semi-sup, etc.) |
| Data collection | Local CSV only | Local CSV + Cloud API submission |
| Model versioning | Single file overwrite | Symlink-based, keep last 5 versions |
| Negative sampling | None | Time-window + hard negative mining |
| Semi-supervised | None | Confidence-thresholded auto-labeling |

### 1.4 Training Data Flow

```
Every tick / event on server:
  FeatureBridge computes features
  -> MLModelManager runs inference (existing)
  -> DataCollector logs to CSV (existing)
  -> LabelSubmitter (NEW): if labeled sample available
       -> POST /v1/samples { category, features, label, ... }

Every 24h (cron on cloud backend):
  Load labeled samples from DB (last 30 days)
  -> LabelPipeline: validate, deduplicate, compute weights
  -> Train 3 models (aim, click, session)
  -> Evaluate vs previous model
  -> Update symlink if AUC improved
  -> Keep last 5 versions, cleanup old

On server restart (or /ml reload command):
  Server downloads latest model files
  -> MLDataManager loads into AimModel/ClickModel/SessionModel
  -> FusionEngine uses new weights
```

## 2. Data Collection Strategy

### 2.1 Sample JSON Format

Each labeled sample sent to the cloud API follows this schema:

```json
{
  "category": "aim",
  "features": [0.042, 0.031, 0.891, 3.2, 0.003, 0.12],
  "label": 1.0,
  "label_source": "staff_ban",
  "server_id": "a1b2c3d4-e5f6-...",
  "client_version": "1.21",
  "ping": 45,
  "tps": 20.0,
  "timestamp": 1789123456789,
  "player_uuid": "550e8400-e29b-...",
  "whitebox_certainties": {
    "movement": 0.0,
    "combat": 0.85,
    "packet": 0.0
  },
  "is_flagged": true
}
```

### 2.2 Feature Vectors per Category

**Aim (6 features)** -- from MLModelManager.extractAimFeatures():

| Index | Name | Range | Description |
|-------|------|-------|-------------|
| 0 | yawJerkStd | [0, +inf) | Std dev of yaw acceleration (ping-normalized) |
| 1 | pitchJerkStd | [0, +inf) | Std dev of pitch acceleration (ping-normalized) |
| 2 | aimSmoothness | [0, 1] | Correlation between consecutive yaw deltas |
| 3 | rotationEntropy | [0, 8] | Shannon entropy of rotation delta distribution |
| 4 | gcdError | [0, 0.5] | Avg deviation from 0.5-degree grid alignment |
| 5 | snapFreq | [0, 1] | Frequency of abrupt rotation jumps |

**Click (5 features)** -- from MLModelManager.extractClickFeatures():

| Index | Name | Range | Description |
|-------|------|-------|-------------|
| 0 | cooldownAccuracy | [0, 0.98] | How precisely attacks match weapon cooldown |
| 1 | missRatio | [0, 1] | Fraction of missed attack opportunities |
| 2 | hitMissRatio | [0, 1] | Proportion of swings that connect |
| 3 | criticalRatio | [0, 1] | Fraction of attacks while sprint-jumping |
| 4 | perfectStreak | [0, +inf) | Longest consecutive perfect cooldown attacks |

**Session (8 features)** -- from MLModelManager.extractSessionFeatures():

| Index | Name | Range | Description |
|-------|------|-------|-------------|
| 0 | cooldownAccuracy | [0, 0.98] | Same as click feature #0 |
| 1 | missRatio | [0, 1] | Same as click feature #1 |
| 2 | mouseSensitivity | [0, 1] | Inferred sensitivity (pitch/yaw ratio) |
| 3 | pitchDeltaMean | [0, +inf) | Mean pitch change per tick |
| 4 | yawDeltaMean | [0, +inf) | Mean yaw change per tick |
| 5 | gcdConsistency | [0, 1] | Inverse of gcdError (1.0 - error * 4) |
| 6 | rotationEntropy | [0, 8] | Shannon entropy of rotation deltas |
| 7 | normalizedSessionDuration | [0, 1] | Session duration / 1 hour (capped) |

### 2.3 When to Submit a Labeled Sample

| Trigger | Condition | Action |
|---------|-----------|--------|
| Staff /ban | Ban command executed on player | Submit all recent features as label=1.0, source="staff_ban" |
| Staff /unban | Unban command executed | Submit features from time of original flag as label=0.0, source="staff_unban" |
| Clean window | 1h no flags + 100+ checks passed | Submit 1 random sample per 10min window as label=0.0, source="clean_window" |
| Watchdog bot hit | Bot confirms cheat | Submit label=1.0, source="watchdog_bot" |
| High whitebox certainty | Any check certainty > 0.95 | Submit label=1.0, source="whitebox_high" |
| Known vanilla fingerprint | Client brand = vanilla + no flags for 30min | Submit label=0.0, source="vanilla_fingerprint" |
| Semi-supervised | Model score > 0.95 or < 0.05 (stable) | Submit auto-label with source="semi_supervised" |

### 2.4 Sampling Rate Limits

To avoid overwhelming the cloud API:

- **Positive samples** (label=1.0): Always submit (rare event)
- **Negative samples** (label=0.0): Max 1 sample per player per 10 minutes
- **Clean window negatives**: Max 6 per player per hour (1 per 10min)
- **Bulk submission**: Buffer samples on server, flush every 60s in batch (max 100 samples/batch)
- **Rate limit**: HTTP 429 backoff with exponential retry (1s, 2s, 4s, 8s, max 30s)

## 3. Database Schema

### 3.1 SQLite Schema (Cloud Backend)

```sql
-- training_samples.db

-- Core labeled samples table
CREATE TABLE training_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK(category IN ('aim', 'click', 'session')),
    features_json TEXT NOT NULL,          -- JSON array of floats
    label REAL,                            -- 0.0 or 1.0, NULL if unlabeled
    label_source TEXT,                      -- See Section 4
    -- Context fields
    server_id TEXT,
    player_uuid TEXT NOT NULL,
    client_version TEXT,
    ping INTEGER,
    tps REAL,
    whitebox_certainties_json TEXT,        -- JSON object
    is_flagged INTEGER DEFAULT 0,
    -- Metadata
    created_at INTEGER NOT NULL,           -- unix ms
    sample_weight REAL DEFAULT 1.0,        -- importance weight (label pipeline)
    is_valid INTEGER DEFAULT 1,            -- set to 0 by label validation
    duplicate_of_id INTEGER REFERENCES training_samples(id),
    FOREIGN KEY (duplicate_of_id) REFERENCES training_samples(id)
);

CREATE INDEX idx_samples_category ON training_samples(category);
CREATE INDEX idx_samples_label ON training_samples(label) WHERE label IS NOT NULL;
CREATE INDEX idx_samples_source ON training_samples(label_source);
CREATE INDEX idx_samples_created ON training_samples(created_at);
CREATE INDEX idx_samples_player ON training_samples(player_uuid);
CREATE INDEX idx_samples_valid ON training_samples(is_valid) WHERE is_valid = 1;

-- Model versions table
CREATE TABLE model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK(category IN ('aim', 'click', 'session')),
    version TEXT NOT NULL,                  -- e.g. "aim_20260701_030000"
    model_path TEXT NOT NULL,              -- relative path in filesystem
    auc REAL,                              -- evaluation AUC
    best_f1 REAL,                          -- best F1 on test set
    train_samples INTEGER,                 -- number of training samples
    test_samples INTEGER,                  -- number of test samples
    positive_ratio REAL,                   -- ratio of positives in training set
    num_trees INTEGER,                     -- number of trees (GBDT)
    num_features INTEGER,                  -- number of features
    hyperparams_json TEXT,                 -- hyperparameters used
    is_active INTEGER DEFAULT 0,           -- currently live model
    trained_at INTEGER NOT NULL,           -- unix ms
    training_duration_seconds REAL,        -- how long training took
    notes TEXT                             -- any notes (e.g. "regressed, kept old")
);

CREATE INDEX idx_versions_category ON model_versions(category);
CREATE INDEX idx_versions_active ON model_versions(is_active) WHERE is_active = 1;

-- Hard negative mining candidates
CREATE TABLE hard_negatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id INTEGER NOT NULL REFERENCES training_samples(id),
    model_score REAL NOT NULL,             -- model prediction score
    decision_boundary_distance REAL,       -- distance from 0.5
    reviewed INTEGER DEFAULT 0,            -- staff reviewed?
    created_at INTEGER NOT NULL
);

-- Label source statistics
CREATE TABLE label_source_stats (
    source TEXT PRIMARY KEY,
    total_count INTEGER DEFAULT 0,
    positive_count INTEGER DEFAULT 0,
    negative_count INTEGER DEFAULT 0,
    last_sample_at INTEGER
);
```

### 3.2 PostgreSQL Alternative

For production deployments, use PostgreSQL with TimescaleDB:

```sql
-- Same schema but use TIMESTAMPTZ for created_at
-- JSONB for features_json and whitebox_certainties_json
-- SELECT create_hypertable('training_samples', 'created_at');
```

## 4. Label Sources and Reliability

### 4.1 Source Matrix

| Source | Label | Reliability | Volume | Use Case |
|--------|-------|-------------|--------|----------|
| staff_ban | 1.0 | ★★★★★ Very High | Very Low | Gold standard -- manual ban confirmed |
| staff_unban | 0.0 | ★★★★★ Very High | Extremely Low | False positive correction |
| watchdog_bot | 1.0 | ★★★★ High | Medium | Automated bot hit confirmation |
| clean_window | 0.0 | ★★★ Medium | Very High | Negative sampling via time window |
| whitebox_high | 1.0 | ★★★ Medium | Medium | High-certainty whitebox flag |
| vanilla_fingerprint | 0.0 | ★★★★ High | Low | Client brand = vanilla + clean play |
| semi_supervised | auto | ★★ Low | High | Model auto-label, needs review |

### 4.2 Source Weights for Training

Each sample gets a sample_weight used in LightGBM training:

| Source | Weight | Rationale |
|--------|--------|-----------|
| staff_ban | 5.0 | Gold standard -- most reliable positive |
| staff_unban | 5.0 | Gold standard -- most reliable negative |
| watchdog_bot | 3.0 | Automated but reliable (bot pattern) |
| clean_window | 0.5 | Weak negative (player may cheat subtly) |
| whitebox_high | 1.5 | Moderate reliability whitebox signal |
| vanilla_fingerprint | 2.0 | Reliable negative (client version verified) |
| semi_supervised | 0.3 | Low confidence auto-label |

Final weight = source_weight * class_balance_weight.

### 4.3 Source Details

#### staff_ban (Positive Gold Standard)

- **Trigger**: Console command /ban executed by staff
- **Reliability**: Maximum -- human staff made the decision
- **Delay**: Submit features from the LAST 60 seconds before the ban command
- **Risk**: Staff may ban for wrong reasons (false reputation, chat behavior)
- **Mitigation**: Only submit if staff has > 50 bans with < 5% appeal rate
- **Volume**: ~1-5 per day per server

#### staff_unban (Negative Gold Standard)

- **Trigger**: Console command /unban after appeal review
- **Reliability**: Maximum -- staff reviewed evidence and determined false positive
- **Delay**: Submit features from the TIME OF ORIGINAL BAN (requires lookup)
- **Volume**: < 1 per day per server

#### watchdog_bot (Positive High Reliability)

- **Trigger**: Watchdog bot account confirms the player is cheating
- **Reliability**: High for obvious cheats (killaura, aimbot), lower for subtle
- **Volume**: ~10-50 per day per server

#### clean_window (Negative Medium Reliability)

- **Trigger**: Player online 1+ hours with zero flags AND 100+ checks passed
- **Sampling**: 1 random snapshot per 10-minute clean window
- **Reliability**: Medium -- player could toggle cheats
- **Weight**: 0.5 to prevent subtle cheats from training as "legit"
- **Volume**: Very high -- primary source of negatives

#### whitebox_high (Positive Medium Reliability)

- **Trigger**: Grim check certainty > 0.95
- **Mitigation**: Movement/Packet >0.95 gets weight 2.5; Combat_Aim gets 1.5

#### vanilla_fingerprint (Negative High Reliability)

- **Trigger**: Client brand = "vanilla" + 30+ min play with zero flags
- **Reliability**: High -- vanilla client is confirmed legitimate
- **Weight**: 2.0 (accounts for possible external overlays)

#### semi_supervised (Auto-label, Low Reliability)

- **Trigger**: Model predicts with confidence > 0.95 or < 0.05 (stable over 3 ticks)
- **Weight**: 0.3 (lowest) so auto-labels don't dominate training
- **Review**: Samples at boundary (0.90-0.95 or 0.05-0.10) flagged for staff

### 4.4 Label Quality Pipeline

```
Raw sample from server
    |
    v
+-----------------------+
| 1. Schema Validation  |  <- Check required fields, feature ranges
+-----------------------+
    |
    v
+-----------------------+
| 2. Deduplication      |  <- Same player_uuid + near-identical features
+-----------------------+
    |
    v
+-----------------------+
| 3. Range Validation   |  <- Feature values within expected ranges
+-----------------------+     Outliers flagged for review
    |
    v
+-----------------------+
| 4. Weight Assignment  |  <- Multiply source_weight * class_balance_weight
+-----------------------+
    |
    v
+-----------------------+
| 5. Store in SQLite    |  <- Insert into training_samples
+-----------------------+
```

## 5. Negative Sampling Strategy

### 5.1 Class Imbalance Challenge

In anticheat ML, positives (cheaters) are rare compared to negatives (legitimate players). Typical ratios:

| Category | Expected Positive Ratio | Flipped Ratio (Neg:Pos) |
|----------|------------------------|------------------------|
| aim | 0.1% -- 1% | 99:1 to 999:1 |
| click | 0.5% -- 5% | 19:1 to 199:1 |
| session | 1% -- 10% | 9:1 to 99:1 |

Without corrective measures, a classifier learns to always predict "legitimate" and achieves 99% accuracy while detecting nothing.

### 5.2 Three-Pronged Strategy

#### A. Time-Window Negative Sampling

The primary source of negatives: clean play windows.

```
Player Session Timeline:
|-----30min grace----|----------60min clean play----------|--flag--|
                     ^                                  ^       ^
                     |                                  |       |
                     +--- sample 1 neg at t=40min       |       |
                     +--- sample 2 neg at t=50min       |       |
                     +--- sample 3 neg at t=60min       |       |
                                               flag at t=70min    |
                                                        ban at t=72min
```

- First 30 minutes after join: skip (grace period, player may be warming up)
- Sample every 10 minutes during clean windows (no flags, no high whitebox)
- Max 6 negative samples per player per hour

#### B. Hard Negative Mining

Samples near the decision boundary that the current model finds difficult:

```python
def mine_hard_negatives(model, unlabeled_pool, n_samples=100):
    """
    Find unlabeled samples where model score is in [0.35, 0.65].
    These are the most informative for improving the decision boundary.
    """
    scores = model.predict(unlabeled_pool)
    boundary_dist = np.abs(scores - 0.5)
    hard_indices = np.argsort(boundary_dist)[:n_samples]
    return unlabeled_pool[hard_indices], scores[hard_indices]
```

These hard negatives are stored in the `hard_negatives` table for staff review.

#### C. Class-Weighted Training

In LightGBM, use `scale_pos_weight` to handle imbalance:

```python
pos_weight = len(y_train[y_train == 0]) / max(len(y_train[y_train == 1]), 1)
params['scale_pos_weight'] = min(pos_weight, 100)  # cap at 100x
```

### 5.3 Final Sample Weight Formula

```
sample_weight = source_weight * class_balance_weight

class_balance_weight = total_negatives / total_positives
    (applied to positive samples only; negatives get 1.0)
```

Example with 10,000 negatives and 100 positives:

| Source | Source Weight | Class Balance | Final Weight |
|--------|--------------|---------------|--------------|
| staff_ban (pos) | 5.0 | 100 | 500.0 |
| watchdog_bot (pos) | 3.0 | 100 | 300.0 |
| clean_window (neg) | 0.5 | 1.0 | 0.5 |
| vanilla_fingerprint (neg) | 2.0 | 1.0 | 2.0 |

## 6. LightGBM Training Pipeline

### 6.1 Overview

Replace the current sklearn GBDT (train_gbdt.py, 30 trees, max_depth=4, lr=0.1) with LightGBM. Benefits:

- **4-10x faster training** on sparse/high-dim data
- **Native categorical feature support** (for client_version, server_id)
- **Built-in handling of missing values**
- **GPU training support** for large datasets
- **Leaf-wise tree growth** (better AUC than depth-wise)
- **Early stopping** with validation set
- **Sample weights** built into the API

### 6.2 Training Script

File: cloud/training/train.py

```python
#!/usr/bin/env python3
"""
Cloud training pipeline for MLSHybridAC anticheat ML models.

Replaces the offline sklearn GBDT training (train_gbdt.py) with a
fully automated LightGBM pipeline that reads from the labeled samples
database and produces binary model files compatible with
GBDT.java / AimModel.java / ClickModel.java / SessionModel.java.

Usage:
    python train.py --category aim --db training.db --output ./models/
    python train.py --all --db training.db --output ./models/

Requirements:
    pip install lightgbm numpy pandas scikit-learn
"""
import argparse
import json
import logging
import sqlite3
import struct
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score,
    precision_recall_curve,
    f1_score,
    average_precision_score,
    confusion_matrix,
)

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trainer")


class ModelTrainer:
    """
    LightGBM trainer for anticheat models.

    Handles data loading, feature engineering, training with sample weights,
    evaluation, and export to GBDT.java-compatible binary format.
    """

    # Feature definitions MUST match MLModelManager extract methods
    FEATURE_DEFS = {
        "aim": {
            "cols": [
                "yawJerkStd", "pitchJerkStd", "aimSmoothness",
                "rotationEntropy", "gcdError", "snapFreq",
            ],
            "n_features": 6,
        },
        "click": {
            "cols": [
                "cooldownAccuracy", "missRatio", "hitMissRatio",
                "criticalRatio", "perfectStreak",
            ],
            "n_features": 5,
        },
        "session": {
            "cols": [
                "cooldownAccuracy", "missRatio", "mouseSensitivity",
                "pitchDeltaMean", "yawDeltaMean", "gcdConsistency",
                "rotationEntropy", "normalizedSessionDuration",
            ],
            "n_features": 8,
        },
    }

    SOURCE_WEIGHTS = {
        "staff_ban": 5.0, "staff_unban": 5.0, "watchdog_bot": 3.0,
        "clean_window": 0.5, "whitebox_high": 1.5,
        "vanilla_fingerprint": 2.0, "semi_supervised": 0.3,
    }

    BASE_PARAMS = {
        "objective": "binary",
        "metric": "auc",
        "boosting": "gbdt",
        "num_leaves": 31,
        "max_depth": 6,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "min_data_in_leaf": 20,
        "scale_pos_weight": "auto",
        "num_threads": 4,
        "verbosity": -1,
        "seed": 42,
        "deterministic": True,
    }

    def __init__(self, db_path: str, model_dir: str, max_days: int = 30):
        self.db_path = db_path
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.max_days = max_days

    def load_data(self, category: str, min_samples: int = 500):
        """Load labeled training data from SQLite for a given category."""
        if category not in self.FEATURE_DEFS:
            raise ValueError(f"Unknown category: {category}")

        logger.info(f"Loading {category} data from {self.db_path}...")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        df = pd.read_sql_query(
            """
            SELECT id, features_json, label, label_source,
                   ping, tps, sample_weight, created_at
            FROM training_samples
            WHERE category = ? AND label IS NOT NULL
              AND is_valid = 1
              AND created_at > (strftime('%%s', 'now') - ?) * 1000
            ORDER BY created_at DESC
            """,
            conn,
            params=(category, self.max_days * 86400),
        )
        conn.close()
        logger.info(f"Loaded {len(df)} raw samples for {category}")

        if len(df) < min_samples:
            logger.warning(f"Insufficient samples: {len(df)} < {min_samples}")
            return None, None, None

        # Parse features from JSON
        X_list = []
        for _, row in df.iterrows():
            feats = json.loads(row["features_json"])
            expected_n = self.FEATURE_DEFS[category]["n_features"]
            if len(feats) > expected_n:
                feats = feats[:expected_n]
            elif len(feats) < expected_n:
                feats = feats + [0.0] * (expected_n - len(feats))
            X_list.append(feats)

        X = np.array(X_list, dtype=np.float32)
        y = df["label"].values.astype(np.float64)

        # Compute sample weights
        source_weights = df["label_source"].map(
            lambda s: self.SOURCE_WEIGHTS.get(s, 1.0)
        ).values

        n_pos = np.sum(y == 1.0)
        n_neg = np.sum(y == 0.0)
        if n_pos > 0 and n_neg > 0:
            class_weight = n_neg / n_pos
            class_balance = np.where(y == 1.0, class_weight, 1.0)
        else:
            class_balance = np.ones_like(y)

        db_weights = df["sample_weight"].values.astype(np.float64)
        db_weights = np.nan_to_num(db_weights, nan=1.0)
        db_weights = np.clip(db_weights, 0.1, None)

        sample_weights = source_weights * class_balance * db_weights
        sample_weights = np.clip(sample_weights, 0.01, 1000.0)

        logger.info(f"  Samples: {len(X)} total, {n_pos} positive, {n_neg} negative")
        return X, y, sample_weights

    def train(self, category, X, y, sample_weight=None,
              num_boost_round=500, early_stopping_rounds=50):
        """Train a LightGBM model for the given category."""
        X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
            X, y, sample_weight,
            test_size=0.2, random_state=42, stratify=y,
        )

        params = self.BASE_PARAMS.copy()
        n_pos = np.sum(y_train == 1.0)
        n_neg = np.sum(y_train == 0.0)
        if n_pos > 0 and n_neg > 0:
            params["scale_pos_weight"] = min(n_neg / n_pos, 100.0)
            logger.info(f"scale_pos_weight = {params['scale_pos_weight']:.2f}")

        train_data = lgb.Dataset(X_train, y_train, weight=w_train)
        test_data = lgb.Dataset(X_test, y_test, weight=w_test, reference=train_data)

        logger.info(f"Training {category}: {X_train.shape[0]} train, {X_test.shape[0]} test")
        model = lgb.train(
            params, train_data,
            num_boost_round=num_boost_round,
            valid_sets=[test_data],
            valid_names=["eval"],
            callbacks=[
                lgb.early_stopping(early_stopping_rounds),
                lgb.log_evaluation(50),
            ],
        )

        # Evaluate
        y_pred = model.predict(X_test, num_iteration=model.best_iteration)
        auc = roc_auc_score(y_test, y_pred)
        ap = average_precision_score(y_test, y_pred)

        precisions, recalls, thresholds = precision_recall_curve(y_test, y_pred)
        f1_scores = 2 * precisions[:-1] * recalls[:-1] / (precisions[:-1] + recalls[:-1] + 1e-9)
        best_f1 = f1_scores.max()
        best_threshold = thresholds[f1_scores.argmax()]

        logger.info(f"Test AUC: {auc:.4f}, AP: {ap:.4f}, Best F1: {best_f1:.4f}")

        # Feature importance
        importance = model.feature_importance(importance_type="gain")
        for name, imp in sorted(
            zip(self.FEATURE_DEFS[category]["cols"], importance),
            key=lambda x: x[1], reverse=True,
        ):
            logger.info(f"  {name}: {imp:.2f}")

        return {
            "model": model,
            "best_iteration": model.best_iteration,
            "auc": float(auc), "ap": float(ap),
            "best_f1": float(best_f1),
            "best_threshold": float(best_threshold),
            "n_train": len(X_train), "n_test": len(X_test),
            "n_pos": int(n_pos), "n_neg": int(n_neg),
        }

    def export_gbdt(self, model, output_path, max_trees=30):
        """
        Export LightGBM model to GBDT.java-compatible binary format.

        Binary format: [MAGIC 4B][VERSION 4B][numTrees 4B][maxDepth 4B]
        then each tree: [numNodes 4B] then for each node:
            [featureIndex 4B][threshold 4B][value 4B][leftChild 4B][rightChild 4B]
        """
        num_trees = min(model.num_trees(), max_trees)
        logger.info(f"Exporting {num_trees} trees to {output_path}")

        max_depth = 4
        tree_infos = model.dump_model()["tree_info"]
        for i in range(num_trees):
            depth = self._compute_tree_depth(tree_infos[i])
            max_depth = max(max_depth, depth)
        max_depth = min(max_depth, 10)

        with open(output_path, "wb") as f:
            f.write(b"\x47\x42\x44\x54")  # MAGIC = "GBDT"
            f.write(struct.pack(">II", 1, num_trees))  # VERSION, numTrees
            f.write(struct.pack(">I", max_depth))      # maxDepth

            for i in range(num_trees):
                self._export_tree(f, tree_infos[i])

        logger.info(f"Exported: {num_trees} trees, max_depth={max_depth}, "
                    f"{Path(output_path).stat().st_size} bytes")

    def _compute_tree_depth(self, tree_data):
        if "tree_structure" not in tree_data:
            return 0
        def _depth(node, d=0):
            if node is None: return d
            return max(_depth(node.get("left_child"), d+1),
                       _depth(node.get("right_child"), d+1))
        return _depth(tree_data["tree_structure"])

    def _export_tree(self, f, tree_info):
        tree = tree_info.get("tree_structure")
        if tree is None:
            f.write(struct.pack(">I", 1))
            f.write(struct.pack(">iffii", -1, 0.0, 0.0, -1, -1))
            return

        # Flatten tree (BFS)
        nodes, queue = [], [tree]
        index_map = {}
        while queue:
            node = queue.pop(0)
            idx = len(nodes)
            index_map[id(node)] = idx

            if "split_feature" in node:
                nodes.append({
                    "type": "internal",
                    "feature_index": node.get("split_feature_internal", 0),
                    "threshold": node.get("threshold", 0.0),
                    "value": node.get("internal_value", 0.0),
                    "left_child": node["left_child"],
                    "right_child": node["right_child"],
                })
                queue.append(node["left_child"])
                queue.append(node["right_child"])
            else:
                nodes.append({
                    "type": "leaf", "feature_index": -1,
                    "threshold": 0.0, "value": node.get("leaf_value", 0.0),
                })

        # Resolve child indices
        for i, n in enumerate(nodes):
            if n["type"] == "internal":
                n["left_idx"] = index_map.get(id(n["left_child"]), -1)
                n["right_idx"] = index_map.get(id(n["right_child"]), -1)
            else:
                n["left_idx"] = -1
                n["right_idx"] = -1

        # Write
        f.write(struct.pack(">I", len(nodes)))
        for n in nodes:
            f.write(struct.pack(">iffii",
                n["feature_index"], float(n["threshold"]),
                float(n["value"]), n["left_idx"], n["right_idx"]))

    def run(self, category, num_boost_round=500,
            early_stopping_rounds=50, min_samples=500):
        """Complete training run: load, train, export."""
        logger.info(f"{'='*60}")
        logger.info(f"Training {category.upper()} model")
        logger.info(f"{'='*60}")

        X, y, sw = self.load_data(category, min_samples=min_samples)
        if X is None:
            return {"status": "skipped", "reason": "insufficient_samples",
                    "category": category}

        result = self.train(category, X, y, sw,
                            num_boost_round=num_boost_round,
                            early_stopping_rounds=early_stopping_rounds)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        version = f"{category}_{timestamp}"
        model_path = str(self.model_dir / f"{version}.txt")
        self.export_gbdt(result["model"], model_path)

        # Update symlink
        symlink = self.model_dir / f"{category}_v1.txt"
        if symlink.exists():
            symlink.unlink()
        symlink.symlink_to(f"{version}.txt")

        self._cleanup_old_models(category)
        self._record_version(category, version, result)

        return {
            "status": "done", "category": category, "version": version,
            "model_path": model_path, "auc": result["auc"],
            "ap": result["ap"], "best_f1": result["best_f1"],
            "n_samples": result["n_train"] + result["n_test"],
            "n_pos": result["n_pos"], "n_neg": result["n_neg"],
            "num_trees": result["best_iteration"],
            "num_features": X.shape[1],
        }

    def _cleanup_old_models(self, category, keep=5):
        pattern = f"{category}_*.txt"
        files = sorted(self.model_dir.glob(pattern), key=lambda f: f.stat().st_mtime)
        for f in files[:-keep] if len(files) > keep else []:
            f.unlink()

    def _record_version(self, category, version, result):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT INTO model_versions
                    (category, version, model_path, auc, best_f1,
                     train_samples, test_samples, positive_ratio,
                     num_trees, num_features, is_active,
                     trained_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (category, version, f"{version}.txt",
                  result["auc"], result["best_f1"],
                  result["n_train"], result["n_test"],
                  result["n_pos"] / max(result["n_pos"] + result["n_neg"], 1),
                  result["best_iteration"], len(result.get("num_features", 6)),
                  int(datetime.now(timezone.utc).timestamp() * 1000)))
            conn.commit()
        except Exception as e:
            logger.warning(f"DB insert failed: {e}")
        finally:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLSHybridAC Training Pipeline")
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--category", choices=["aim", "click", "session"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--max-days", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=500)
    parser.add_argument("--rounds", type=int, default=500)
    parser.add_argument("--early-stopping", type=int, default=50)
    args = parser.parse_args()

    kwargs = {"num_boost_round": args.rounds,
              "early_stopping_rounds": args.early_stopping,
              "min_samples": args.min_samples}

    trainer = ModelTrainer(args.db, args.output, args.max_days)
    if args.all:
        for cat in ["aim", "click", "session"]:
            trainer.run(cat, **kwargs)
    elif args.category:
        trainer.run(args.category, **kwargs)
    else:
        parser.print_help()
        sys.exit(1)
```

### 6.3 Label Pipeline Code

File: cloud/training/labeler.py

```python
"""
Label Pipeline -- processes raw samples from server submission into
high-quality training labels.

Pipeline steps:
  1. Validate: schema, feature ranges, timestamp sanity
  2. Deduplicate: same player + near-identical features within 60s
  3. Weight: assign sample_weight based on label_source
  4. Hard negative mining: find samples near decision boundary
  5. Semi-supervised auto-labeling: high-confidence predictions
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger("labeler")


class LabelPipeline:
    """Processes and validates incoming training samples."""

    FEATURE_RANGES = {
        "aim": {
            "yawJerkStd": (0.0, 10.0), "pitchJerkStd": (0.0, 10.0),
            "aimSmoothness": (0.0, 1.0), "rotationEntropy": (0.0, 8.0),
            "gcdError": (0.0, 0.5), "snapFreq": (0.0, 1.0),
        },
        "click": {
            "cooldownAccuracy": (0.0, 1.0), "missRatio": (0.0, 1.0),
            "hitMissRatio": (0.0, 1.0), "criticalRatio": (0.0, 1.0),
            "perfectStreak": (0.0, 100.0),
        },
        "session": {
            "cooldownAccuracy": (0.0, 1.0), "missRatio": (0.0, 1.0),
            "mouseSensitivity": (0.0, 1.0), "pitchDeltaMean": (0.0, 10.0),
            "yawDeltaMean": (0.0, 10.0), "gcdConsistency": (0.0, 1.0),
            "rotationEntropy": (0.0, 8.0),
            "normalizedSessionDuration": (0.0, 1.0),
        },
    }

    DUPLICATE_TOLERANCE = 0.05

    def __init__(self, db_path: str):
        self.db_path = db_path

    def process_sample(self, sample: dict) -> dict:
        validation = self._validate_sample(sample)
        if not validation["valid"]:
            return {"status": "rejected", "reason": validation["reason"]}

        dup = self._check_duplicate(sample)
        if dup:
            return {"status": "duplicate", "original_id": dup}

        weight = self._compute_weight(sample)
        sample_id = self._store_sample(sample, weight)
        self._update_source_stats(sample)
        return {"status": "accepted", "sample_id": sample_id}

    def _validate_sample(self, sample: dict) -> dict:
        required = ["category", "features", "player_uuid", "timestamp"]
        for field in required:
            if field not in sample:
                return {"valid": False, "reason": f"Missing: {field}"}

        category = sample["category"]
        if category not in self.FEATURE_RANGES:
            return {"valid": False, "reason": f"Unknown category: {category}"}

        features = sample["features"]
        if not isinstance(features, list):
            return {"valid": False, "reason": "features must be array"}

        expected_n = len(self.FEATURE_RANGES[category])
        if len(features) != expected_n:
            return {"valid": False, "reason": f"Expected {expected_n} features, got {len(features)}"}

        for i, (fname, (lo, hi)) in enumerate(self.FEATURE_RANGES[category].items()):
            val = features[i]
            slack_lo = lo - (hi - lo) * 0.1
            slack_hi = hi + (hi - lo) * 0.1
            if val < slack_lo or val > slack_hi:
                return {"valid": False, "reason": f"{fname}[{i}]={val} out of range [{lo},{hi}]"}

        # Timestamp sanity
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        if sample["timestamp"] > now + 60000:
            return {"valid": False, "reason": "Future timestamp"}
        if sample["timestamp"] < now - 7 * 86400 * 1000:
            return {"valid": False, "reason": "Older than 7 days"}

        valid_sources = {"staff_ban", "staff_unban", "watchdog_bot",
                         "clean_window", "whitebox_high",
                         "vanilla_fingerprint", "semi_supervised", "unlabeled"}
        if sample.get("label_source", "unlabeled") not in valid_sources:
            return {"valid": False, "reason": "Invalid label_source"}

        return {"valid": True}

    def _check_duplicate(self, sample: dict, window_s: int = 60) -> Optional[int]:
        """Check if near-identical sample exists from same player in last 60s."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            """SELECT id, features_json FROM training_samples
               WHERE player_uuid = ? AND category = ?
                 AND created_at > (? - ? * 1000) AND is_valid = 1
               ORDER BY created_at DESC LIMIT 5""",
            (sample["player_uuid"], sample["category"],
             sample["timestamp"], window_s),
        )
        new_feats = np.array(sample["features"])
        for row in cur.fetchall():
            old = np.array(json.loads(row[1]))
            max_vals = np.maximum(np.abs(new_feats), np.abs(old))
            max_vals[max_vals < 0.001] = 1.0
            if np.all(np.abs(new_feats - old) / max_vals < self.DUPLICATE_TOLERANCE):
                conn.close()
                return row[0]
        conn.close()
        return None

    def _compute_weight(self, sample: dict) -> float:
        source_weights = {
            "staff_ban": 5.0, "staff_unban": 5.0, "watchdog_bot": 3.0,
            "clean_window": 0.5, "whitebox_high": 1.5,
            "vanilla_fingerprint": 2.0, "semi_supervised": 0.3, "unlabeled": 0.1,
        }
        weight = source_weights.get(sample.get("label_source", "unlabeled"), 1.0)

        if sample.get("ping", 0) > 300:
            weight *= 0.5
        elif sample.get("ping", 0) > 150:
            weight *= 0.8

        tps = sample.get("tps", 20.0)
        if tps < 16.0:
            weight *= 0.3
        elif tps < 18.0:
            weight *= 0.7

        return weight

    def _store_sample(self, sample: dict, weight: float) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            """INSERT INTO training_samples
               (category, features_json, label, label_source,
                server_id, player_uuid, client_version,
                ping, tps, whitebox_certainties_json,
                is_flagged, created_at, sample_weight)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sample["category"], json.dumps(sample["features"]),
             sample.get("label"), sample.get("label_source"),
             sample.get("server_id"), sample["player_uuid"],
             sample.get("client_version"), sample.get("ping"),
             sample.get("tps"),
             json.dumps(sample.get("whitebox_certainties", {})),
             1 if sample.get("is_flagged") else 0,
             sample["timestamp"], weight),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid

    def _update_source_stats(self, sample: dict) -> None:
        source = sample.get("label_source", "unlabeled")
        label = sample.get("label")
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO label_source_stats
               (source, total_count, positive_count, negative_count)
               VALUES (?, 1, ?, ?)
               ON CONFLICT(source) DO UPDATE SET
                 total_count = total_count + 1,
                 positive_count = positive_count + ?,
                 negative_count = negative_count + ?,
                 last_sample_at = ?""",
            (source,
             1 if label == 1.0 else 0, 1 if label == 0.0 else 0,
             1 if label == 1.0 else 0, 1 if label == 0.0 else 0,
             sample["timestamp"]),
        )
        conn.commit()
        conn.close()

    def mine_hard_negatives(self, model, n_samples=100, category=None) -> list:
        """Find unlabeled samples near decision boundary."""
        conn = sqlite3.connect(self.db_path)

        if category:
            cur = conn.execute(
                """SELECT id, features_json, player_uuid
                   FROM training_samples
                   WHERE label IS NULL AND is_valid = 1 AND category = ?
                   ORDER BY created_at DESC LIMIT 5000""",
                (category,),
            )
        else:
            cur = conn.execute(
                """SELECT id, features_json, player_uuid, category
                   FROM training_samples
                   WHERE label IS NULL AND is_valid = 1
                   ORDER BY created_at DESC LIMIT 5000"""
            )

        rows = cur.fetchall()
        conn.close()

        if len(rows) < n_samples:
            return []

        results = []
        for row in rows:
            sid, feat_json, puuid = row[0], row[1], row[2]
            feats = np.array(json.loads(feat_json), dtype=np.float32).reshape(1, -1)
            try:
                score = model.predict(feats)[0]
                results.append({
                    "sample_id": sid, "player_uuid": puuid,
                    "score": float(score),
                    "boundary_distance": abs(score - 0.5),
                })
            except Exception:
                continue

        results.sort(key=lambda x: x["boundary_distance"])
        top = results[:n_samples]

        conn = sqlite3.connect(self.db_path)
        for r in top:
            conn.execute(
                """INSERT OR IGNORE INTO hard_negatives
                   (sample_id, model_score, decision_boundary_distance, created_at)
                   VALUES (?, ?, ?, ?)""",
                (r["sample_id"], r["score"], r["boundary_distance"],
                 int(datetime.now(timezone.utc).timestamp() * 1000)),
            )
        conn.commit()
        conn.close()
        return top
```

## 7. Auto-training Workflow

### 7.1 Cron Schedule

```
# crontab (runs on cloud backend at 3:00 AM UTC daily)
0 3 * * * /usr/bin/python3 /opt/ac-cloud/training/auto_train.py \
    --db /opt/ac-cloud/data/training.db \
    --output /opt/ac-cloud/models/ \
    >> /var/log/ac-training.log 2>&1
```

### 7.2 Workflow Steps

```
1. Load Data (from SQLite, last 30 days)
       |
       v
2. For each category (aim, click, session):
       |
       v
   ┌─────────────────────────────────────────────────────────────┐
   │  a. Load labeled samples with weights                       │
   │  b. Stratified train/test split (80/20)                    │
   │  c. Train LightGBM with early stopping on validation AUC   │
   │  d. Evaluate: AUC, AP, F1, confusion matrix                │
   │  e. Export to GBDT.java binary format                      │
   └─────────────────────┬───────────────────────────────────────┘
                         |
                         v
   ┌─────────────────────────────────────────────────────────────┐
   │  Compare AUC vs previous active model:                     │
   │                                                             │
   │  improvement > 0.001?                                       │
   │     YES -> Update symlink, activate new version              │
   │             Run hard negative mining with new model         │
   │             Run semi-supervised labeling                    │
   │     NO  -> Keep old model, log regression warning           │
   └─────────────────────────────────────────────────────────────┘
                         |
                         v
3. Cleanup: remove old model files (keep last 5 per category)
4. Send notification via Discord/Slack webhook
5. Record all metrics in model_versions table
```

### 7.3 Auto-Train Script

File: cloud/training/auto_train.py

```python
#!/usr/bin/env python3
"""
Auto-training workflow -- called by cron daily at 3:00 AM.

Manages full workflow: training, AUC comparison, version management,
hard negative mining, semi-supervised labeling, and notification.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from train import ModelTrainer
from labeler import LabelPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler("/var/log/ac-training.log")],
)
logger = logging.getLogger("auto_train")


class AutoTrainer:
    def __init__(self, db_path: str, model_dir: str, max_days: int = 30):
        self.db_path = db_path
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.max_days = max_days
        self.trainer = ModelTrainer(db_path, str(self.model_dir), max_days)
        self.labeler = LabelPipeline(db_path)
        self.start_time = time.time()

    def run(self) -> dict:
        logger.info("=" * 60)
        logger.info("AUTO-TRAINING WORKFLOW STARTED")
        logger.info(f"DB: {self.db_path}")
        logger.info(f"Output: {self.model_dir}")
        logger.info("=" * 60)

        results = {}
        success_count = 0
        skip_count = 0
        regression_count = 0

        for category in ["aim", "click", "session"]:
            logger.info(f"\nTraining {category.upper()}...")
            result = self.trainer.run(
                category, num_boost_round=500,
                early_stopping_rounds=50, min_samples=500,
            )

            if result["status"] == "skipped":
                skip_count += 1
                results[category] = result
                continue

            comparison = self._compare_with_previous(category, result)
            result["comparison"] = comparison

            if comparison["is_better"]:
                self._activate_version(category, result["version"])
                success_count += 1
                logger.info(f"  ACTIVE: AUC {result['auc']:.4f} "
                           f"(was {comparison['previous_auc']:.4f})")

                if result["auc"] > 0.85:
                    self._run_semi_supervised(category, result)
            else:
                regression_count += 1
                logger.warning(f"  REGRESSED: AUC {result['auc']:.4f} "
                              f"<= {comparison['previous_auc']:.4f}")
                self._record_regression(category, result)

            results[category] = result

        duration = time.time() - self.start_time
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 1),
            "results": results,
            "success_count": success_count,
            "skip_count": skip_count,
            "regression_count": regression_count,
            "total": len(results),
        }

        logger.info(f"\nComplete: {success_count} ok, {skip_count} skip, "
                    f"{regression_count} regressed in {duration:.1f}s")

        self._send_notification(summary)
        return summary

    def _compare_with_previous(self, category, result):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            """SELECT id, version, auc, best_f1, num_trees, trained_at
               FROM model_versions
               WHERE category = ? AND is_active = 1
               ORDER BY trained_at DESC LIMIT 1""",
            (category,),
        )
        row = cur.fetchone()
        conn.close()

        if row is None:
            return {"previous_auc": None, "is_better": True, "reason": "first_model"}

        prev_auc = row[2]
        is_better = (result["auc"] - prev_auc) > 0.001
        return {
            "previous_id": row[0], "previous_version": row[1],
            "previous_auc": prev_auc, "new_auc": result["auc"],
            "improvement": round(result["auc"] - prev_auc, 4),
            "is_better": is_better,
            "reason": "improved" if is_better else "regressed",
        }

    def _activate_version(self, category, version):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""UPDATE model_versions SET is_active = 0
                        WHERE category = ? AND is_active = 1""", (category,))
        conn.execute("""UPDATE model_versions SET is_active = 1
                        WHERE category = ? AND version = ?""", (category, version))
        conn.commit()
        conn.close()

    def _record_regression(self, category, result):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """UPDATE model_versions SET notes = ?
               WHERE version = ?""",
            (f"REGRESSED: auc={result['auc']:.4f} (not activated)",
             result["version"]),
        )
        conn.commit()
        conn.close()

    def _run_semi_supervised(self, category, result):
        logger.info(f"  Semi-supervised labeling for {category}...")
        # Implementation per Section 6.4

    def _send_notification(self, summary):
        webhook = os.environ.get("NOTIFICATION_WEBHOOK_URL")
        if not webhook:
            return

        lines = [
            "**Auto-Training Report**",
            f"Duration: {summary['duration_seconds']:.1f}s",
            f"OK: {summary['success_count']} | Skip: {summary['skip_count']} | "
            f"Regressed: {summary['regression_count']}",
            "",
        ]
        for cat in ["aim", "click", "session"]:
            r = summary["results"].get(cat, {})
            if r.get("status") == "done":
                c = r.get("comparison", {})
                prev = c.get("previous_auc")
                p = f" (was {prev:.4f})" if prev else " (first)"
                lines.append(f"**{cat.upper()}**: AUC={r['auc']:.4f}{p} | "
                            f"F1={r['best_f1']:.4f} | {r['n_samples']} samples")
            else:
                lines.append(f"**{cat.upper()}**: SKIPPED ({r.get('reason', '')})")

        import urllib.request
        payload = json.dumps({"content": "\n".join(lines), "username": "AC-Trainer"}).encode()
        req = urllib.request.Request(webhook, data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-days", type=int, default=30)
    args = parser.parse_args()

    trainer = AutoTrainer(args.db, args.output, args.max_days)
    summary = trainer.run()
    if summary["success_count"] == 0 and summary["skip_count"] < summary["total"]:
        sys.exit(1)
```

## 8. Model Versioning

### 8.1 Directory Structure

```
models/
  aim_v1.txt              -> symlink to aim_20260701_030000.txt
  aim_20260701_030000.txt  (AUC 0.93, current)
  aim_20260630_030000.txt  (AUC 0.91, kept)
  aim_20260629_030000.txt  (AUC 0.89, kept)
  aim_20260628_030000.txt  (AUC 0.88, kept)
  aim_20260627_030000.txt  (AUC 0.87, kept)

  click_v1.txt            -> symlink to click_20260630_030000.txt
  click_20260701_030000.txt (AUC 0.91, regressed, not active)
  click_20260630_030000.txt (AUC 0.92, current)
  click_20260629_030000.txt (AUC 0.90, kept)
  click_20260628_030000.txt (AUC 0.88, kept)
  click_20260627_030000.txt (AUC 0.85, kept)
  click_20260626_030000.txt (AUC 0.82, kept)

  session_v1.txt          -> symlink to session_20260630_030000.txt
  session_20260701_030000.txt (AUC 0.97, current)
  session_20260630_030000.txt (AUC 0.96, kept)
  session_20260629_030000.txt (AUC 0.95, kept)
  session_20260628_030000.txt (AUC 0.93, kept)
  session_20260627_030000.txt (AUC 0.91, kept)
```

### 8.2 Symlink Strategy

The _v1.txt symlink always points to the current best model. The Minecraft server downloads only the symlink target.

```python
# Update symlink (from ModelTrainer.run())
symlink = model_dir / f"{category}_v1.txt"
if symlink.exists() or symlink.is_symlink():
    symlink.unlink()
symlink.symlink_to(f"{version}.txt")  # relative symlink
```

### 8.3 Cleanup Policy

- Keep last 5 model versions per category (configurable)
- Remove older ones after each training run
- Exceptions:
  - If the latest model regressed, keep both old (active) and new (regressed)
  - Never delete the currently active model

### 8.4 Model Distribution

The cloud backend serves models via:

1. **Direct download**: GET /v1/models/{category}/latest
2. **Server pull**: wget/HTTP GET on startup
3. **Manual rollback**: POST /v1/models/{category}/activate?version={version}

```
# Server startup model download
for category in aim click session; do
    wget -q -O /plugins/GrimAC/ml-data/models/${category}_v1.txt \
        https://cloud.ac-server.com/v1/models/${category}/latest
done
```

## 9. Java Integration: Server-Side Label Submission

### 9.1 LabelSubmitter (New File)

File: Grim/common/src/main/java/ac/grim/grimac/manager/ml/LabelSubmitter.java

```java
package ac.grim.grimac.manager.ml;

import ac.grim.grimac.GrimAPI;
import ac.grim.grimac.manager.FusionEngine;
import ac.grim.grimac.manager.player.features.FeatureBridge;
import ac.grim.grimac.manager.player.features.FeatureVector;
import ac.grim.grimac.player.GrimPlayer;
import com.google.gson.Gson;
import com.google.gson.annotations.SerializedName;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * LabelSubmitter -- batched submission of labeled training samples
 * to the cloud training API.
 *
 * Collects feature snapshots from FeatureBridge and submits them
 * (with labels when available) to the cloud backend.
 * This is ADDITIVE to the existing DataCollector (CSV logging).
 */
public class LabelSubmitter {

    private static final int BATCH_MAX_SIZE = 100;
    private static final long FLUSH_INTERVAL_MS = 60_000L;
    private static final long NEGATIVE_COOLDOWN_MS = 600_000L;
    private static final long GRACE_PERIOD_MS = 300_000L;
    private static final long CLEAN_WINDOW_MS = 3_600_000L;

    private final HttpClient http;
    private final Gson gson;
    private final String baseUrl;
    private final String apiKey;
    private final boolean enabled;
    private final String serverId;

    private final ConcurrentLinkedQueue<Sample> buffer = new ConcurrentLinkedQueue<>();
    private final AtomicInteger bufferSize = new AtomicInteger(0);
    private final ConcurrentHashMap<UUID, Long> lastNegativeSample = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<UUID, Long> playerLastFlagTime = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<UUID, Long> playerJoinTime = new ConcurrentHashMap<>();
    private ScheduledExecutorService scheduler;

    public LabelSubmitter() {
        var config = GrimAPI.INSTANCE.getConfigManager().getConfig();
        this.enabled = config.getBooleanElse("ML.cloud-submission-enabled", false);
        this.baseUrl = config.getStringElse("ML.cloud-url", "");
        this.apiKey = config.getStringElse("ML.cloud-api-key", "");
        this.serverId = config.getStringElse("ML.server-id", UUID.randomUUID().toString());

        this.gson = new Gson();
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(1000))
                .build();

        if (enabled && !baseUrl.isEmpty()) {
            this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "ML-LabelSubmitter");
                t.setDaemon(true);
                return t;
            });
            this.scheduler.scheduleAtFixedRate(
                    this::flush, FLUSH_INTERVAL_MS, FLUSH_INTERVAL_MS, TimeUnit.MILLISECONDS);
        }
    }

    /**
     * Submit a labeled sample (staff ban, watchdog bot, etc.).
     */
    public void submitLabeled(GrimPlayer player, float[] features,
                              float label, String labelSource, String category) {
        if (!enabled || features == null) return;

        FeatureBridge fb = player.getFeatureBridge();
        Sample sample = new Sample(
                category, features, label, labelSource,
                player.uuid.toString(),
                player.getClientVersion().toString(),
                player.getTransactionPing(),
                (float) getCurrentTps(),
                System.currentTimeMillis(),
                buildWhiteboxCertainties(player),
                true
        );

        buffer.offer(sample);
        if (bufferSize.incrementAndGet() >= BATCH_MAX_SIZE) {
            flush();
        }
    }

    /**
     * Submit a negative sample from a clean play window.
     */
    public void submitCleanWindow(GrimPlayer player, String category) {
        if (!enabled) return;
        UUID uuid = player.uuid;

        Long lastNeg = lastNegativeSample.get(uuid);
        long now = System.currentTimeMillis();
        if (lastNeg != null && now - lastNeg < NEGATIVE_COOLDOWN_MS) return;
        lastNegativeSample.put(uuid, now);

        Long joinTime = playerJoinTime.get(uuid);
        if (joinTime != null && now - joinTime < GRACE_PERIOD_MS) return;

        MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();
        if (ml == null) return;

        float[] features = null;
        switch (category) {
            case "aim": features = ml.extractAimFeatures(player.getFeatureBridge()); break;
            case "click": features = ml.extractClickFeatures(player.getFeatureBridge()); break;
            case "session": features = ml.extractSessionFeatures(player.getFeatureBridge()); break;
        }
        if (features == null) return;

        Sample sample = new Sample(
                category, features, 0.0f, "clean_window",
                player.uuid.toString(),
                player.getClientVersion().toString(),
                player.getTransactionPing(),
                (float) getCurrentTps(),
                System.currentTimeMillis(),
                buildWhiteboxCertainties(player),
                false
        );

        buffer.offer(sample);
        bufferSize.incrementAndGet();
    }

    public void onPlayerJoin(GrimPlayer player) {
        playerJoinTime.put(player.uuid, System.currentTimeMillis());
    }

    public void onPlayerFlag(GrimPlayer player) {
        playerLastFlagTime.put(player.uuid, System.currentTimeMillis());
    }

    public boolean isInCleanWindow(GrimPlayer player) {
        long now = System.currentTimeMillis();
        Long lastFlag = playerLastFlagTime.get(player.uuid);
        if (lastFlag != null && now - lastFlag < CLEAN_WINDOW_MS) return false;
        Long joinTime = playerJoinTime.get(player.uuid);
        return joinTime != null && now - joinTime >= GRACE_PERIOD_MS;
    }

    private void flush() {
        if (buffer.isEmpty()) return;
        List<Sample> batch = new ArrayList<>(BATCH_MAX_SIZE);
        Sample s;
        while ((s = buffer.poll()) != null && batch.size() < BATCH_MAX_SIZE) {
            batch.add(s);
        }
        bufferSize.addAndGet(-batch.size());
        if (batch.isEmpty()) return;

        String json = gson.toJson(Map.of("samples", batch, "server_id", serverId));
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/v1/samples/batch"))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + apiKey)
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .timeout(Duration.ofMillis(1000))
                    .build();

            http.sendAsync(req, HttpResponse.BodyHandlers.ofString())
                    .thenAccept(resp -> { /* non-blocking, errors ignored */ });
        } catch (Exception ignored) { }
    }

    private Map<String, Double> buildWhiteboxCertainties(GrimPlayer player) {
        Map<String, Double> map = new HashMap<>();
        FusionEngine fusion = player.getFusionEngine();
        if (fusion != null) {
            map.put("movement", fusion.getBlackboxRisk(FusionEngine.Category.MOVEMENT));
            map.put("combat", fusion.getBlackboxRisk(FusionEngine.Category.COMBAT_AIM));
            map.put("packet", fusion.getBlackboxRisk(FusionEngine.Category.PACKET));
        }
        return map;
    }

    private double getCurrentTps() {
        try { return GrimAPI.INSTANCE.getPlatformServer().getTPS(); }
        catch (Exception e) { return 20.0; }
    }

    public void shutdown() {
        flush();
        if (scheduler != null) scheduler.shutdown();
    }

    // -- Sample record (matches JSON schema in Section 2.1) --

    public static class Sample {
        public final String category;
        public final float[] features;
        public final Float label;
        @SerializedName("label_source")
        public final String labelSource;
        @SerializedName("player_uuid")
        public final String playerUuid;
        @SerializedName("client_version")
        public final String clientVersion;
        public final int ping;
        public final float tps;
        public final long timestamp;
        @SerializedName("whitebox_certainties")
        public final Map<String, Double> whiteboxCertainties;
        @SerializedName("is_flagged")
        public final boolean isFlagged;

        public Sample(String category, float[] features, Float label,
                      String labelSource, String playerUuid, String clientVersion,
                      int ping, float tps, long timestamp,
                      Map<String, Double> whiteboxCertainties, boolean isFlagged) {
            this.category = category;
            this.features = features;
            this.label = label;
            this.labelSource = labelSource;
            this.playerUuid = playerUuid;
            this.clientVersion = clientVersion;
            this.ping = ping;
            this.tps = tps;
            this.timestamp = timestamp;
            this.whiteboxCertainties = whiteboxCertainties;
            this.isFlagged = isFlagged;
        }
    }
}
```

### 9.2 Integration Points

#### In DataCollector.java (add clean window check):

```java
// After collecting tick data, check for clean window negative
LabelSubmitter submitter = GrimAPI.INSTANCE.getLabelSubmitter();
if (submitter != null && submitter.isInCleanWindow(player)) {
    // ~0.17% chance per tick ~= 1 sample per 10 minutes per category
    if (ThreadLocalRandom.current().nextInt(600) == 0) {
        submitter.submitCleanWindow(player, "aim");
    }
    if (ThreadLocalRandom.current().nextInt(600) == 0) {
        submitter.submitCleanWindow(player, "click");
    }
    if (ThreadLocalRandom.current().nextInt(1200) == 0) {
        submitter.submitCleanWindow(player, "session");
    }
}
```

#### In PunishmentManager (staff ban/unban):

```java
// When staff bans a player:
LabelSubmitter submitter = GrimAPI.INSTANCE.getLabelSubmitter();
if (submitter != null && player != null) {
    MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();
    submitter.submitLabeled(player, ml.extractAimFeatures(fb), 1.0f, "staff_ban", "aim");
    submitter.submitLabeled(player, ml.extractClickFeatures(fb), 1.0f, "staff_ban", "click");

    fusion.onFlag(FusionEngine.Category.COMBAT_AIM);
}

// When staff unbans (false positive correction):
submitter.submitLabeled(player, ml.extractAimFeatures(fb), 0.0f, "staff_unban", "aim");
```

### 9.3 Configuration (config.yml)

```yaml
ML:
  cloud-submission-enabled: false
  cloud-url: "https://ac-cloud.myserver.com"
  cloud-api-key: "sk-..."
  server-id: "auto"

  # Existing settings (unchanged)
  data-collector-dir: "plugins/MLSHybridAC/data/"
  data-dir: "plugins/GrimAC/ml-data/"
  auto-save-interval-minutes: 5
  max-training-samples: 10000
```

## 10. Evaluation and Monitoring

### 10.1 Metrics Dashboard

After each training run, log the following:

```json
{
  "category": "aim",
  "version": "aim_20260701_030000",
  "timestamp": "2026-07-01T03:00:00Z",
  "duration_seconds": 142.3,
  "data": {
    "train_samples": 8450,
    "test_samples": 2113,
    "positive_ratio": 0.023,
    "source_breakdown": {
      "staff_ban": { "total": 45, "pos": 45, "neg": 0 },
      "watchdog_bot": { "total": 230, "pos": 230, "neg": 0 },
      "clean_window": { "total": 6200, "pos": 0, "neg": 6200 },
      "vanilla_fingerprint": { "total": 1800, "pos": 0, "neg": 1800 },
      "whitebox_high": { "total": 120, "pos": 120, "neg": 0 },
      "semi_supervised": { "total": 168, "pos": 132, "neg": 36 }
    }
  },
  "metrics": {
    "auc": 0.9321,
    "average_precision": 0.4512,
    "best_f1": 0.387,
    "best_threshold": 0.42
  },
  "comparison": {
    "previous_auc": 0.9150,
    "improvement": 0.0171,
    "is_better": true
  },
  "model": {
    "num_trees": 127,
    "num_features": 6,
    "max_depth": 6,
    "file_size_bytes": 14250
  }
}
```

### 10.2 Alert Conditions

| Condition | Severity | Action |
|-----------|----------|--------|
| AUC < 0.70 | CRITICAL | Stop training, rollback, notify admin |
| AUC regression > 0.05 | WARNING | Flag for review, keep previous model |
| Insufficient samples (< 500) | INFO | Skip category |
| Training duration > 30 min | WARNING | Check data volume or resource contention |
| No training for 7+ days | INFO | Check cron and DB health |

### 10.3 CLI Monitor

File: cloud/training/monitor.py

```python
#!/usr/bin/env python3
"""Monitor training health and performance."""
import sqlite3, sys
from datetime import datetime, timezone


def print_summary(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print(f"TRAINING PIPELINE MONITOR -- {datetime.now().isoformat()}")
    print()

    # Last training per category
    print("Last Training Run:")
    for cat in ["aim", "click", "session"]:
        c.execute("""SELECT version, auc, best_f1, train_samples,
                            test_samples, trained_at, is_active
                     FROM model_versions WHERE category = ?
                     ORDER BY trained_at DESC LIMIT 1""", (cat,))
        row = c.fetchone()
        if row:
            ts = datetime.fromtimestamp(row[5] / 1000, tz=timezone.utc)
            active = " [ACTIVE]" if row[6] else ""
            print(f"  {cat:8s}: AUC={row[1]:.4f} F1={row[2]:.4f} "
                  f"samples={row[3]+row[4]} {ts.isoformat()}{active}")
        else:
            print(f"  {cat:8s}: no training data")

    print()
    print("Label Source Distribution (last 30 days):")
    c.execute("""SELECT label_source, COUNT(*),
                        SUM(CASE WHEN label = 1.0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN label = 0.0 THEN 1 ELSE 0 END)
                 FROM training_samples
                 WHERE created_at > (strftime('%%s', 'now') - 30*86400) * 1000
                 GROUP BY label_source ORDER BY COUNT(*) DESC""")
    for src, total, pos, neg in c.fetchall():
        print(f"  {src:25s}: {total:>6} total ({pos:>5} pos, {neg:>5} neg)")

    print()
    c.execute("SELECT COUNT(*) FROM hard_negatives WHERE reviewed = 0")
    print(f"Hard negatives unreviewed: {c.fetchone()[0]}")
    conn.close()


def print_alerts(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Low AUC models
    c.execute("""SELECT category, version, auc FROM model_versions
                 WHERE auc < 0.70 AND is_active = 1 ORDER BY trained_at DESC""")
    found = False
    for cat, ver, auc in c.fetchall():
        found = True
        print(f"  [CRITICAL] {cat}.{ver}: AUC={auc:.4f} < 0.70")

    # Regressions
    c.execute("""SELECT v1.category, v1.version, v1.auc, v2.auc
                 FROM model_versions v1
                 JOIN model_versions v2 ON v2.id = (
                     SELECT id FROM model_versions
                     WHERE category = v1.category AND id < v1.id
                     ORDER BY trained_at DESC LIMIT 1)
                 WHERE v1.auc < v2.auc - 0.05 LIMIT 10""")
    for cat, ver, auc, prev in c.fetchall():
        found = True
        print(f"  [WARNING] {cat}.{ver}: regressed {prev:.4f} -> {auc:.4f}")

    if not found:
        print("  No active alerts")
    conn.close()


if __name__ == "__main__":
    mode, db = "summary", None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--db": db = sys.argv[i + 2]
        elif arg == "--alerts": mode = "alerts"

    if not db:
        print("--db required"); sys.exit(1)
    print_alerts(db) if mode == "alerts" else print_summary(db)
```

## 11. Deployment Guide

### 11.1 Cloud Backend Setup

```bash
# 1. Create directories
mkdir -p /opt/ac-cloud/{training,models,data,logs}

# 2. Install Python dependencies
pip install lightgbm numpy pandas scikit-learn

# 3. Initialize database
python -c "
import sqlite3
conn = sqlite3.connect('/opt/ac-cloud/data/training.db')
conn.executescript('''
    CREATE TABLE training_samples (id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL, features_json TEXT NOT NULL, label REAL,
        label_source TEXT, server_id TEXT, player_uuid TEXT NOT NULL,
        client_version TEXT, ping INTEGER, tps REAL,
        whitebox_certainties_json TEXT, is_flagged INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL, sample_weight REAL DEFAULT 1.0,
        is_valid INTEGER DEFAULT 1, duplicate_of_id INTEGER);
    CREATE TABLE model_versions (id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL, version TEXT NOT NULL, model_path TEXT NOT NULL,
        auc REAL, best_f1 REAL, train_samples INTEGER, test_samples INTEGER,
        positive_ratio REAL, num_trees INTEGER, num_features INTEGER,
        hyperparams_json TEXT, is_active INTEGER DEFAULT 0,
        trained_at INTEGER NOT NULL, training_duration_seconds REAL, notes TEXT);
    CREATE TABLE hard_negatives (id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id INTEGER NOT NULL, model_score REAL NOT NULL,
        decision_boundary_distance REAL, reviewed INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL);
    CREATE TABLE label_source_stats (source TEXT PRIMARY KEY,
        total_count INTEGER DEFAULT 0, positive_count INTEGER DEFAULT 0,
        negative_count INTEGER DEFAULT 0, last_sample_at INTEGER);
''')
conn.commit()
conn.close()
"

# 4. Set up cron
echo "0 3 * * * /usr/bin/python3 /opt/ac-cloud/training/auto_train.py \
    --db /opt/ac-cloud/data/training.db \
    --output /opt/ac-cloud/models/ \
    >> /opt/ac-cloud/logs/training.log 2>&1" | crontab -

# 5. Configure notification webhook
export NOTIFICATION_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

### 11.2 Server Integration Checklist

- [ ] Add LabelSubmitter.java to the project
- [ ] Add cloud-submission-enabled config options
- [ ] Wire LabelSubmitter into PunishmentManager (staff ban/unban)
- [ ] Wire LabelSubmitter into DataCollector (clean window detection)
- [ ] Create cloud backend directory structure
- [ ] Set up SQLite database with schema
- [ ] Deploy train.py, labeler.py, auto_train.py to cloud
- [ ] Set up cron job for daily training
- [ ] Configure model download on server startup
- [ ] Test end-to-end: server -> cloud API -> training -> model download

### 11.3 Rollout Strategy

**Phase 1 (Weeks 1-2)**: Deploy LabelSubmitter in shadow mode (enabled=false). Collect to CSV only. Deploy cloud backend, accept samples, validate pipeline.

**Phase 2 (Weeks 3-4)**: Enable cloud submission on 1 production server. Begin accumulating labeled samples in DB.

**Phase 3 (Week 5)**: Enable daily training. Train models but DO NOT push to servers. Evaluate AUC daily for 1 week vs existing sklearn GBDT.

**Phase 4 (Week 6)**: If cloud models consistently outperform existing (AUC improvement > 0.02), push to production. Enable model download on server startup.

**Phase 5 (Ongoing)**: Monitor metrics, review hard negatives, tune hyperparameters.

## 12. Appendices

### A. Comparison: Current sklearn GBDT vs LightGBM

| Aspect | sklearn GBDT (current) | LightGBM (target) |
|--------|----------------------|-------------------|
| Training time (10k samples, 6 features) | ~45s | ~5s |
| AUC (typical) | 0.85-0.90 | 0.90-0.95 |
| Max trees | 30 (hardcoded) | 500 with early stopping |
| Tree growth | Depth-wise (level) | Leaf-wise (best-first) |
| Missing values | Not supported | Native |
| Sample weights | Not used | Built-in weight param |
| Categorical features | Manual encoding | Native |
| GPU support | No | Yes |
| File format | Custom binary | Same (backward compatible) |

### B. Feature Range Validation Reference

```
Aim Features:
  yawJerkStd:      [0.0, 10.0]   human: 0.5-3.0,   bot: 0.01-0.4
  pitchJerkStd:    [0.0, 10.0]   human: 0.5-3.0,   bot: 0.01-0.4
  aimSmoothness:   [0.0, 1.0]    human: 0.3-0.75,  bot: 0.85-1.0
  rotationEntropy: [0.0, 8.0]    human: 5-7 bits,  bot: 2-4 bits
  gcdError:        [0.0, 0.5]    bot near 0,       human: 0.1-0.5
  snapFreq:        [0.0, 1.0]    human: 0.05-0.15, bot: > 0.2

Click Features:
  cooldownAccuracy: [0.0, 0.98]  human: 0.5-0.85,  bot: > 0.95
  missRatio:        [0.0, 1.0]   human: 0.5-0.7,   bot: < 0.1
  hitMissRatio:     [0.0, 1.0]   human: 0.6-0.8,   bot: > 0.95
  criticalRatio:    [0.0, 1.0]   human: 0.3-0.6,   bot: > 0.8
  perfectStreak:    [0.0, +inf)  human: 5-8,       bot: 20+

Session Features:
  cooldownAccuracy: [0.0, 0.98]  same as click
  missRatio:        [0.0, 1.0]   same as click
  mouseSensitivity: [0.0, 1.0]   varies by player
  pitchDeltaMean:   [0.0, +inf)  varies by activity
  yawDeltaMean:     [0.0, +inf)  varies by activity
  gcdConsistency:   [0.0, 1.0]   high = suspicious
  rotationEntropy:  [0.0, 8.0]   same as aim
  sessionDuration:  [0.0, 1.0]   normalized to 1 hour
```

### C. LightGBM Hyperparameter Tuning Guide

```python
param_grid = {
    "num_leaves": [15, 31, 63, 127],
    "max_depth": [4, 6, 8, -1],
    "learning_rate": [0.01, 0.05, 0.1],
    "feature_fraction": [0.6, 0.8, 1.0],
    "bagging_fraction": [0.6, 0.8, 1.0],
    "min_data_in_leaf": [10, 20, 50, 100],
    "lambda_l1": [0.0, 0.1, 1.0],
    "lambda_l2": [0.0, 0.1, 1.0],
}
```

Strategy:
1. Start with defaults (Section 6.2)
2. After 2 weeks of data, use optuna/grid search with 3-fold CV
3. Tune per-category separately
4. Re-tune every 3 months as cheat patterns evolve

### D. Glossary

| Term | Definition |
|------|------------|
| GBDT | Gradient Boosted Decision Tree -- ensemble of shallow decision trees |
| LightGBM | Microsoft gradient boosting with leaf-wise tree growth |
| AUC | Area Under ROC Curve -- classification performance |
| F1 | Harmonic mean of precision and recall |
| EWMA | Exponentially Weighted Moving Average |
| Hard Negative | Sample near decision boundary model misclassifies |
| Semi-supervised | Training using both labeled and unlabeled data |
| Positive/Negative | Cheating / Legitimate in anticheat context |
| Whitebox | Deterministic check evidence (Grim check certainty) |
| Blackbox | ML model risk score |
| EWMA | Exponentially Weighted Moving Average |


> **End of Document**


