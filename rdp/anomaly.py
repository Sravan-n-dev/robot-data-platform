"""Data-quality checks on per-topic timestamp series. Pure functions, no I/O."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_MESSAGES = 5          # need a few samples before a nominal period is meaningful
DROP_FACTOR = 1.8         # gap > 1.8x median period => at least one message dropped
DROPOUT_FACTOR = 10.0     # gap > 10x median period => sensor considered stopped
DROPOUT_MIN_SECONDS = 0.5


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str
    start_ns: int
    end_ns: int
    detail: str


def detect_gaps(stamps_ns: np.ndarray) -> list[Finding]:
    """Find message drops and sensor dropouts from log-time gaps.

    The nominal period is the median inter-message interval, which stays robust
    even when a few large gaps exist.
    """
    if stamps_ns.size < MIN_MESSAGES:
        return []
    diffs = np.diff(stamps_ns)
    positive = diffs[diffs > 0]
    if positive.size == 0:
        return []
    period = float(np.median(positive))
    findings: list[Finding] = []
    for i in np.flatnonzero(diffs > DROP_FACTOR * period):
        gap = float(diffs[i])
        ratio = gap / period
        start, end = int(stamps_ns[i]), int(stamps_ns[i + 1])
        if ratio >= DROPOUT_FACTOR and gap / 1e9 >= DROPOUT_MIN_SECONDS:
            findings.append(Finding(
                "sensor_dropout", "critical", start, end,
                f"no data for {gap / 1e9:.2f}s (nominal period {period / 1e9:.3f}s)"))
        else:
            missed = max(int(round(ratio)) - 1, 1)
            findings.append(Finding(
                "message_drop", "warning", start, end,
                f"about {missed} message(s) missing; gap {gap / 1e9:.3f}s"))
    return findings


def detect_timestamp_issues(header_ns: np.ndarray) -> list[Finding]:
    """Find duplicated or backwards-moving header timestamps."""
    if header_ns.size < 2:
        return []
    diffs = np.diff(header_ns)
    findings: list[Finding] = []
    for i in np.flatnonzero(diffs < 0):
        findings.append(Finding(
            "timestamp_regression", "critical", int(header_ns[i + 1]), int(header_ns[i]),
            f"header stamp moved backwards by {-diffs[i] / 1e9:.3f}s"))
    duplicates = int(np.count_nonzero(diffs == 0))
    if duplicates:
        findings.append(Finding(
            "timestamp_duplicate", "warning", int(header_ns[0]), int(header_ns[-1]),
            f"{duplicates} message(s) repeated the previous header stamp"))
    return findings


def detect_invalid(stamps_ns: np.ndarray, valid_mask: np.ndarray) -> list[Finding]:
    """Summarise messages whose required numeric fields were NaN or infinite."""
    bad = np.flatnonzero(~valid_mask)
    if bad.size == 0:
        return []
    return [Finding(
        "invalid_values", "warning", int(stamps_ns[bad[0]]), int(stamps_ns[bad[-1]]),
        f"{bad.size} message(s) contained NaN/inf in required fields")]
