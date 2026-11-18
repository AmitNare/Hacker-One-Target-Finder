# Changelog

## 1.3.0 — 2026-11-01

- Kept public GraphQL discovery as the primary unauthenticated source.
- Kept the HackerOne v1 hackers REST API as an optional authenticated fallback.
- Bounded GraphQL and REST HTTP 429 retry handling.
- Restricted REST pagination URLs to HTTPS `api.hackerone.com` before sending authenticated requests.
- Fixed discovery caching so a run with `--limit` does not overwrite the full cache with a truncated subset.
- Added a 24-hour per-program detail cache, including negative results, to avoid repeated lookups for unavailable public metrics.
- Added `--max-enrichment` to cap detail requests per run.
- Added Data Confidence to exported records and the empty CSV header.
- Clarified that generated profile/scope links still require manual scope verification.
- Added regression tests for bounded retries and data confidence.
- Added `RUN_WINDOWS.bat` for Windows setup and execution.

## 1.3.1 - Dependency setup fix
- Added a dependency preflight with clear pip installation instructions.
- Added INSTALL_DEPENDENCIES.bat for Windows virtual-environment setup.
- Updated RUN_WINDOWS.bat to install requirements into the same interpreter used to run the CLI.
- Clarified virtual-environment installation instructions.

## 1.3.2
- Added a one-click Windows launcher.
- Added a helper to create a Desktop shortcut to the launcher.
- Removed Python cache files from the distribution archive.

## 1.3.3 — Dated Desktop output and overwrite behavior
- Save run output under `Desktop/HackerOne Programs/Target_DD_MM_YYYY`.
- Reuse the same dated folder on repeat runs; CSV/Excel and updated cache files are replaced.
- Start a fresh `h1_finder.log` on each run.
- Initialize `program_details_cache.json` when absent.
- No discovery, filtering, ranking, or scoring logic changed.

## 1.3.4 - 2026-11-12

- Changed the default 90-day report filter to 30–40 reports (inclusive).
- Kept all public programs eligible regardless of launch age; discovery is ordered by newest launch date first.
- Added the program launch date to parsed records and exported reports.
- Left enrichment, ranking score calculation, output paths, caches, and Windows launchers unchanged.
