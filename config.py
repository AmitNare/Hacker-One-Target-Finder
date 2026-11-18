"""
Configuration module for HackerOne Target Finder.
All tunable parameters, API endpoints, and defaults live here.
"""

import os
from datetime import date
from pathlib import Path
from typing import List, Optional

# Load optional .env from the project root without overriding real env vars.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# API & Endpoint constants
# ---------------------------------------------------------------------------
HACKERONE_API_BASE = "https://api.hackerone.com/v1"
HACKERONE_PROGRAMS_ENDPOINT = f"{HACKERONE_API_BASE}/hackers/programs"
HACKERONE_PROGRAM_DETAIL_ENDPOINT = f"{HACKERONE_API_BASE}/hackers/programs/{{handle}}"

HACKERONE_GRAPHQL_URL = "https://hackerone.com/graphql"
HACKERONE_DIRECTORY_URL = "https://hackerone.com/directory/programs"

# ---------------------------------------------------------------------------
# Request defaults
# ---------------------------------------------------------------------------
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "HackerOne-Target-Finder/1.1 (educational-research)",
}

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS: float = 1.5
MAX_RETRIES: int = 3
RETRY_BACKOFF_FACTOR: float = 2.0
RETRY_STATUS_CODES: List[int] = [429, 500, 502, 503, 504]

# ---------------------------------------------------------------------------
# Filtering defaults
# ---------------------------------------------------------------------------
DEFAULT_MIN_REPORTS: int = 0   # 0 = include all programs up to max (catches new + low-volume)
DEFAULT_MAX_REPORTS: int = 40
DEFAULT_DAYS: int = 90
DEFAULT_PAGE_SIZE: int = 50
MAX_PROGRAMS: Optional[int] = None

# ---------------------------------------------------------------------------
# Report volume classification thresholds
# ---------------------------------------------------------------------------
VOLUME_THRESHOLDS = {
    "very_low": (0, 9),
    "low": (10, 19),
    "moderate": (20, 29),
    "below_threshold": (30, 39),
}

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
def get_output_dir(run_date: Optional[date] = None) -> str:
    """Return the dated Desktop output folder used for each daily run."""
    run_date = run_date or date.today()
    folder_name = f"Target_{run_date:%d_%m_%Y}"
    return str(Path.home() / "Desktop" / "HackerOne Programs" / folder_name)


OUTPUT_DIR = get_output_dir()
CSV_FILENAME = "low_report_targets.csv"
EXCEL_FILENAME = "low_report_targets.xlsx"
LOG_FILENAME = "h1_finder.log"
CACHE_FILENAME = "programs_cache.json"
DETAIL_CACHE_FILENAME = "program_details_cache.json"
DETAIL_CACHE_TTL_HOURS = 24
MAX_DETAIL_LOOKUPS = 100

# ---------------------------------------------------------------------------
# Excel sheet names
# ---------------------------------------------------------------------------
SHEET_MATCHING = "Matching Programs"
SHEET_UNVERIFIED = "New & Unverified Programs"
SHEET_ALL = "All Discovered Programs"
SHEET_RESPONSE = "Response Time Analysis"
SHEET_DATA_STATUS = "Data Collection Status"

# ---------------------------------------------------------------------------
# Required output columns (order matters for CSV / Excel)
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = [
    "Program Name",
    "HackerOne URL",
    "Program Type",
    "Program Launch Date",
    "Bounty Availability",
    "Reports Received (90 Days)",
    "Report Volume Category",
    "Average First Response",
    "Average Triage Time",
    "Average Resolution Time",
    "Average Time to Bounty",
    "Response Efficiency",
    "Official Scope Policy URL",
    "Scope Review Status",
    "Ranking Score",
    "Data Confidence",
    "Data Source",
    "Last Checked Date",
]

# ---------------------------------------------------------------------------
# Ranking weights  (higher = more important)
# ---------------------------------------------------------------------------
RANKING_WEIGHTS = {
    "report_volume": 0.33,
    "response_time": 0.22,
    "triage_time": 0.13,
    "resolution_time": 0.10,
    "response_efficiency": 0.10,
    "bounty_availability": 0.07,
    "scope_documented": 0.05,
}

# ---------------------------------------------------------------------------
# Credentials (optional – needed for authenticated REST API access)
# Set via environment variables or a local .env file; never hard-code secrets.
# ---------------------------------------------------------------------------
H1_API_USERNAME: Optional[str] = os.getenv("H1_API_USERNAME")
H1_API_TOKEN: Optional[str] = os.getenv("H1_API_TOKEN")

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
CACHE_TTL_HOURS = 6
