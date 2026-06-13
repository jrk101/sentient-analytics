"""
Table Parser MCP Server v2
Fixes:
- Year carry-forward logic: rows like 'January', 'February' inherit year from preceding '1940-January' row
- Resolved row labels: every row gets a fully-qualified label like '1940-March'
- Better multi-level header flattening
"""

import re
import json
from pathlib import Path
from typing import Optional
from fastmcp import FastMCP

mcp = FastMCP("treasury-table-parser")

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
MONTH_NAME_TO_NUM = {m: i + 1 for i, m in enumerate(MONTH_NAMES)}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_pipe_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|[\s\-|]+\|\s*$", line))


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) > 4


def _flatten_header(cell: str) -> str:
    """Collapse 'A > Unnamed: 0 > B' → 'A > B', drop all Unnamed segments."""
    parts = [p.strip() for p in cell.split(">")]
    meaningful = [p for p in parts if not re.match(r"^[Uu]nnamed:", p) and p.lower() != "nan"]
    return " > ".join(meaningful) if meaningful else cell.strip()


def _parse_number(val: str) -> Optional[float]:
    if not val or val.strip() in ("", "-", "nan", "—", "N/A", "n.a.", "*", "4/", "1/", "2/", "3/"):
        return None
    cleaned = re.sub(r"[,$%\s]", "", val.strip())
    # Remove footnote markers like 1/, 2/ at the end
    cleaned = re.sub(r"\d+/$", "", cleaned)
    cleaned = cleaned.replace("(", "-").replace(")", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_year_month_in_label(label: str) -> tuple[Optional[int], Optional[int]]:
    """
    Try to extract (year, month_num) from a row label.
    Handles:
      '1940-January' → (1940, 1)
      '1940-Jan'     → (1940, 1)
      'January'      → (None, 1)   ← year must be carried forward
      'February'     → (None, 2)
      '1940'         → (1940, None) ← fiscal/calendar year row
      'Fiscal year 1940' → (1940, None)
      '1940 (Estimated)' → (1940, None)
    """
    label_lower = label.lower().strip()

    # Pattern: YYYY-MonthName or YYYY-Mon
    m = re.search(r"(\d{4})[-\s]+(january|february|march|april|may|june|july|august|september|october|november|december)", label_lower)
    if m:
        return int(m.group(1)), MONTH_NAME_TO_NUM[m.group(2)]

    # Pattern: MonthName only (no year)
    for mn, num in MONTH_NAME_TO_NUM.items():
        if re.search(rf"\b{mn}\b", label_lower):
            return None, num

    # Pattern: bare year
    m = re.search(r"\b(\d{4})\b", label)
    if m:
        return int(m.group(1)), None

    return None, None


def _apply_year_carry_forward(records: list[dict], label_key: str) -> list[dict]:
    """
    For each record, if the row label has a month but no year,
    carry forward the year from the most recent row that had a year.
    Also attach resolved_year and resolved_month to every record.
    """
    current_year: Optional[int] = None
    result = []
    for rec in records:
        label = rec.get(label_key, "")
        year, month = _detect_year_month_in_label(label)

        if year is not None:
            current_year = year  # update running year

        resolved_year = year if year is not None else current_year
        resolved_month = month

        # Build fully-qualified label for month-only rows
        if month is not None and year is None and current_year is not None:
            month_name = MONTH_NAMES[month - 1].capitalize()
            rec["resolved_label"] = f"{current_year}-{month_name}"
        else:
            rec["resolved_label"] = label

        rec["resolved_year"] = resolved_year
        rec["resolved_month"] = resolved_month
        result.append(rec)
    return result


def _extract_tables(text: str) -> list[dict]:
    lines = text.splitlines()
    tables = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_table_row(line) and not _is_separator(line):
            table_start = i
            raw = [line]
            i += 1
            while i < len(lines):
                l = lines[i]
                if _is_table_row(l) or _is_separator(l):
                    raw.append(l)
                    i += 1
                elif l.strip() == "" and i + 1 < len(lines) and (_is_table_row(lines[i + 1]) or _is_separator(lines[i + 1])):
                    raw.append(l)
                    i += 1
                else:
                    break

            header_rows, data_rows = [], []
            for l in raw:
                if _is_separator(l):
                    continue
                cells = _parse_pipe_row(l)
                if not header_rows:
                    header_rows.append(cells)
                else:
                    data_rows.append(cells)

            headers = [_flatten_header(c) for c in (header_rows[0] if header_rows else [])]
            if headers and data_rows:
                tables.append({
                    "headers": headers,
                    "rows": data_rows,
                    "raw_text": "\n".join(raw),
                    "line_start": table_start,
                })
        else:
            i += 1
    return tables


def _table_to_records(table: dict) -> list[dict]:
    headers = table["headers"]
    label_key = headers[0] if headers else "col_0"
    records = []
    for row in table["rows"]:
        rec = {}
        for j, cell in enumerate(row):
            key = headers[j] if j < len(headers) else f"col_{j}"
            rec[key] = cell
        records.append(rec)
    return _apply_year_carry_forward(records, label_key)


def _context_before(text: str, line_start: int, n: int = 8) -> str:
    all_lines = text.splitlines()
    start = max(0, line_start - n)
    return "\n".join(all_lines[start:line_start]).strip()


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def extract_all_tables(file_path: str) -> str:
    """
    List all tables found in a document with their index, headers, row count, and section context.
    Use this to identify which table to read in detail.

    Args:
        file_path: Path to the bulletin .txt file

    Returns:
        JSON list of tables with index, context, headers, row_count, sample_rows
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    tables = _extract_tables(text)

    summaries = []
    for idx, t in enumerate(tables):
        ctx = _context_before(text, t["line_start"])
        summaries.append({
            "table_index": idx,
            "context_before": ctx[-300:],
            "headers": t["headers"],
            "row_count": len(t["rows"]),
            "sample_rows": t["rows"][:3],
        })
    return json.dumps({"file_path": file_path, "total_tables": len(tables), "tables": summaries}, indent=2)


@mcp.tool()
def extract_table_by_index(file_path: str, table_index: int) -> str:
    """
    Extract a complete table by index, with year carry-forward applied.
    Every row will have 'resolved_label', 'resolved_year', and 'resolved_month' added.
    This means rows like 'February' will show resolved_year=1940 if the preceding row was '1940-January'.

    Args:
        file_path: Path to the bulletin .txt file
        table_index: 0-based index from extract_all_tables

    Returns:
        JSON with headers and all records (including resolved_year/month)
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    tables = _extract_tables(text)

    if not (0 <= table_index < len(tables)):
        return json.dumps({"error": f"table_index {table_index} out of range (0–{len(tables)-1})"})

    t = tables[table_index]
    ctx = _context_before(text, t["line_start"])
    records = _table_to_records(t)

    return json.dumps({
        "table_index": table_index,
        "context_before": ctx[-400:],
        "headers": t["headers"],
        "total_rows": len(records),
        "records": records,
    }, indent=2)


@mcp.tool()
def find_tables_with_keyword(file_path: str, keyword: str) -> str:
    """
    Find all tables in a document whose headers or surrounding context contain a keyword.

    Args:
        file_path: Path to the bulletin .txt file
        keyword: Case-insensitive keyword (e.g. 'national defense', 'net interest', 'income tax')

    Returns:
        JSON with matching tables (index, context, headers, sample rows)
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    tables = _extract_tables(text)
    lower_kw = keyword.lower()

    matches = []
    for idx, t in enumerate(tables):
        ctx = _context_before(text, t["line_start"])
        header_str = " ".join(t["headers"]).lower()
        raw_preview = t["raw_text"][:800].lower()
        if lower_kw in header_str or lower_kw in ctx.lower() or lower_kw in raw_preview:
            matches.append({
                "table_index": idx,
                "context_before": ctx[-400:],
                "headers": t["headers"],
                "row_count": len(t["rows"]),
                "sample_rows": t["rows"][:5],
            })
    return json.dumps({"keyword": keyword, "matches_found": len(matches), "matching_tables": matches}, indent=2)


@mcp.tool()
def extract_rows_for_year_month(
    file_path: str,
    table_index: int,
    year: Optional[int] = None,
    month: Optional[int] = None,
    col_hint: Optional[str] = None,
) -> str:
    """
    Extract rows from a table filtered by year and/or month, with year carry-forward applied.
    Returns only matching rows with numeric values parsed.

    Use this for:
    - All monthly rows for year 1953: year=1953, month=None
    - A specific month: year=1940, month=1 (January)
    - A range of months: call multiple times or extract full table and filter manually

    Args:
        file_path: Path to the bulletin .txt file
        table_index: Table index from find_tables_with_keyword or extract_all_tables
        year: Filter by resolved year (None = all years)
        month: Filter by resolved month number 1-12 (None = all months)
        col_hint: Optional column keyword to filter columns (e.g. 'defense', 'total')

    Returns:
        JSON with matching rows including resolved labels and parsed numeric values
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    tables = _extract_tables(text)

    if not (0 <= table_index < len(tables)):
        return json.dumps({"error": f"table_index {table_index} out of range"})

    t = tables[table_index]
    headers = t["headers"]
    records = _table_to_records(t)

    # Filter by year/month
    filtered = []
    for rec in records:
        ry = rec.get("resolved_year")
        rm = rec.get("resolved_month")
        if year is not None and ry != year:
            continue
        if month is not None and rm != month:
            continue
        filtered.append(rec)

    # Filter columns
    target_cols = headers
    if col_hint:
        target_cols = [h for h in headers if col_hint.lower() in h.lower()] or headers

    results = []
    for rec in filtered:
        row_result = {
            "resolved_label": rec.get("resolved_label", ""),
            "resolved_year": rec.get("resolved_year"),
            "resolved_month": rec.get("resolved_month"),
            "values": {},
        }
        for col in target_cols:
            raw = rec.get(col, "")
            row_result["values"][col] = {
                "raw": raw,
                "numeric": _parse_number(raw),
            }
        results.append(row_result)

    return json.dumps({
        "table_index": table_index,
        "year_filter": year,
        "month_filter": month,
        "col_hint": col_hint,
        "total_matching_rows": len(results),
        "rows": results,
    }, indent=2)


@mcp.tool()
def extract_section_text(file_path: str, section_keyword: str, max_chars: int = 3000) -> str:
    """
    Return raw text around a keyword in the document.
    Fallback for when data is in prose rather than a table.

    Args:
        file_path: Path to bulletin .txt file
        section_keyword: Keyword to locate the section
        max_chars: Characters to return around the match (default 3000)

    Returns:
        JSON with text section around keyword
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    lower = text.lower()
    pos = lower.find(section_keyword.lower())
    if pos == -1:
        return json.dumps({"error": f"Keyword '{section_keyword}' not found", "file": file_path})
    start = max(0, pos - 300)
    end = min(len(text), pos + max_chars)
    return json.dumps({"section_keyword": section_keyword, "position": pos, "text": text[start:end]}, indent=2)
