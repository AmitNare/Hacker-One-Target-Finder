"""
program_parser.py – Transforms raw HackerOne API response dicts into
structured ProgramRecord objects.

No network calls are made here; all parsing is done on already-fetched data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import config
from logger import get_logger

log = get_logger("program_parser")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

UNKNOWN = "Unknown"


@dataclass
class ProgramRecord:
    """A structured, normalised representation of a HackerOne program."""

    # Identity
    handle: str = ""
    name: str = UNKNOWN
    url: str = UNKNOWN
    program_type: str = UNKNOWN          # "bug_bounty" | "vdp" | "unknown"
    offers_bounties: bool = False
    state: str = UNKNOWN                 # "public_mode" | "soft_launch" | etc.
    started_accepting_at: Optional[str] = None  # launch date; used for newest-first ordering

    # Report volume (90-day window)
    reports_received_90d: Optional[int] = None   # None = not available
    report_volume_category: str = UNKNOWN

    # Response time metrics (in hours, or None if unavailable)
    avg_first_response_h: Optional[float] = None
    avg_triage_h: Optional[float] = None
    avg_resolution_h: Optional[float] = None
    avg_time_to_bounty_h: Optional[float] = None
    response_efficiency_pct: Optional[float] = None

    # Scope
    scope_policy_url: str = UNKNOWN
    scope_review_status: str = "Pending Manual Review"

    # Metadata
    ranking_score: float = 0.0
    data_source: str = "HackerOne Public GraphQL"
    last_checked: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(config.DATE_FORMAT)
    )

    # Internal – raw payload for debugging
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    # Convenience helpers                                                  #
    # ------------------------------------------------------------------ #

    def is_below_threshold(self, max_reports: int = config.DEFAULT_MAX_REPORTS) -> bool:
        """Return True only when the 90-day count is KNOWN and below threshold."""
        return (
            self.reports_received_90d is not None
            and self.reports_received_90d <= max_reports
        )

    def display_reports(self) -> str:
        if self.reports_received_90d is not None:
            return str(self.reports_received_90d)
        return "New/Unverified"

    @property
    def data_confidence(self) -> str:
        available = sum(value is not None for value in (
            self.reports_received_90d,
            self.avg_first_response_h,
            self.avg_triage_h,
            self.avg_resolution_h,
            self.response_efficiency_pct,
        ))
        ratio = available / 5
        return "High" if ratio >= 0.8 else ("Medium" if ratio >= 0.4 else "Low")

    def display_response(self, hours: Optional[float]) -> str:
        if hours is None:
            return UNKNOWN
        if hours < 1:
            return f"{int(hours * 60)} min"
        return f"{hours:.1f} hrs"

    def to_row(self) -> Dict[str, Any]:
        """Return a flat dict suitable for pandas / CSV export."""
        # Format launch date from ISO timestamp to human-readable
        launch_display = UNKNOWN
        if self.started_accepting_at:
            try:
                dt = datetime.fromisoformat(
                    str(self.started_accepting_at).replace("Z", "+00:00")
                )
                launch_display = dt.strftime("%d %b %Y")   # e.g. "10 Jun 2026"
            except (TypeError, ValueError):
                launch_display = str(self.started_accepting_at)

        return {
            "Program Name":                 self.name,
            "HackerOne URL":                self.url,
            "Program Type":                 self.program_type,
            "Program Launch Date":          launch_display,
            "Bounty Availability":          "Yes" if self.offers_bounties else "No",
            "Reports Received (90 Days)":   self.display_reports(),
            "Report Volume Category":       self.report_volume_category,
            "Average First Response":       self.display_response(self.avg_first_response_h),
            "Average Triage Time":          self.display_response(self.avg_triage_h),
            "Average Resolution Time":      self.display_response(self.avg_resolution_h),
            "Average Time to Bounty":       self.display_response(self.avg_time_to_bounty_h),
            "Response Efficiency":          (
                f"{self.response_efficiency_pct:.1f}%"
                if self.response_efficiency_pct is not None
                else UNKNOWN
            ),
            "Official Scope Policy URL":    self.scope_policy_url,
            "Scope Review Status":          self.scope_review_status,
            "Ranking Score":                f"{self.ranking_score:.2f}",
            "Data Confidence":               self.data_confidence,
            "Data Source":                  self.data_source,
            "Last Checked Date":            self.last_checked,
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _classify_volume(count: Optional[int]) -> str:
    if count is None:
        return UNKNOWN
    for category, (lo, hi) in config.VOLUME_THRESHOLDS.items():
        if lo <= count <= hi:
            return category.replace("_", " ").title() + " Volume"
    if count >= 40:
        return "Above Threshold"
    return UNKNOWN


def _derive_scope_url(handle: str) -> str:
    """Return the canonical public scope policy URL for a given program handle."""
    if not handle:
        return UNKNOWN
    return f"https://hackerone.com/{handle}?type=team#scope"


def _derive_program_url(handle: str) -> str:
    if not handle:
        return UNKNOWN
    return f"https://hackerone.com/{handle}"


def _hours_from_seconds(seconds: Any) -> Optional[float]:
    v = _safe_float(seconds)
    return round(v / 3600, 2) if v is not None else None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_program(raw: Dict[str, Any]) -> ProgramRecord:
    """
    Parse a raw API dict (as returned by discovery.py) into a ProgramRecord.

    The HackerOne v1 API wraps attributes under an 'attributes' key.
    Both top-level and nested attribute layouts are handled.
    """
    attrs: Dict[str, Any] = raw.get("attributes", raw)   # graceful fallback
    handle: str = attrs.get("handle", "") or raw.get("id", "")

    # --- Program type classification ---
    submission_state = attrs.get("submission_state", "").lower()
    offers_bounties: bool = bool(attrs.get("offers_bounties", False))
    program_type: str
    if offers_bounties:
        program_type = "Bug Bounty"
    else:
        program_type = "VDP"

    # --- State ---
    state = attrs.get("state", attrs.get("submission_state", UNKNOWN))

    # --- Response time metrics -------------------------------------------------
    # HackerOne API exposes these under 'most_recent_activity_at', 'bounties_paid'
    # and several time-to-X fields depending on the endpoint / auth level.
    # Fields observed in the public API:
    #   average_time_to_first_program_response (seconds)
    #   average_time_to_bounty_awarded         (seconds)
    #   average_time_to_report_resolved        (seconds)
    response_stats = attrs.get("response_efficiency_percentage")
    avg_first_response_h  = _hours_from_seconds(attrs.get("average_time_to_first_program_response"))
    avg_triage_h          = _hours_from_seconds(attrs.get("average_time_to_triage"))
    avg_resolution_h      = _hours_from_seconds(attrs.get("average_time_to_report_resolved"))
    avg_time_to_bounty_h  = _hours_from_seconds(attrs.get("average_time_to_bounty_awarded"))
    response_efficiency   = _safe_float(response_stats)

    # --- 90-day report count ---------------------------------------------------
    # The public API may expose this under several possible field names.
    # Only use fields that represent 90-day received volume.
    # Never treat missing values, lifetime totals, or submission_count as zero.
    reports_90d: Optional[int] = None
    for key in (
        "reports_received_last_90_days",
        "reports_received_in_last_90_days",
        "last_90_days_report_count",
        "reports_last_90_days",
    ):
        val = attrs.get(key)
        if val is not None:
            reports_90d = _safe_int(val)
            break

    record = ProgramRecord(
        handle=handle,
        name=attrs.get("name", handle or UNKNOWN),
        url=_derive_program_url(handle),
        program_type=program_type,
        offers_bounties=offers_bounties,
        state=state,
        started_accepting_at=attrs.get("started_accepting_at"),
        reports_received_90d=reports_90d,
        report_volume_category=_classify_volume(reports_90d),
        avg_first_response_h=avg_first_response_h,
        avg_triage_h=avg_triage_h,
        avg_resolution_h=avg_resolution_h,
        avg_time_to_bounty_h=avg_time_to_bounty_h,
        response_efficiency_pct=response_efficiency,
        scope_policy_url=_derive_scope_url(handle),
        scope_review_status=(
            "Program profile link – verify current scope manually"
            if handle else "Pending Manual Review"
        ),
        data_source=attrs.get("data_source", "HackerOne Public GraphQL"),
        _raw=raw,
    )

    log.debug("Parsed: '%s' | reports_90d=%s | type=%s", record.name, record.display_reports(), record.program_type)
    return record


def parse_all(raw_programs: list) -> List[ProgramRecord]:
    """Parse a list of raw API dicts into ProgramRecord objects."""
    records: List[ProgramRecord] = []
    for raw in raw_programs:
        try:
            records.append(parse_program(raw))
        except Exception as exc:
            handle = raw.get("attributes", {}).get("handle", "<unknown>")
            log.warning("Failed to parse program '%s': %s", handle, exc)
    log.info("Parsed %d / %d programs successfully.", len(records), len(raw_programs))
    return records
