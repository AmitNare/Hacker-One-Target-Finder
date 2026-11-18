"""
exporter.py – Generates CSV and Excel reports from ranked ProgramRecord data.

Excel Workbook structure:
  Sheet 1 – Matching Programs      (below-threshold confirmed programs)
  Sheet 2 – All Discovered Programs (every program discovered)
  Sheet 3 – Response Time Analysis
  Sheet 4 – Data Collection Status

All exports go to config.OUTPUT_DIR.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Font, PatternFill, Border, Side
)
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows

import config
from logger import get_logger
from program_parser import ProgramRecord, UNKNOWN

log = get_logger("exporter")

# ---------------------------------------------------------------------------
# Colour palette (ARGB hex, no leading #)
# ---------------------------------------------------------------------------
CLR_HEADER_BG   = "FF1F4E79"   # Dark blue header
CLR_HEADER_FG   = "FFFFFFFF"   # White text
CLR_VERY_LOW    = "FF00B050"   # Green  – 0-9 reports
CLR_LOW         = "FF92D050"   # Light green – 10-19
CLR_MODERATE    = "FFFFC000"   # Amber – 20-29
CLR_BELOW_THR   = "FFFF6600"   # Orange – 30-39
CLR_UNKNOWN     = "FFD9D9D9"   # Grey – unknown
CLR_ALT_ROW     = "FFE9F0F9"   # Light blue alternate row
CLR_WHITE       = "FFFFFFFF"


def _make_df(records: List[ProgramRecord]) -> pd.DataFrame:
    """Convert a list of ProgramRecord objects to a pandas DataFrame."""
    return pd.DataFrame([r.to_row() for r in records])


def _header_style() -> dict:
    return dict(
        font=Font(name="Calibri", bold=True, color=CLR_HEADER_FG, size=11),
        fill=PatternFill("solid", fgColor=CLR_HEADER_BG),
        alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
        border=Border(
            bottom=Side(style="medium", color="FF000000"),
        ),
    )


def _apply_styles(ws, header_row: int = 1) -> None:
    """Apply header formatting and alternating row colours to a worksheet."""
    h_style = _header_style()

    for cell in ws[header_row]:
        for attr, val in h_style.items():
            setattr(cell, attr, val)

    for row_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1), start=1):
        bg = CLR_ALT_ROW if row_idx % 2 == 0 else CLR_WHITE
        for cell in row:
            cell.fill = PatternFill("solid", fgColor=bg)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.font = Font(name="Calibri", size=10)


def _auto_width(ws, min_width: int = 12, max_width: int = 50) -> None:
    """Set column widths based on content length."""
    for col in ws.columns:
        max_len = max_width
        col_letter = get_column_letter(col[0].column)
        lengths = []
        for cell in col:
            try:
                if cell.value:
                    lengths.append(len(str(cell.value)))
            except Exception:
                pass
        if lengths:
            max_len = min(max(max(lengths) + 2, min_width), max_width)
        ws.column_dimensions[col_letter].width = max_len


def _colour_report_cell(ws, col_letter: str, start_row: int) -> None:
    """Colour-code the 'Reports Received (90 Days)' column cells."""
    colour_map = {
        "Very Low Volume":      CLR_VERY_LOW,
        "Low Volume":           CLR_LOW,
        "Moderate Volume":      CLR_MODERATE,
        "Below Threshold Volume": CLR_BELOW_THR,
        UNKNOWN:                CLR_UNKNOWN,
    }
    # Find the "Report Volume Category" column index (may vary)
    cat_col = None
    for cell in ws[1]:
        if cell.value == "Report Volume Category":
            cat_col = cell.column
            break

    for row_idx in range(start_row, ws.max_row + 1):
        report_cell = ws[f"{col_letter}{row_idx}"]
        category = ws.cell(row=row_idx, column=cat_col).value if cat_col else None
        colour = colour_map.get(category or "", CLR_WHITE)
        report_cell.fill = PatternFill("solid", fgColor=colour)


def _write_sheet_from_df(wb: Workbook, sheet_name: str, df: pd.DataFrame) -> None:
    """Add a formatted sheet from a DataFrame."""
    ws = wb.create_sheet(title=sheet_name)

    if df.empty:
        ws.append(["No data available."])
        return

    # Write header + rows
    for row in dataframe_to_rows(df, index=False, header=True):
        ws.append(row)

    _apply_styles(ws)
    _auto_width(ws)
    ws.freeze_panes = "A2"

    # Colour-code report column if present
    for cell in ws[1]:
        if cell.value == "Reports Received (90 Days)":
            col_letter = get_column_letter(cell.column)
            _colour_report_cell(ws, col_letter, 2)
            break


def _response_time_df(records: List[ProgramRecord]) -> pd.DataFrame:
    """Build the response-time analysis DataFrame."""
    rows = []
    for r in records:
        rows.append({
            "Program Name":          r.name,
            "HackerOne URL":         r.url,
            "Avg First Response":    r.display_response(r.avg_first_response_h),
            "Avg Triage Time":       r.display_response(r.avg_triage_h),
            "Avg Resolution Time":   r.display_response(r.avg_resolution_h),
            "Avg Time to Bounty":    r.display_response(r.avg_time_to_bounty_h),
            "Response Efficiency":   (
                f"{r.response_efficiency_pct:.1f}%"
                if r.response_efficiency_pct is not None else UNKNOWN
            ),
            "Ranking Score":         f"{r.ranking_score:.2f}",
            "Program Type":          r.program_type,
            "Bounty Available":      "Yes" if r.offers_bounties else "No",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Public export functions
# ---------------------------------------------------------------------------

def export_csv(
    matching_records: List[ProgramRecord],
    unverified_records: Optional[List[ProgramRecord]] = None,
    filepath: Optional[str] = None,
) -> str:
    """
    Export the matching (in-range) programs to a CSV file, with unverified
    (new programs with no 90-day data yet) appended below a separator row.

    Returns the absolute path of the written file.
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = filepath or os.path.join(config.OUTPUT_DIR, config.CSV_FILENAME)

    df = _make_df(matching_records)
    if df.empty:
        log.warning("No matching programs to export to CSV.")
        df = pd.DataFrame(columns=config.REQUIRED_COLUMNS)

    # Append unverified programs below a blank separator row
    unverified_records = unverified_records or []
    if unverified_records:
        sep = pd.DataFrame([{col: ("--- New / No 90-Day Data Yet ---" if col == "Program Name" else "")
                              for col in config.REQUIRED_COLUMNS}])
        unverified_df = _make_df(unverified_records)
        df = pd.concat([df, sep, unverified_df], ignore_index=True)

    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info("CSV exported -> %s (%d rows)", out_path, len(df))
    return out_path


def export_excel(
    matching_records: List[ProgramRecord],
    all_records: List[ProgramRecord],
    data_status_rows: List[Dict[str, Any]],
    unverified_records: Optional[List[ProgramRecord]] = None,
    filepath: Optional[str] = None,
) -> str:
    """
    Export a multi-sheet Excel workbook.

    Sheets:
      1. Matching Programs        (confirmed in [0–40] report range)
      2. New & Unverified Programs (new programs with no 90-day data yet)
      3. All Discovered Programs  (every program discovered)
      4. Response Time Analysis
      5. Data Collection Status

    Returns the absolute path of the written file.
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = filepath or os.path.join(config.OUTPUT_DIR, config.EXCEL_FILENAME)

    wb = Workbook()
    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    # ── Sheet 1: Matching Programs ───────────────────────────────────────
    matching_df = _make_df(matching_records)
    _write_sheet_from_df(wb, config.SHEET_MATCHING, matching_df)
    log.info("Sheet '%s' written (%d rows).", config.SHEET_MATCHING, len(matching_df))

    # ── Sheet 2: New & Unverified Programs ───────────────────────────────
    unverified_records = unverified_records or []
    unverified_df = _make_df(unverified_records)
    _write_sheet_from_df(wb, config.SHEET_UNVERIFIED, unverified_df)
    log.info("Sheet '%s' written (%d rows).", config.SHEET_UNVERIFIED, len(unverified_df))

    # ── Sheet 3: All Discovered Programs ─────────────────────────────────
    all_df = _make_df(all_records)
    _write_sheet_from_df(wb, config.SHEET_ALL, all_df)
    log.info("Sheet '%s' written (%d rows).", config.SHEET_ALL, len(all_df))

    # ── Sheet 4: Response Time Analysis ──────────────────────────────────
    resp_df = _response_time_df(all_records)
    _write_sheet_from_df(wb, config.SHEET_RESPONSE, resp_df)
    log.info("Sheet '%s' written (%d rows).", config.SHEET_RESPONSE, len(resp_df))

    # ── Sheet 5: Data Collection Status ──────────────────────────────────
    status_df = pd.DataFrame(data_status_rows)
    _write_sheet_from_df(wb, config.SHEET_DATA_STATUS, status_df)
    log.info("Sheet '%s' written (%d rows).", config.SHEET_DATA_STATUS, len(status_df))

    wb.save(out_path)
    log.info("Excel workbook exported -> %s", out_path)
    return out_path
