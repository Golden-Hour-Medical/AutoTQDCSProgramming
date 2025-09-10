#!/usr/bin/env python3
"""
CSV Metric Aggregator

Purpose:
- Scan a folder of CSV files exported from device tests (like the screenshot provided).
- Extract numeric values from the "Actual" column for each metric/row.
- Identify the unit/device ID per file from the header cell (first row, first column) or a column named
  "Device" / "Unit" if present.
- Produce one output CSV per metric containing two columns: UnitID, Value.
- Also produce a summary index CSV listing all metrics and the path to each metric CSV.

Usage:
  python csv_aggregate_metrics.py --input <folder_with_csvs> --output <output_folder>

Notes:
- The tool is tolerant to minor header name variations: it tries to find the "Actual" column by
  case-insensitive match among ["Actual", "Value", "Measured"].
- The metric name is read from the first column of each data row (e.g., "Pump", "Valve", ...).
- Non-numeric or empty values in the target column are skipped.
- Commas/quotes are handled using Python's csv module.

This script is intentionally verbose and clear for maintainability.
"""

import argparse
import csv
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def guess_unit_id_from_header(rows: List[List[str]]) -> Optional[str]:
    """
    Attempt to extract a unit/device ID from the CSV content.

    Heuristics:
    - If the first row, first cell contains something like "Device" or an identifier
      (e.g., "Device Bas 28:37:2F:8D:63:54"), return the trailing token(s).
    - If a header row includes a column named "Device", "Unit", or "Serial", take the
      value from the first data row in that column.
    """
    if not rows:
        return None

    # 1) First row, first cell heuristic
    first_cell = (rows[0][0] or "").strip() if rows[0] else ""
    if first_cell:
        # If it contains MAC-like or ID-like suffix, pick the last whitespace-separated token
        parts = first_cell.split()
        if len(parts) >= 2:
            candidate = parts[-1].strip()
            # Basic sanity: prefer strings containing ':' or hex-like
            if any(c in candidate for c in [":", "-"]) or all(ch in "0123456789ABCDEFabcdef" for ch in candidate):
                return candidate

    # 2) Look for explicit columns in header
    header = [h.strip() for h in rows[0]]
    col_name_to_idx = {h.lower(): i for i, h in enumerate(header)}
    for key in ["device", "unit", "serial", "device id", "unit id", "mac", "mac address"]:
        if key in col_name_to_idx and len(rows) > 1:
            idx = col_name_to_idx[key]
            value = (rows[1][idx] if idx < len(rows[1]) else "").strip()
            if value:
                return value

    return None


def find_column_index(header: List[str], candidates: List[str]) -> Optional[int]:
    """Find a column index in header by case-insensitive name among candidates.

    Tries exact match first, then substring fuzzy match (e.g., "Actual Value").
    """
    norm = [str(h).strip().lower() for h in header]
    lookup = {h: i for i, h in enumerate(norm)}

    # 1) exact
    for name in candidates:
        key = name.lower().strip()
        if key in lookup:
            return lookup[key]

    # 2) fuzzy contains
    for i, h in enumerate(norm):
        for name in candidates:
            key = name.lower().strip()
            if key and key in h:
                return i

    return None


def parse_float(value: str) -> Optional[float]:
    """Try to parse a string as float; return None if not numeric."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Remove common units if embedded (e.g., "mmHg", "mA", "dBm", "uA", "dB")
    # Keep leading sign and digits/decimal/exp; strip trailing non-numeric characters.
    # Example: "291.718 mA" -> "291.718"
    cleaned = ""
    allowed = set("0123456789+-eE.")
    for ch in text:
        if ch in allowed:
            cleaned += ch
        else:
            # stop at first non-allowed char after we've seen a digit
            if cleaned:
                break
    try:
        return float(cleaned)
    except Exception:
        return None


def _read_rows_with_sniffer(csv_path: Path) -> Optional[List[List[str]]]:
    """Read a delimited text file using csv.Sniffer to handle CSV/TSV variations."""
    # Try utf-8-sig first, then latin-1
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = csv_path.read_text(encoding=encoding)
        except Exception:
            continue

        try:
            sample = text[:4096]
            sniffer = csv.Sniffer()
            # Prefer among common delimiters
            dialect = sniffer.sniff(sample, delimiters=",\t;|")
            reader = csv.reader(text.splitlines(), dialect)
            return [row for row in reader]
        except Exception:
            # Fallback: if tabs present but only one column when read with default
            if "\t" in text:
                reader = csv.reader(text.splitlines(), delimiter='\t')
                try:
                    return [row for row in reader]
                except Exception:
                    pass
            # Final fallback: comma
            try:
                reader = csv.reader(text.splitlines(), delimiter=',')
                return [row for row in reader]
            except Exception:
                pass
    return None


def _detect_header_row_index(rows: List[List[str]]) -> Optional[int]:
    """Detect which row is the header by looking for common column names like 'Actual'."""
    max_scan = min(20, len(rows))
    # First, prefer rows containing 'actual'
    for i in range(max_scan):
        lowered = [str(c).strip().lower() for c in rows[i]]
        if any("actual" in c for c in lowered) and sum(1 for c in lowered if c) >= 2:
            return i
    # Next, look for row that contains multiple of these labels
    keywords = {"peripheral", "unit", "result", "min", "typ", "max"}
    for i in range(max_scan):
        lowered = [str(c).strip().lower() for c in rows[i]]
        matches = sum(1 for c in lowered if any(k in c for k in keywords))
        if matches >= 2:
            return i
    # Fallback: first non-empty row with >=2 cells
    for i in range(max_scan):
        if rows[i] and sum(1 for c in rows[i] if str(c).strip()) >= 2:
            return i
    return None


def aggregate_metrics(input_dir: Path, output_dir: Path) -> Tuple[Dict[str, List[Tuple[str, float]]], List[Path]]:
    """
    Read all CSV files in input_dir and build a mapping:
        metric_name -> list of (unit_id, value)

    Returns the metrics mapping and a list of CSV files processed.
    """
    metrics: Dict[str, List[Tuple[str, float]]] = {}
    processed_files: List[Path] = []

    for csv_path in sorted(input_dir.glob("*.csv")):
        rows = _read_rows_with_sniffer(csv_path)
        if rows is None:
            continue

        if not rows:
            continue

        processed_files.append(csv_path)

        # Determine unit ID
        unit_id = guess_unit_id_from_header(rows) or csv_path.stem

        # Identify header row: prefer the row containing 'Actual'
        header_row_idx = _detect_header_row_index(rows)
        if header_row_idx is None:
            continue

        header = rows[header_row_idx]
        # Locate column indexes
        name_col_idx = 0  # metric name column: commonly first column
        actual_col_idx = find_column_index(header, ["Actual", "Actual Value", "Value", "Measured", "Measured Value"]) or None

        # If still not found, try to infer relative to 'Max' column (Actual typically follows Max)
        if actual_col_idx is None:
            max_idx = find_column_index(header, ["Max"]) or None
            if max_idx is not None:
                # Prefer the immediate next column if it exists
                if max_idx + 1 < len(header):
                    next_header = str(header[max_idx + 1]).strip().lower()
                    if "actual" in next_header or not next_header:
                        actual_col_idx = max_idx + 1
                # If not determined, scan to the right for a header containing 'actual'
                if actual_col_idx is None:
                    for j in range(max_idx + 1, len(header)):
                        if "actual" in str(header[j]).strip().lower():
                            actual_col_idx = j
                            break

        # If we still cannot find an Actual column, skip this file to avoid misreading 'Max'
        if actual_col_idx is None:
            continue

        # Data rows start after header
        for row in rows[header_row_idx + 1:]:
            if not row or all(not str(c).strip() for c in row):
                continue

            metric_name = (row[name_col_idx] if name_col_idx < len(row) else "").strip()
            if not metric_name:
                continue

            if actual_col_idx is None or actual_col_idx >= len(row):
                continue

            numeric = parse_float(row[actual_col_idx])
            if numeric is None:
                continue

            metrics.setdefault(metric_name, []).append((unit_id, numeric))

    return metrics, processed_files


def write_metric_csvs(metrics: Dict[str, List[Tuple[str, float]]], output_dir: Path) -> Path:
    """Write one CSV per metric: columns = UnitID, Value. Also create an index CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "metrics_index.csv"

    with index_path.open("w", newline="", encoding="utf-8") as idx_f:
        idx_writer = csv.writer(idx_f)
        idx_writer.writerow(["Metric", "OutputCSV", "Count"])

        for metric_name, entries in sorted(metrics.items()):
            safe_name = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in metric_name)
            metric_csv = output_dir / f"metric_{safe_name}.csv"

            with metric_csv.open("w", newline="", encoding="utf-8") as mf:
                w = csv.writer(mf)
                w.writerow(["UnitID", "Value"])
                for unit_id, value in entries:
                    w.writerow([unit_id, value])

            idx_writer.writerow([metric_name, str(metric_csv.name), len(entries)])

    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate per-metric Actual values across CSV files.")
    parser.add_argument("--input", "-i", required=True, help="Folder containing input CSV files")
    parser.add_argument("--output", "-o", default="aggregated_metrics", help="Output folder for metric CSVs")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"❌ Input directory not found: {input_dir}")
        return 1

    metrics, files = aggregate_metrics(input_dir, output_dir)

    if not files:
        print("❌ No CSV files found to process.")
        return 1

    if not metrics:
        print("⚠️ No numeric 'Actual' values found. Nothing to write.")
        return 2

    index_path = write_metric_csvs(metrics, output_dir)
    print(f"✅ Wrote {len(metrics)} metric CSVs. Index: {index_path}")
    print("Tip: Plot each metric CSV with UnitID on X-axis and Value on Y-axis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


