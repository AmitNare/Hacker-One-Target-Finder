"""
main.py – CLI entry point for the HackerOne Target Finder.

Usage examples:
    python main.py
    python main.py --max-reports 39 --export both
    python main.py --max-reports 20 --export csv --limit 200
    python main.py --help

Environment variables:
    H1_API_USERNAME   HackerOne API identifier (for authenticated access)
    H1_API_TOKEN      HackerOne API token      (for authenticated access)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import config

log = None  # Configured after the dated output directory is selected.


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h1-target-finder",
        description=(
            "HackerOne Automated Bug Bounty Target Finder\n"
            "Discovers public HackerOne programs and identifies those with\n"
            "low report volume (< 40 reports in the last 90 days).\n\n"
            "DISCLAIMER: Low report count does not guarantee low competition\n"
            "or better bounty outcomes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--min-reports", type=int, default=config.DEFAULT_MIN_REPORTS,
        metavar="N",
        help=f"Minimum 90-day report count (default: {config.DEFAULT_MIN_REPORTS})",
    )
    parser.add_argument(
        "--max-reports", type=int, default=config.DEFAULT_MAX_REPORTS,
        metavar="N",
        help=f"Maximum 90-day report count (default: {config.DEFAULT_MAX_REPORTS})",
    )
    parser.add_argument(
        "--days", type=int, default=config.DEFAULT_DAYS,
        metavar="N",
        help="HackerOne exposes a fixed 90-day report metric; this option is retained for compatibility (default: 90)",
    )
    parser.add_argument(
        "--export", choices=["csv", "excel", "both"], default="both",
        help="Export format (default: both)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        metavar="N",
        help="Limit total programs fetched (default: all)",
    )
    parser.add_argument(
        "--require-bounty", action="store_true",
        help="Only include programs that offer monetary bounties",
    )
    parser.add_argument(
        "--skip-enrichment", action="store_true",
        help="Skip per-program detail API calls (faster, but fewer metrics)",
    )
    parser.add_argument(
        "--max-enrichment", type=int, default=config.MAX_DETAIL_LOOKUPS, metavar="N",
        help=f"Maximum public detail lookups per run (default: {config.MAX_DETAIL_LOOKUPS}; use 0 to disable)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        metavar="PATH",
        help="Optional custom output directory (default: Desktop/HackerOne Programs/Target_DD_MM_YYYY)",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force re-fetch even if cached data exists",
    )
    parser.add_argument(
        "--no-colour", action="store_true",
        help="Disable ANSI colour output",
    )
    return parser


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

ANSI_GREEN  = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN   = "\033[96m"
ANSI_RESET  = "\033[0m"
ANSI_BOLD   = "\033[1m"


def _c(text: str, code: str, use_colour: bool) -> str:
    return f"{code}{text}{ANSI_RESET}" if use_colour else text


def _print_banner(use_colour: bool = True) -> None:
    banner = """
+--------------------------------------------------------------+
|      HackerOne Automated Bug Bounty Target Finder            |
|      Identifies low-volume public bug bounty programs        |
+--------------------------------------------------------------+
|  DISCLAIMER: For educational & research purposes only.       |
|  Always respect HackerOne ToS & program scope policies.      |
+--------------------------------------------------------------+
"""
    # Use sys.stdout.buffer.write to handle any encoding safely
    import sys
    try:
        print(_c(banner, ANSI_CYAN, use_colour))
    except UnicodeEncodeError:
        sys.stdout.buffer.write(banner.encode("utf-8"))
        sys.stdout.buffer.flush()


def _print_summary(matching, unverified, all_records, csv_path, excel_path, use_colour):
    print()
    print(_c("=" * 60, ANSI_CYAN, use_colour))
    print(_c("  RESULTS SUMMARY", ANSI_BOLD, use_colour))
    print(_c("=" * 60, ANSI_CYAN, use_colour))
    print(f"  Total programs discovered       : {len(all_records)}")
    print(f"  Programs in report range (0–40) : {_c(str(len(matching)), ANSI_GREEN, use_colour)}")
    print(f"  New / no 90-day data yet        : {_c(str(len(unverified)), ANSI_YELLOW, use_colour)}")
    print()

    if matching:
        print(_c("  Top 10 Ranked Programs (confirmed):", ANSI_BOLD, use_colour))
        print(f"  {'#':<4} {'Program':<35} {'Reports':>8} {'Score':>8}")
        print("  " + "-" * 58)
        for i, r in enumerate(matching[:10], start=1):
            reports = r.display_reports()
            score   = f"{r.ranking_score:.1f}"
            name    = r.name[:33]
            print(f"  {i:<4} {name:<35} {reports:>8} {score:>8}")

    if unverified:
        print()
        print(_c("  Newest / Unverified Programs (no 90-day data yet):", ANSI_BOLD, use_colour))
        print(f"  {'#':<4} {'Program':<35} {'Type':<12} {'Launched':>20}")
        print("  " + "-" * 74)
        for i, r in enumerate(unverified[:10], start=1):
            name    = r.name[:33]
            ptype   = r.program_type[:10]
            launched = str(r.started_accepting_at or "Unknown")[:20]
            print(f"  {i:<4} {name:<35} {ptype:<12} {launched:>20}")

    print()
    if csv_path:
        print(f"  CSV   -> {_c(csv_path, ANSI_GREEN, use_colour)}")
    if excel_path:
        print(f"  Excel -> {_c(excel_path, ANSI_GREEN, use_colour)}")
    print(_c("=" * 60, ANSI_CYAN, use_colour))
    print()


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def _check_runtime_dependencies() -> bool:
    """Fail early with actionable instructions if runtime packages are missing."""
    import importlib.util

    required = ("requests", "pandas", "openpyxl", "urllib3")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if not missing:
        return True

    print("\n[DEPENDENCY ERROR] Missing required packages:")
    for name in missing:
        print(f"  - {name}")
    print("\nInstall dependencies into this same Python environment:")
    print("  python -m pip install -r requirements.txt")
    print("\nFor this project's Windows virtual environment:")
    print(r"  .\.venv\Scripts\python.exe -m pip install -r requirements.txt")
    print(r"  .\.venv\Scripts\python.exe main.py --refresh --skip-enrichment")
    return False


def run(args: argparse.Namespace) -> int:
    """
    Full pipeline:
      1. Discover programs
      2. Parse records
      3. Enrich metrics (optional)
      4. Filter
      5. Rank
      6. Export
    """
    if not _check_runtime_dependencies():
        return 2

    use_colour = not args.no_colour

    # Use one dated folder per day. Re-running on the same day reuses the
    # folder, replacing reports/caches and starting a fresh log.
    if args.output_dir:
        config.OUTPUT_DIR = os.path.abspath(args.output_dir)
    else:
        config.OUTPUT_DIR = config.get_output_dir()
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # Truncate only this run's log file once. Module loggers opened later
    # append to the same file so they do not repeatedly erase each other.
    log_path = os.path.join(config.OUTPUT_DIR, config.LOG_FILENAME)
    with open(log_path, "w", encoding="utf-8"):
        pass

    # Create an empty detail cache if it does not exist; normal cache writes
    # use os.replace, so an existing cache is replaced safely on update.
    detail_cache_path = os.path.join(config.OUTPUT_DIR, config.DETAIL_CACHE_FILENAME)
    if not os.path.exists(detail_cache_path):
        with open(detail_cache_path, "w", encoding="utf-8") as cache_file:
            cache_file.write("{}")

    from logger import get_logger
    global log
    log = get_logger("main")

    _print_banner(use_colour)

    start_time = time.time()
    log.info("Pipeline started at %s", datetime.now(timezone.utc).isoformat())
    if args.days != 90:
        log.warning(
            "HackerOne's public field is a fixed 90-day metric; --days=%d does not change the source reporting window.",
            args.days,
        )
    if args.min_reports < 0 or args.max_reports < args.min_reports:
        log.error("Invalid report range: require 0 <= min-reports <= max-reports.")
        return 2
    if args.limit is not None and args.limit < 1:
        log.error("--limit must be a positive integer.")
        return 2
    if args.max_enrichment < 0:
        log.error("--max-enrichment must be zero or a positive integer.")
        return 2

    log.info("Parameters: min=%d max=%d limit=%s export=%s",
             args.min_reports, args.max_reports, args.limit, args.export)

    # ── Step 1: Discover ────────────────────────────────────────────────
    log.info("[1/6] Discovering public HackerOne programs …")
    from discovery import discover_programs
    raw_programs = discover_programs(max_programs=args.limit, refresh=args.refresh)

    if not raw_programs:
        log.error(
            "No programs discovered. Check internet access and the public HackerOne "
            "directory endpoint. The REST fallback requires valid API credentials; "
            "a REST HTTP 401 does not mean public GraphQL discovery is authenticated."
        )
        return 1

    # ── Step 2: Parse ───────────────────────────────────────────────────
    log.info("[2/6] Parsing %d program records …", len(raw_programs))
    from program_parser import parse_all
    records = parse_all(raw_programs)

    # ── Step 3: Enrich metrics (optional) ───────────────────────────────
    if not args.skip_enrichment:
        log.info("[3/6] Enriching metrics via detail API …")
        from metrics_collector import enrich_records, collect_data_status
        records = enrich_records(records, max_lookups=args.max_enrichment)
    else:
        log.info("[3/6] Skipping enrichment (--skip-enrichment set).")
        from metrics_collector import collect_data_status

    data_status = collect_data_status(records)

    # ── Step 4: Filter ──────────────────────────────────────────────────
    log.info("[4/6] Applying filters (reports_90d=%d–%d) …", args.min_reports, args.max_reports)
    from filter_engine import apply_filters, summarise
    result = apply_filters(
        records,
        min_reports=args.min_reports,
        max_reports=args.max_reports,
        require_bounty=args.require_bounty,
    )
    summarise(result)

    # ── Step 5: Rank ────────────────────────────────────────────────────
    log.info("[5/6] Ranking matching programs …")
    from ranking import rank_programs
    ranked_matching = rank_programs(result.matching)
    # Rank the unverified (new) programs separately for the dedicated sheet.
    ranked_unverified = rank_programs(result.unverified)
    # Discovery is already ordered by started_accepting_at DESC. Re-apply that
    # ordering after ranking so the newest launched programs appear first.
    def _launch_sort_key(record):
        value = record.started_accepting_at
        if not value:
            return (0, datetime.min)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return (1, parsed)
        except (TypeError, ValueError):
            return (0, datetime.min)
    ranked_matching.sort(key=_launch_sort_key, reverse=True)
    ranked_unverified.sort(key=_launch_sort_key, reverse=True)
    ranked_all      = rank_programs(records)   # rank all for Sheet 2

    # ── Step 6: Export ──────────────────────────────────────────────────
    log.info("[6/6] Exporting results …")
    from exporter import export_csv, export_excel

    csv_path   = None
    excel_path = None

    if args.export in ("csv", "both"):
        csv_path = export_csv(ranked_matching, ranked_unverified)

    if args.export in ("excel", "both"):
        excel_path = export_excel(
            matching_records  = ranked_matching,
            unverified_records = ranked_unverified,
            all_records       = ranked_all,
            data_status_rows  = data_status,
        )

    elapsed = time.time() - start_time
    log.info("Pipeline completed in %.1f seconds.", elapsed)

    _print_summary(ranked_matching, ranked_unverified, records, csv_path, excel_path, use_colour)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser  = _build_parser()
    args    = parser.parse_args()
    sys.exit(run(args))
