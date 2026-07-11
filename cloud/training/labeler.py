"""
Label Pipeline — labeling strategy for training samples.
========================================================
Label sources weighted by reliability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LabelSource:
    name: str
    weight: float          # Label weight (0-1)
    reliability: str       # Rating
    description: str


LABEL_SOURCES = {
    "staff_ban": LabelSource(
        name="staff_ban", weight=1.0, reliability="★★★★★",
        description="Staff confirmed ban — gold standard positive",
    ),
    "staff_unban": LabelSource(
        name="staff_unban", weight=0.0, reliability="★★★★★",
        description="Staff confirmed false positive — gold standard negative",
    ),
    "watchdog_bot": LabelSource(
        name="watchdog_bot", weight=0.95, reliability="★★★★☆",
        description="Watchdog bot confirmed cheating",
    ),
    "clean_window": LabelSource(
        name="clean_window", weight=0.05, reliability="★★★☆☆",
        description="1 hour clean play after 100+ check passes",
    ),
    "whitebox_high": LabelSource(
        name="whitebox_high", weight=0.85, reliability="★★★☆☆",
        description="Whitebox certainty > 0.95 (movement/packet cheats)",
    ),
    "vanilla_fingerprint": LabelSource(
        name="vanilla_fingerprint", weight=0.02, reliability="★★★★☆",
        description="Known vanilla client (via ClientBrand check)",
    ),
    "semi_supervised": LabelSource(
        name="semi_supervised", weight=0.3, reliability="★★☆☆☆",
        description="Model confidence > 0.95 (needs review)",
    ),
    "unlabeled": LabelSource(
        name="unlabeled", weight=None, reliability="☆☆☆☆☆",
        description="No label — used for unsupervised pre-training",
    ),
}


def get_label_weight(source: str) -> float | None:
    """Get label weight for a source. Returns None for unlabeled."""
    src = LABEL_SOURCES.get(source)
    return src.weight if src else None


def is_high_confidence(source: str) -> bool:
    """Check if label source is high confidence (> 0.8)."""
    weight = get_label_weight(source)
    return weight is not None and weight >= 0.8


def get_training_weight(source: str, base_label: float) -> float:
    """Get effective training weight for a sample.

    For positive samples: higher weight for reliable sources.
    For negative samples: lower weight to avoid over-penalizing.
    """
    src = LABEL_SOURCES.get(source)
    if not src or src.weight is None:
        return 0.0
    if base_label >= 0.5:
        return src.weight
    else:
        return src.weight * 0.5  # Negative samples get half weight
