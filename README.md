# HackerOne Target Finder

A Python command-line tool that collects public HackerOne program information and exports programs with a selected number of reported submissions in the last 90 days. It does not scan program assets.

## Run on Windows

1. Install Python 3.10 or newer.
2. Double-click `RUN_WINDOWS.bat` to install dependencies and start the default run, or run:

```powershell
python -m pip install -r requirements.txt
python main.py
```

The default run includes programs with **0–40 known reports in the last 90 days**. Programs without a public report count are listed separately as unverified.

## Common options

```powershell
python main.py --min-reports 10 --max-reports 30
python main.py --require-bounty
python main.py --limit 100
python main.py --skip-enrichment
python main.py --max-enrichment 25
python main.py --export csv
python main.py --output-dir "C:\Reports\HackerOne"
python main.py --refresh
```

Use `python main.py --help` to see all options. Public directory discovery does not require credentials. HackerOne API credentials are optional and are only used for the authenticated REST fallback; configure them in a local `.env` file based on `.env.example` if needed.

## What the tool does

1. Retrieves programs from HackerOne's public GraphQL directory. It uses a six-hour cache unless `--refresh` is set.
2. Converts the results into program records and, by default, looks up additional public metrics. Detail results are cached for 24 hours; at most 100 lookups are made per run by default.
3. Selects records in the requested 90-day report range. Unknown counts stay unknown and are not treated as zero. `--days` is retained for compatibility; HackerOne supplies a fixed 90-day metric.
4. Scores records using available public metrics and sorts matching and unverified programs by launch date, newest first.
5. Saves the reports and a run log.

## Output

By default, files are saved in `Desktop/HackerOne Programs/Target_DD_MM_YYYY/`. Use `--output-dir` to choose another folder.

- `low_report_targets.csv` — matching and unverified programs
- `low_report_targets.xlsx` — matching, unverified, all-programs, response-time, and data-status sheets
- `h1_finder.log` — run details and errors
- Cache files — saved API results for later runs

## Notes

This tool uses public information only and does not test or scan any assets. Public metrics may be missing, so check each program's scope and data confidence yourself. A low report count or ranking score does not guarantee low competition or a successful bounty. Follow HackerOne's [Terms of Service](https://www.hackerone.com/terms/service), rate limits, and each program's rules.
