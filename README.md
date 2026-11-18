# HackerOne Automated Bug Bounty Target Finder

A professional Python automation tool that discovers publicly accessible HackerOne bug bounty programs, evaluates their publicly available program statistics, and identifies potentially less-crowded bounty opportunities.

> **DISCLAIMER:** This tool collects only publicly accessible information from the HackerOne API.  
> Low report count does **not** guarantee low competition or better bounty outcomes.  
> Always respect HackerOne's Terms of Service, program scope policies, and rate limits.

---

## Features

- 🔍 **Program Discovery** – Fetches public HackerOne programs from the public GraphQL directory (no login required)
- 📊 **90-Day Report Filter** – Finds recently launched programs with 30–40 publicly reported reports in the last 90 days. Programs are ordered by launch date (newest first); there is no 90-day launch-date cutoff.
- 🧾 **Data Confidence** – Shows whether public metrics are High, Medium, or Low completeness
- 🧠 **Safe Caching** – Caches the public directory and detail lookups to reduce repeated requests
- ⏳ **Bounded Retries** – Handles rate limits with a maximum retry count and bounded wait
- ⏱ **Response Time Analysis** – Collects publicly available response metrics
- 🏆 **Ranking System** – Scores programs by volume, responsiveness, and bounty availability
- 📁 **Dual Export** – Generates both CSV and Excel (multi-sheet) reports
- 🔒 **No Scope Probing** – Only references official scope policy URLs; never scans assets

---

## Project Structure

```
HackerOne Target Finder/
├── config.py            # All configuration constants
├── logger.py            # Centralised logging setup
├── discovery.py         # Program discovery via HackerOne API
├── program_parser.py    # Raw API data → ProgramRecord objects
├── metrics_collector.py # Metric enrichment via detail API
├── filter_engine.py     # Report-volume filtering
├── ranking.py           # Composite scoring & ranking
├── exporter.py          # CSV and Excel export
├── main.py              # CLI entry point
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── tests/               # Unit tests
│   ├── test_filter_engine.py
│   ├── test_program_parser.py
│   └── test_ranking.py
└── tests/               # Unit tests

Generated files are saved outside the source folder, on the Desktop:

```
Desktop/
└── HackerOne Programs/
    └── Target_DD_MM_YYYY/
        ├── low_report_targets.csv
        ├── low_report_targets.xlsx
        ├── h1_finder.log
        ├── programs_cache.json
        └── program_details_cache.json
```

Running the tool again on the same date reuses that folder and overwrites
report files and updated caches. The log is started fresh for each run.
```

---

## Installation

### Prerequisites
- Python 3.10 or higher
- pip
- Internet access to `hackerone.com`


### Steps

On Windows, double-click `INSTALL_DEPENDENCIES.bat` to install packages into the project's `.venv`, or use `RUN_WINDOWS.bat` to install dependencies and launch the application automatically.

### One-click Desktop Launch (Windows)

1. Extract the complete project folder to a permanent location (for example, `E:\VAPT Project\HackerOne Target Finder`). Do not move the folder after creating the shortcut.
2. Double-click `CREATE_DESKTOP_SHORTCUT.bat` once. It creates **HackerOne Target Finder** on your Windows Desktop.
3. Double-click the Desktop shortcut whenever you want to run the tool. A Command Prompt window opens, checks/installs dependencies in the project `.venv`, runs the default command (`python main.py`), displays the output, and pauses so you can read it.

You can also double-click `START_HACKERONE_TARGET_FINDER.bat` directly from the project folder. Optional CLI arguments can be passed to that launcher if needed. VS Code is not required to run the application.
 A virtual environment is isolated; activating it does not install packages.

```bash
# 1. Clone / download the project
cd "e:\VAPT Project\HackerOne Target Finder"

# 2. Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

# 3. Install dependencies into the active virtual environment
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

---

## Configuration

### API Authentication (optional fallback)

The **hackers REST API always requires credentials** and returns HTTP 401 without them. That is expected. Discovery uses the public GraphQL directory first and does **not** need a token.

If you still want REST as a fallback:

```bash
copy .env.example .env
```

Edit `.env` with **your** username and API token from https://hackerone.com/settings/api_token/edit

The application loads `.env` automatically via `python-dotenv`. Do not put real tokens in `.env.example`.

```powershell
# Or set them only for the current PowerShell session
$env:H1_API_USERNAME="your_username"
$env:H1_API_TOKEN="your_api_token"
```

---

## Usage

### Basic Run (default: 30–40 reports in the last 90 days, newest launches first)

```bash
python main.py
```

If you use `.venv`, install requirements after activating it. Always use the same interpreter for installation and execution.

### Custom Report Threshold

```bash
python main.py --min-reports 30 --max-reports 40
```

### Export Options

```bash
python main.py --export csv          # CSV only
python main.py --export excel        # Excel only
python main.py --export both         # Both (default)
```

### Limit Programs Fetched

```bash
python main.py --limit 100           # Process first 100 programs only
```

### Bug Bounty Programs Only (exclude VDP)

```bash
python main.py --require-bounty
```

### Skip Detail API Calls (faster, fewer metrics)

```bash
python main.py --skip-enrichment
```

### Limit Detail Lookups

By default, the tool makes at most 100 per-program public detail lookups per run. Cached detail results (including unavailable results) are reused for 24 hours.

```bash
python main.py --max-enrichment 25  # At most 25 network lookups
python main.py --max-enrichment 0   # Disable detail lookups
```

Use `--refresh` to refresh the public directory cache. It does not delete the separate detail cache.

### Full Example

```bash
python main.py --min-reports 30 --max-reports 40 --days 90 --export both --limit 500 --require-bounty --max-enrichment 100
```

---

## Output Files

### `output/low_report_targets.csv`
Flat CSV containing all confirmed below-threshold programs.

### `output/low_report_targets.xlsx`
Multi-sheet Excel workbook:

| Sheet | Contents |
|-------|----------|
| Matching Programs | Confirmed below-threshold programs, colour-coded by volume |
| All Discovered Programs | Every program found, ranked by score |
| Response Time Analysis | Response/triage/resolution metrics for all programs |
| Data Collection Status | Per-program metric availability tracking |

### `output/h1_finder.log`
Full debug log of every API call, parse result, filter decision, and export step.

---

## Report Volume Categories

| Range | Category | Excel Colour |
|-------|----------|-------------|
| 0 – 9 | Very Low Volume | 🟢 Green |
| 10 – 19 | Low Volume | 🟡 Light Green |
| 20 – 29 | Moderate Volume | 🟠 Amber |
| 30 – 40 | Selected Report Range | 🔴 Orange |
| Unknown | Unknown | ⬜ Grey |
| ≥ 40 | Excluded | – |

---

## Ranking System

Programs are scored 0–100 using a weighted composite:

| Factor | Weight |
|--------|--------|
| Report Volume (90 days) | 33% |
| Average First Response | 22% |
| Average Triage Time | 13% |
| Average Resolution Time | 10% |
| Response Efficiency | 10% |
| Bounty Availability | 7% |
| Documented scope policy URL | 5% |

Higher score = more attractive based on available public metrics. Unknown metrics use a neutral midpoint; always review Data Confidence alongside the score. This is not a guarantee of low competition, vulnerability discovery, or bounty success. HackerOne's public GraphQL directory is not a versioned API contract and may change; the tool logs schema/network failures rather than bypassing access controls.

---

## Running Tests

```bash
python -m pytest tests/ -v
# or
python -m unittest discover tests/
```

---

## Data Availability Notes

Public HackerOne data varies by source:
1. **Public GraphQL directory** – program identity, bounty/VDP flag, SLA response times, and (when the schema exposes it) `reports_received_last_90_days`
2. **Program configuration** – some programs hide public statistics
3. **REST v1 hackers API** – requires a personal API token; still may omit 90-day volume

Missing metrics are recorded as `Unknown`. Unknown 90-day counts are **never treated as zero** and are **not** included in confirmed below-threshold results.

---

## Important Notes

- This tool respects HackerOne's [Terms of Service](https://www.hackerone.com/terms/service)
- Rate limiting is built-in (1.5 second delay between requests)
- No private program data, private reports, or restricted information is accessed
- Scope policy URLs are provided for **manual review only** – no automated scanning
- All data is sourced from publicly accessible HackerOne GraphQL/REST endpoints
- Cached discovery results in `output/programs_cache.json` are reused for 6 hours unless you pass `--refresh`

---

## License

For educational and research purposes only. Use responsibly.


---

## Troubleshooting (Windows PowerShell)

Run commands from the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py main.py --refresh --skip-enrichment --export both
```

The first run with `--refresh` bypasses the local six-hour discovery cache.
`--skip-enrichment` is useful for a quick connectivity check and avoids making
one detail request per program.

### Understanding HTTP 401

The `/v1/hackers/programs` REST endpoint requires HTTP Basic authentication.
A 401 from this endpoint is expected when no API username/token is configured.
The application must not treat that response as proof that public directory
discovery requires credentials. Public GraphQL directory discovery is attempted
first; REST is only an optional fallback.

If you choose to configure REST fallback, copy `.env.example` to `.env` and
enter your own API identifier and token. Never share `.env` or commit it.

### If GraphQL discovery returns zero programs

1. Open `https://hackerone.com/directory/programs` in a browser and confirm it loads.
2. Run `py main.py --refresh --skip-enrichment`.
3. Check `output/h1_finder.log` for GraphQL HTTP status and GraphQL schema errors.
4. Update the project from the same ZIP/extracted folder; do not mix old `.py`
   files with new ones.
5. If HackerOne changes its public GraphQL schema or access policy, the query
   must be updated to match the current public schema. Do not bypass login,
   CAPTCHA, or access controls.

### Important data limitations

HackerOne may hide report-volume and response-time metrics for individual
programs. Missing values remain `Unknown`; they are never converted to zero.
The report count field exposed by the public directory is specifically a
90-day metric. The `--days` argument is retained for CLI compatibility and
does not change HackerOne's server-side reporting period.
