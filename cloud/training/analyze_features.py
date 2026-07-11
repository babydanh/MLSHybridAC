"""
Feature Importance Analysis — LightGBM feature analysis for anticheat ML.
=========================================================================
"""

from __future__ import annotations

import json
import logging

import lightgbm as lgb
import numpy as np

logger = logging.getLogger(__name__)


def analyze_model(model_path: str, feature_names: list[str]) -> dict:
    """Analyze trained LightGBM model and return feature importance."""
    model = lgb.Booster(model_file=model_path)

    # Gain importance (how much each feature contributed to splits)
    gain = model.feature_importance(importance_type="gain")
    total_gain = gain.sum()

    # Split importance (how many times each feature was used)
    split = model.feature_importance(importance_type="split")
    total_split = split.sum()

    results = []
    for i, name in enumerate(feature_names):
        results.append({
            "feature": name,
            "gain_pct": float(gain[i] / total_gain * 100) if total_gain > 0 else 0,
            "split_count": int(split[i]),
            "split_pct": float(split[i] / total_split * 100) if total_split > 0 else 0,
        })

    results.sort(key=lambda x: x["gain_pct"], reverse=True)

    return {
        "model_path": model_path,
        "trees": model.num_trees(),
        "features": model.num_feature(),
        "importance": results,
    }


def print_importance(results: dict) -> None:
    """Print feature importance table."""
    print(f"\nModel: {results['model_path']}")
    print(f"Trees: {results['trees']}, Features: {results['features']}")
    print(f"{'Feature':30s} {'Gain%':8s} {'Splits':8s} {'Split%':8s}")
    print("-" * 54)
    for r in results["importance"]:
        print(f"{r['feature']:30s} {r['gain_pct']:7.1f}% {r['split_count']:8d} {r['split_pct']:7.1f}%")


def suggest_feature_removal(results: dict, min_gain_pct: float = 1.0) -> list[str]:
    """Suggest features for removal (gain < threshold)."""
    return [
        r["feature"]
        for r in results["importance"]
        if r["gain_pct"] < min_gain_pct
    ]
