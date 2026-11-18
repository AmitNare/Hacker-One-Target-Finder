"""
filter_engine.py – Applies report-volume and quality filters to a list of
ProgramRecord objects.

Design rules:
  - A program is included in the 'matching' set when its 90-day report count
    is a KNOWN integer in [min_reports, max_reports].
  - Programs with Unknown report counts are placed in a separate
    'unverified' list (new/recently-launched programs with no 90-day history).
    These ARE exported to a dedicated "New & Unverified Programs" sheet so the
    user can still review and manually check them.
  - Programs with > max_reports reports are excluded from the primary output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import config
from logger import get_logger
from program_parser import ProgramRecord, UNKNOWN

log = get_logger("filter_engine")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    matching: List[ProgramRecord]    # confirmed in-range programs
    excluded: List[ProgramRecord]    # programs > max_reports
    unverified: List[ProgramRecord]  # report count is Unknown (new programs, no 90-day data yet)

    @property
    def all_programs(self) -> List[ProgramRecord]:
        return self.matching + self.excluded + self.unverified


# ---------------------------------------------------------------------------
# Core filter
# ---------------------------------------------------------------------------

def apply_filters(
    records: List[ProgramRecord],
    min_reports: int = config.DEFAULT_MIN_REPORTS,
    max_reports: int = config.DEFAULT_MAX_REPORTS,
    require_bounty: bool = False,
    require_known_response: bool = False,
) -> FilterResult:
    """
    Split *records* into matching, excluded, and unverified buckets.

    Parameters
    ----------
    records               : All parsed ProgramRecord objects.
    min_reports           : Minimum 90-day report count (inclusive). Default 0.
    max_reports           : Maximum 90-day report count (inclusive). Default 40.
    require_bounty        : If True, only include programs that offer bounties.
    require_known_response: If True, only include programs with known response times.

    Returns
    -------
    FilterResult with three partitioned lists.
    - matching   : known report count in [min_reports, max_reports]
    - unverified : report count is None (new/recently launched programs — still exported!)
    - excluded   : report count known but above max_reports
    """
    matching: List[ProgramRecord] = []
    excluded: List[ProgramRecord] = []
    unverified: List[ProgramRecord] = []

    for r in records:
        # ── Optional hard-filter: bounty programs only ──────────────────
        if require_bounty and not r.offers_bounties:
            log.debug("Excluding '%s' – no bounty program.", r.name)
            excluded.append(r)
            continue

        # ── Optional hard-filter: require known response time ────────────
        if require_known_response and r.avg_first_response_h is None:
            log.debug("Excluding '%s' – unknown first-response time.", r.name)
            excluded.append(r)
            continue

        # ── Primary report-count filter ──────────────────────────────────
        if r.reports_received_90d is None:
            # New or recently-launched program — no 90-day data available yet.
            # Keep in unverified so they appear in the dedicated output sheet.
            log.debug("Unverified '%s' – 90-day report count unknown (new program).", r.name)
            unverified.append(r)
            continue

        count = r.reports_received_90d
        if min_reports <= count <= max_reports:
            log.debug("MATCH: '%s' with %d reports.", r.name, count)
            matching.append(r)
        else:
            log.debug("Excluded: '%s' with %d reports (outside %d–%d).", r.name, count, min_reports, max_reports)
            excluded.append(r)

    log.info(
        "Filter results – Matching: %d | Unverified/New: %d | Excluded: %d",
        len(matching), len(unverified), len(excluded),
    )
    return FilterResult(matching=matching, excluded=excluded, unverified=unverified)


def summarise(result: FilterResult) -> None:
    """Print a human-readable filter summary to the log."""
    log.info("=" * 60)
    log.info("FILTER SUMMARY")
    log.info("  Confirmed in-range programs        : %d", len(result.matching))
    log.info("  New / no 90-day data (unverified)  : %d", len(result.unverified))
    log.info("  Programs above threshold (excluded) : %d", len(result.excluded))
    log.info("  Total programs processed            : %d", len(result.all_programs))
    log.info("=" * 60)

    # Category breakdown of matching programs
    categories: dict = {}
    for r in result.matching:
        cat = r.report_volume_category
        categories[cat] = categories.get(cat, 0) + 1
    if categories:
        log.info("  Volume category breakdown (confirmed):")
        for cat, cnt in sorted(categories.items()):
            log.info("    %-30s : %d", cat, cnt)
    log.info("=" * 60)
