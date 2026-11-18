"""
metrics_collector.py – Enriches ProgramRecord objects with additional
publicly available metrics.

When the directory listing is missing a 90-day report count or response-time
metric, this module queries the public GraphQL team endpoint. Authenticated
REST detail calls are used only as a secondary fallback.

No private programs, private reports, or restricted data is accessed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
import time
from typing import Any, Dict, List, Optional

import config
from logger import get_logger
from program_parser import ProgramRecord, _hours_from_seconds, _safe_float, _safe_int, _classify_volume

log = get_logger("metrics_collector")


def _enrich_record(record: ProgramRecord, attrs: Dict[str, Any]) -> None:
    """Update *record* in-place with metric fields found in *attrs*."""
    if record.reports_received_90d is None:
        for key in (
            "reports_received_last_90_days",
            "reports_received_in_last_90_days",
            "last_90_days_report_count",
            "reports_last_90_days",
        ):
            val = attrs.get(key)
            if val is not None:
                record.reports_received_90d = _safe_int(val)
                record.report_volume_category = _classify_volume(record.reports_received_90d)
                log.debug("  '%s' 90-day count enriched: %s", record.handle, record.reports_received_90d)
                break

    if record.avg_first_response_h is None:
        v = attrs.get("average_time_to_first_program_response")
        if v is not None:
            record.avg_first_response_h = _hours_from_seconds(v)

    if record.avg_triage_h is None:
        v = attrs.get("average_time_to_triage") or attrs.get("average_time_to_report_triage")
        if v is not None:
            record.avg_triage_h = _hours_from_seconds(v)

    if record.avg_resolution_h is None:
        v = attrs.get("average_time_to_report_resolved")
        if v is not None:
            record.avg_resolution_h = _hours_from_seconds(v)

    if record.avg_time_to_bounty_h is None:
        v = attrs.get("average_time_to_bounty_awarded")
        if v is not None:
            record.avg_time_to_bounty_h = _hours_from_seconds(v)

    if record.response_efficiency_pct is None:
        v = attrs.get("response_efficiency_percentage")
        if v is not None:
            record.response_efficiency_pct = _safe_float(v)

    offers = attrs.get("offers_bounties")
    if offers is not None:
        record.offers_bounties = bool(offers)
        record.program_type = "Bug Bounty" if record.offers_bounties else "VDP"


def _needs_detail(record: ProgramRecord) -> bool:
    return record.reports_received_90d is None or (
        record.avg_first_response_h is None
        and record.avg_triage_h is None
        and record.avg_resolution_h is None
        and record.response_efficiency_pct is None
    )


def _load_detail_cache() -> Dict[str, Any]:
    path = os.path.join(config.OUTPUT_DIR, config.DETAIL_CACHE_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_detail_cache(cache: Dict[str, Any]) -> None:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, config.DETAIL_CACHE_FILENAME)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False)
        os.replace(temp_path, path)
    except OSError as exc:
        log.warning("Could not save detail cache: %s", exc)
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def enrich_records(
    records: List[ProgramRecord],
    skip_handles: Optional[List[str]] = None,
    max_lookups: Optional[int] = config.MAX_DETAIL_LOOKUPS,
) -> List[ProgramRecord]:
    """Fill missing public metrics, with bounded lookups and a 24-hour cache.

    Cached misses are retained too, preventing repeated requests for fields
    that HackerOne does not expose publicly. max_lookups limits network calls
    during this run; None means no limit and 0 disables enrichment.
    """
    skip = set(skip_handles or [])
    pending = [r for r in records if r.handle not in skip and _needs_detail(r)]
    if not pending:
        log.info("All %d records already have public metrics – skipping extra fetches.", len(records))
        return records
    if max_lookups == 0:
        log.info("Detail enrichment disabled (max_lookups=0).")
        return records

    from discovery import _build_graphql_session, fetch_program_detail_graphql

    cache = _load_detail_cache()
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=config.DETAIL_CACHE_TTL_HOURS)
    session = None
    network_lookups = 0
    cache_hits = 0
    enriched_count = 0

    try:
        for index, record in enumerate(pending, start=1):
            entry = cache.get(record.handle)
            attrs = None
            cache_valid = False
            if isinstance(entry, dict):
                try:
                    fetched_at = datetime.fromisoformat(entry.get("fetched_at", ""))
                    if fetched_at.tzinfo is None:
                        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                    if now - fetched_at <= ttl and "attributes" in entry:
                        attrs = entry.get("attributes")
                        cache_valid = True  # Includes cached negative lookups (None).
                        cache_hits += 1
                except (TypeError, ValueError):
                    cache_valid = False

            if not cache_valid and network_lookups < (max_lookups if max_lookups is not None else float("inf")):
                if session is None:
                    session = _build_graphql_session()
                network_lookups += 1
                log.debug("[%d/%d] Public detail lookup %d for '%s' …",
                          index, len(pending), network_lookups, record.handle)
                attrs = fetch_program_detail_graphql(record.handle, session=session)
                cache[record.handle] = {
                    "fetched_at": now.isoformat(),
                    "attributes": attrs,
                }

            if attrs:
                _enrich_record(record, attrs)
                enriched_count += 1

        _save_detail_cache(cache)
    finally:
        if session is not None:
            session.close()

    uncached_remaining = max(0, len(pending) - cache_hits - network_lookups)
    log.info(
        "Enrichment complete – %d records updated; %d cache hits; %d network lookups; "
        "%d pending lookups deferred by the configured limit.",
        enriched_count, cache_hits, network_lookups, uncached_remaining,
    )
    return records

def collect_data_status(records: List[ProgramRecord]) -> List[Dict[str, Any]]:
    """Sheet 4 (Data Collection Status) rows."""
    rows = []
    for r in records:
        rows.append({
            "Program Name": r.name,
            "Handle": r.handle,
            "90-Day Reports Available": "Yes" if r.reports_received_90d is not None else "No",
            "First Response Available": "Yes" if r.avg_first_response_h is not None else "No",
            "Triage Time Available": "Yes" if r.avg_triage_h is not None else "No",
            "Resolution Time Available": "Yes" if r.avg_resolution_h is not None else "No",
            "Time to Bounty Available": "Yes" if r.avg_time_to_bounty_h is not None else "No",
            "Response Efficiency Available": "Yes" if r.response_efficiency_pct is not None else "No",
            "Data Source": r.data_source,
            "Last Checked": r.last_checked,
        })
    return rows
