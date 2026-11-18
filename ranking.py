"""
ranking.py – Scores and ranks ProgramRecord objects.

Scoring is entirely based on publicly available metrics.
A higher score indicates a more attractive program based on the
configured criteria (low report volume + responsive program).

DISCLAIMER: A low ranking score does NOT guarantee low competition or
better bounty outcomes. Use rankings as a starting point only.
"""

from __future__ import annotations

import math
from typing import List, Optional

import config
from logger import get_logger
from program_parser import ProgramRecord

log = get_logger("ranking")

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_MAX_RESPONSE_HOURS = 7 * 24.0   # 7 days – anything above gets score 0
_MAX_TRIAGE_HOURS   = 14 * 24.0  # 14 days
_MAX_RESOLUTION_HOURS = 90 * 24.0  # 90 days


def _normalise_hours(hours: Optional[float], max_h: float) -> float:
    """
    Map response time (hours) → [0, 1] where 1 = fastest.
    Returns 0.5 when the value is unknown (neutral mid-point).
    """
    if hours is None:
        return 0.5
    if hours <= 0:
        return 1.0
    return max(0.0, 1.0 - (hours / max_h))


def _normalise_reports(count: Optional[int], max_r: int = 39) -> float:
    """
    Map report count → [0, 1] where 1 = fewest reports (most desirable).
    Returns 0.5 when the count is unknown.
    """
    if count is None:
        return 0.5
    if count <= 0:
        return 1.0
    return max(0.0, 1.0 - (count / (max_r + 1)))


def _normalise_efficiency(pct: Optional[float]) -> float:
    """Map response efficiency percentage → [0, 1]. Unknown → 0.5."""
    if pct is None:
        return 0.5
    return max(0.0, min(1.0, pct / 100.0))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_record(record: ProgramRecord) -> float:
    """
    Compute a public-metrics opportunity score in [0, 100].

    Unknown values use a neutral midpoint so records remain rankable. Always
    read the separate Data Confidence column alongside this score; a low
    confidence record should not be compared as if all metrics were verified.
    This is not a probability of finding a vulnerability or earning a bounty.
    """
    w = config.RANKING_WEIGHTS

    volume_score      = _normalise_reports(record.reports_received_90d)
    response_score    = _normalise_hours(record.avg_first_response_h, _MAX_RESPONSE_HOURS)
    triage_score      = _normalise_hours(record.avg_triage_h, _MAX_TRIAGE_HOURS)
    resolution_score  = _normalise_hours(record.avg_resolution_h, _MAX_RESOLUTION_HOURS)
    efficiency_score  = _normalise_efficiency(record.response_efficiency_pct)
    bounty_score      = 1.0 if record.offers_bounties else 0.0
    scope_score       = 1.0 if record.scope_policy_url and record.scope_policy_url != "Unknown" else 0.0

    composite = (
        w["report_volume"]         * volume_score
        + w["response_time"]       * response_score
        + w["triage_time"]         * triage_score
        + w["resolution_time"]     * resolution_score
        + w["response_efficiency"] * efficiency_score
        + w["bounty_availability"] * bounty_score
        + w.get("scope_documented", 0.0) * scope_score
    )

    return round(composite * 100, 2)


def rank_programs(records: List[ProgramRecord]) -> List[ProgramRecord]:
    """
    Assign a ranking_score to each record and return them sorted
    highest-score first.
    """
    for record in records:
        record.ranking_score = score_record(record)

    ranked = sorted(records, key=lambda r: r.ranking_score, reverse=True)

    log.info(
        "Ranked %d programs. Top: '%s' (%.2f) | Bottom: '%s' (%.2f)",
        len(ranked),
        ranked[0].name if ranked else "-",
        ranked[0].ranking_score if ranked else 0,
        ranked[-1].name if ranked else "-",
        ranked[-1].ranking_score if ranked else 0,
    )
    return ranked


def data_confidence(record: ProgramRecord) -> str:
    """Return a simple transparency label based on available public metrics."""
    checks = (
        record.reports_received_90d is not None,
        record.avg_first_response_h is not None,
        record.avg_triage_h is not None,
        record.avg_resolution_h is not None,
        record.response_efficiency_pct is not None,
    )
    ratio = sum(checks) / len(checks)
    if ratio >= 0.8:
        return "High"
    if ratio >= 0.4:
        return "Medium"
    return "Low"
