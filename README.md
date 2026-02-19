# US Visa Bulletin Web Scraper

A Python tool to fetch, parse, and track changes in the US State Department Visa Bulletin. Each run is stored in a local SQLite database, and consecutive runs of the same type are automatically compared to surface changes in cutoff dates.

## Overview

This tool automatically:
- Fetches the official US Visa Bulletin webpage
- Parses HTML content to extract visa category data
- Saves structured data to JSON format
- Persists each run to a SQLite database, tagged by run type
- Compares the current run against the previous run of the same type and reports which cutoff dates advanced, retrogressed, or became current

The codebase is organized into modular components:

| File | Purpose |
|---|---|
| **fetch.py** | Main script — HTTP requests, CLI interface, orchestration |
| **parser.py** | HTML parsing and data extraction |
| **persist.py** | JSON file I/O |
| **store.py** | SQLite database — run history and comparison storage |
| **compare.py** | Diff logic — compares two bulletin results |

## Installation

### Prerequisites
- Python 3.7 or higher
- pip

### Setup

```bash
pip install -r requirements.txt
```

No additional packages are required for the database or diff features — `sqlite3` is part of the Python standard library.

## Usage

### Basic run (saves JSON + records in DB)

```bash
python fetch.py
```

### Run with comparison against previous result

```bash
python fetch.py --compare
```

On first run, prints "No previous run found". On subsequent runs, prints a diff showing which categories changed.

### View run history

```bash
python fetch.py --history
```

### Tag a run by type

```bash
python fetch.py --run-type test       # test run — compared only against previous test runs
python fetch.py --run-type benchmark
python fetch.py --run-type official   # default
python fetch.py --run-type manual
```

Each run type maintains its own history. Comparisons are always within the same type.

### JSON-only mode (skip database)

```bash
python fetch.py --no-db
```

### All options

```
-o, --output FILE          Output JSON file path (default: visa_bulletin_data.json)
-t, --timestamp            Add timestamp to output filename
-v, --verbose              Enable verbose logging
--display                  Display extracted data summary after saving
--debug                    Save HTML for inspection if parsing fails
--run-type TYPE            Tag this run: official|test|benchmark|manual (default: official)
--db PATH                  SQLite database file path (default: visa_bulletin.db)
--no-db                    Skip database storage (JSON-only mode)
--compare                  Compare this run against the previous run of the same type
--history                  Print the last 10 runs and exit
-h, --help                 Show help message
```

### Examples

```bash
# Verbose run with comparison
python fetch.py -v --compare

# Save with timestamped filename and display summary
python fetch.py -t --display

# Use a custom DB location
python fetch.py --db /var/data/visa.db --compare

# Test run without touching the official history
python fetch.py --run-type test --no-db
```

## Database

Run history is stored in `visa_bulletin.db` (SQLite, single file).

### Tables

**`runs`** — one row per scraper invocation

| Column | Description |
|---|---|
| `id` | Time-based ID: `YYYYMMDDHHmmSS` + 3-digit seq (e.g. `20260218201515001`) |
| `run_type` | `official` / `test` / `benchmark` / `manual` |
| `started_at` | ISO-8601 UTC timestamp |
| `completed_at` | ISO-8601 UTC timestamp |
| `success` | `1` = success, `0` = failure |
| `bulletin_date` | e.g. `"January 2026"` |
| `source_url` | URL of the fetched bulletin page |
| `data_json` | Full parser output as compact JSON |
| `error_message` | Populated on failure |
| `categories_count` | Number of categories extracted |

**`comparisons`** — one row per diff between two consecutive successful runs of the same type

| Column | Description |
|---|---|
| `id` | Time-based ID (same scheme as `runs.id`) |
| `run_id` | ID of the current run |
| `previous_run_id` | ID of the reference run |
| `has_changes` | `1` if any cutoff date changed |
| `diff_json` | Full structured diff |

### Inspecting the database

```bash
sqlite3 visa_bulletin.db

# Inside sqlite3 shell
.headers on
.mode column
SELECT id, run_type, success, bulletin_date, started_at FROM runs ORDER BY started_at DESC LIMIT 10;
SELECT run_id, previous_run_id, has_changes, compared_at FROM comparisons ORDER BY compared_at DESC LIMIT 5;
.quit
```

## Comparison Output

When `--compare` is used and a previous run exists:

```
============================================================
BULLETIN COMPARISON
============================================================
Previous: January 2026
Current:  February 2026
Compared: 2026-02-18T20:15:15

Changes detected:
  Categories added:    0
  Categories removed:  0
  Categories changed:  2
  Total field changes: 3

  EB-2:
    china: 01 SEP 21 → 01 OCT 21  [ADVANCED]
    india: 01 JUN 13 → 01 JUN 13
  EB-3:
    china: 01 JAN 15 → 01 DEC 14  [RETROGRESSED]
    india: 22 JUN 09 → Current    [BECAME_CURRENT]

============================================================
```

Change directions:
- `ADVANCED` — cutoff date moved forward (good news)
- `RETROGRESSED` — cutoff date moved back
- `BECAME_CURRENT` — changed to "Current" (immediately available)
- `LOST_CURRENT` — was "Current", now a specific date
- `CHANGED` — value changed but dates could not be parsed

## Output JSON Format

```json
{
  "bulletin_date": "January 2026",
  "extracted_at": "2026-01-24T14:30:22.123456",
  "total_categories": 15,
  "categories": [
    {
      "visa_category": "EB-1",
      "preference_level": "Employment-Based",
      "china": "Current",
      "india": "Current",
      "final_action_date": "Current"
    },
    {
      "visa_category": "EB-2",
      "china": "01 SEP 21",
      "india": "01 JUN 13"
    }
  ]
}
```

Dates are formatted as `DD MON YY` (e.g. `"01 JAN 26"`). `"Current"` or `"C"` indicates visa numbers are immediately available.

## Module Reference

### fetch.py
- `scrape_visa_bulletin()` — orchestrates fetch → parse → save → DB record → compare
- `fetch_bulletin_page()` — downloads a page
- `extract_bulletin_url_from_landing_page()` — extracts current bulletin URL
- `create_argument_parser()` — CLI argument definitions

### parser.py
- `parse_bulletin_html()` — main parsing entry point (three-tier fallback strategy)
- `parse_visa_table()` — extracts data from individual HTML tables
- `normalize_header()` — standardizes table header names
- `extract_bulletin_date()` — finds bulletin date in page content

### persist.py
- `save_to_json()` — saves data to a JSON file
- `save_with_timestamp()` — saves with a timestamped filename
- `load_from_json()` — loads previously saved data
- `format_data_for_display()` — formats data for terminal output

### store.py
- `init_db()` — creates tables and indexes (idempotent)
- `insert_run()` — records a run (success or failure)
- `get_last_successful_run()` — retrieves the most recent successful run by type
- `insert_comparison()` — stores a diff result
- `get_runs()` — lists runs with optional filtering

### compare.py
- `compare_bulletins()` — diffs two parsed bulletin dicts
- `format_comparison_for_display()` — renders diff as human-readable text

## Running Tests

```bash
# Run all tests
python tests/run_tests.py

# Run a specific test file
python -m unittest tests.test_store
python -m unittest tests.test_compare
python -m unittest tests.test_fetch
python -m unittest tests.test_parser
python -m unittest tests.test_persist
python -m unittest tests.test_e2e

# Run with verbose output
python tests/run_tests.py -v
```

The test suite covers 152 tests across all modules. Tests use temporary files and mocks — no network access or real database is required.

## Error Handling

The scraper handles errors at every stage:
- Network failures, timeouts, HTTP errors
- HTML parsing failures (three fallback strategies)
- File I/O errors
- Database errors (DB failures do not abort the main scrape)

Failed runs are still recorded in the database with `success=0` and an `error_message`. Use `-v` for detailed logging.

## Dependencies

- **requests** — HTTP client
- **beautifulsoup4** — HTML parser
- **lxml** — fast HTML parsing backend (used by beautifulsoup4)
- **sqlite3** — database (Python standard library, no installation needed)

## Notes

- The scraper uses a standard browser User-Agent and 30-second timeout
- WAL mode is enabled on the SQLite database for safe concurrent reads
- `persist.py` JSON functions remain available for JSON-only workflows
