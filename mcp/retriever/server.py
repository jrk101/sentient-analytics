"""
Retriever MCP Server v2
Fixes:
- Indexes the FULL document (not just first 8000 chars) by chunking each file
- Adds find_historical_tables() to locate summary tables that cover a year range
- BM25 over chunks with doc-level dedup on results
"""

import os
import re
import json
from pathlib import Path
from typing import Optional
from fastmcp import FastMCP

mcp = FastMCP("treasury-retriever")

CORPUS_DIR = Path("/app/corpus")
INDEX_FILE = CORPUS_DIR / "index.txt"

# ---------------------------------------------------------------------------
# Index state
# ---------------------------------------------------------------------------
_index_built = False
_doc_paths: list[Path] = []
_chunks: list[str] = []          # one entry per chunk
_chunk_to_doc: list[int] = []    # chunk index → doc index in _doc_paths
_bm25 = None

CHUNK_SIZE = 6000    # chars per chunk
CHUNK_OVERLAP = 500  # overlap between chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _get_all_paths() -> list[Path]:
    paths: list[Path] = []
    if INDEX_FILE.exists():
        for line in INDEX_FILE.read_text().splitlines():
            p = Path(line.strip())
            if p.suffix == ".txt" and p.exists():
                paths.append(p)
    else:
        paths = sorted(CORPUS_DIR.glob("treasury_bulletin_*.txt"))
    return paths


def _ensure_index():
    global _index_built, _doc_paths, _chunks, _chunk_to_doc, _bm25
    if _index_built:
        return

    from rank_bm25 import BM25Okapi

    _doc_paths = _get_all_paths()
    all_chunk_tokens: list[list[str]] = []

    for doc_idx, p in enumerate(_doc_paths):
        try:
            text = p.read_text(errors="replace")
        except Exception:
            text = ""

        # Chunk the full document
        step = CHUNK_SIZE - CHUNK_OVERLAP
        for start in range(0, max(1, len(text)), step):
            chunk = text[start: start + CHUNK_SIZE]
            if not chunk.strip():
                continue
            _chunks.append(chunk)
            _chunk_to_doc.append(doc_idx)
            all_chunk_tokens.append(_tokenize(chunk))

    _bm25 = BM25Okapi(all_chunk_tokens)
    _index_built = True


def _extract_year_month(p: Path) -> tuple[Optional[int], Optional[int]]:
    m = re.search(r"treasury_bulletin_(\d{4})_(\d{2})", p.name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_corpus(query: str, top_k: int = 6) -> str:
    """
    BM25 full-text search over ALL content of every Treasury Bulletin.
    Searches the complete text of all 697 documents (not just headers).
    Returns top matching documents with file paths and relevant snippets.

    Args:
        query: Search query (e.g. "national defense expenditures calendar year 1940")
        top_k: Number of top documents to return (default 6)

    Returns:
        JSON list of {file_path, year, month, score, snippet}
    """
    _ensure_index()
    import heapq

    tokens = _tokenize(query)
    scores = _bm25.get_scores(tokens)

    # Get top-K chunks, then deduplicate to unique docs
    n_chunks = len(_chunks)
    top_chunk_indices = heapq.nlargest(top_k * 4, range(n_chunks), key=lambda i: scores[i])

    seen_docs: set[int] = set()
    results = []
    for chunk_idx in top_chunk_indices:
        doc_idx = _chunk_to_doc[chunk_idx]
        if doc_idx in seen_docs:
            continue
        seen_docs.add(doc_idx)

        p = _doc_paths[doc_idx]
        year, month = _extract_year_month(p)
        chunk_text = _chunks[chunk_idx]

        # Find best snippet inside chunk
        snippet = chunk_text[:500]
        for tok in tokens:
            pos = chunk_text.lower().find(tok)
            if pos != -1:
                start = max(0, pos - 100)
                snippet = chunk_text[start: start + 500]
                break

        results.append({
            "file_path": str(p),
            "year": year,
            "month": month,
            "score": round(float(scores[chunk_idx]), 3),
            "snippet": snippet.strip(),
        })
        if len(results) >= top_k:
            break

    return json.dumps(results, indent=2)


@mcp.tool()
def list_bulletins_for_years(start_year: int, end_year: int) -> str:
    """
    List all bulletin file paths covering a range of years.

    Args:
        start_year: First year inclusive
        end_year: Last year inclusive

    Returns:
        JSON list of {file_path, year, month}
    """
    _ensure_index()
    results = []
    for p in _doc_paths:
        year, month = _extract_year_month(p)
        if year is not None and start_year <= year <= end_year:
            results.append({"file_path": str(p), "year": year, "month": month})
    results.sort(key=lambda x: (x["year"], x["month"] or 0))
    return json.dumps(results, indent=2)


@mcp.tool()
def read_document(file_path: str, max_chars: int = 25000) -> str:
    """
    Read a bulletin document's full text.

    Args:
        file_path: Absolute path to the .txt file
        max_chars: Max characters to return (default 25000). Use a higher number if data is cut off.

    Returns:
        Document text with markdown tables
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    total = len(text)
    if total > max_chars:
        return text[:max_chars] + f"\n\n... [TRUNCATED — showed {max_chars}/{total} chars. Call again with higher max_chars or use search_in_document] ..."
    return text


@mcp.tool()
def search_in_document(file_path: str, keyword: str, context_chars: int = 1000) -> str:
    """
    Find all occurrences of a keyword within a specific document and return surrounding text.

    Args:
        file_path: Path to the bulletin .txt file
        keyword: Keyword to find (case-insensitive)
        context_chars: Characters of context per match (default 1000)

    Returns:
        JSON with list of {position, context} matches
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    text = p.read_text(errors="replace")
    lower = text.lower()
    lower_kw = keyword.lower()

    matches = []
    start = 0
    while len(matches) < 8:
        pos = lower.find(lower_kw, start)
        if pos == -1:
            break
        ctx_start = max(0, pos - 200)
        ctx_end = min(len(text), pos + context_chars)
        matches.append({"position": pos, "context": text[ctx_start:ctx_end]})
        start = pos + len(lower_kw)

    return json.dumps({"keyword": keyword, "total_matches": len(matches), "matches": matches}, indent=2)


@mcp.tool()
def find_historical_tables(keyword: str, target_start_year: int, target_end_year: int, max_results: int = 5) -> str:
    """
    Find documents that contain BOTH a financial keyword AND data covering a target year range.
    This is crucial because Treasury bulletins often republish multi-year historical tables.
    For example, a 1954 bulletin may contain ALL monthly national defense data for 1940-1953.

    Use this when:
    - You need data for a year but the bulletin from that year doesn't have good detail
    - You need a range of years in one place (geometric mean, regression, etc.)
    - You want to verify values across multiple sources

    Args:
        keyword: Financial category keyword (e.g. "national defense", "income tax", "net interest")
        target_start_year: First year you need data for
        target_end_year: Last year you need data for
        max_results: Max files to return (default 5)

    Returns:
        JSON list of {file_path, bulletin_year, score, has_both_years, snippet}
    """
    _ensure_index()
    import heapq

    # Build a query that combines keyword + year range signals
    year_tokens = []
    for y in range(target_start_year, min(target_end_year + 1, target_start_year + 5)):
        year_tokens.append(str(y))

    combined_query = f"{keyword} {' '.join(year_tokens)}"
    tokens = _tokenize(combined_query)
    scores = _bm25.get_scores(tokens)

    # Get top chunks, dedup by doc
    top_indices = heapq.nlargest(max_results * 6, range(len(_chunks)), key=lambda i: scores[i])

    seen: set[int] = set()
    results = []

    for chunk_idx in top_indices:
        doc_idx = _chunk_to_doc[chunk_idx]
        if doc_idx in seen:
            continue
        seen.add(doc_idx)

        p = _doc_paths[doc_idx]
        bulletin_year, _ = _extract_year_month(p)

        # Check whether this document actually contains the target years
        try:
            full_text = p.read_text(errors="replace")
        except Exception:
            full_text = ""

        has_start = str(target_start_year) in full_text
        has_end = str(target_end_year) in full_text
        has_keyword = keyword.lower() in full_text.lower()

        if not (has_keyword and (has_start or has_end)):
            continue

        # Extract a snippet near keyword+year
        snippet = ""
        for tok in [keyword.lower(), str(target_start_year), str(target_end_year)]:
            pos = full_text.lower().find(tok)
            if pos != -1:
                s = max(0, pos - 100)
                snippet = full_text[s: s + 600]
                break

        results.append({
            "file_path": str(p),
            "bulletin_year": bulletin_year,
            "score": round(float(scores[chunk_idx]), 3),
            "has_start_year": has_start,
            "has_end_year": has_end,
            "has_keyword": has_keyword,
            "snippet": snippet.strip(),
        })

        if len(results) >= max_results:
            break

    results.sort(key=lambda x: (-(1 if x["has_start_year"] and x["has_end_year"] else 0), -x["score"]))
    return json.dumps(results, indent=2)


@mcp.tool()
def get_corpus_info() -> str:
    """Get corpus statistics: total documents, year range, sample filenames."""
    _ensure_index()
    years = [_extract_year_month(p)[0] for p in _doc_paths]
    years = [y for y in years if y]
    return json.dumps({
        "total_documents": len(_doc_paths),
        "total_chunks_indexed": len(_chunks),
        "year_range": [min(years), max(years)] if years else [],
        "corpus_dir": str(CORPUS_DIR),
        "sample_files": [p.name for p in _doc_paths[:5]],
    }, indent=2)
