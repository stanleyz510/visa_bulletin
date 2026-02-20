# US Visa Bulletin Web Scraper

A Python tool to fetch, parse, track changes in, and send email notifications for the US State Department Visa Bulletin. Each run is stored in a local SQLite database, and consecutive runs of the same type are automatically compared to surface changes in cutoff dates.

## Overview

This tool automatically:
- Fetches the official US Visa Bulletin webpage
- Parses HTML content to extract visa category data
- Saves structured data to JSON format
- Persists each run to a SQLite database, tagged by run type
- Compares the current run against the previous run of the same type and reports which cutoff dates advanced, retrogressed, or became current
- Sends email notifications to subscribers via AWS SES

The codebase is organized into modular components:

| File | Purpose |
|---|---|
| **main.py** | Full pipeline — fetch → compare → notify (production entry point) |
| **fetch.py** | HTTP scraping, HTML fetching, standalone manual runs |
| **parser.py** | HTML parsing and data extraction |
| **persist.py** | JSON file I/O |
| **store.py** | SQLite database — run history, comparisons, and subscriptions |
| **compare.py** | Diff logic — compares two bulletin results |
| **notify.py** | Email notifications via AWS SES, with local preview mode |
| **app.py** | Flask web app — subscription management UI |
| **static/email_body.html** | Jinja2 template for the notification email body |
| **static/email_preview.html** | Jinja2 template for the browser preview wrapper |

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

### Full pipeline (recommended for production)

```bash
python main.py
```

This runs the complete pipeline: fetches the current bulletin as an `official` run, compares it against the previous official run, and notifies subscribers via email.

```bash
python main.py --no-notify         # Fetch + compare only, skip email
python main.py --updated-only      # Only email subscribers whose categories changed
python main.py --print-local       # Save email previews as HTML instead of sending
python main.py -v --print-local    # Verbose + local preview (useful before SES is set up)
```

### Manual fetch (standalone)

```bash
python fetch.py                    # Manual scrape (run_type=manual)
python fetch.py -v --display       # Verbose with summary output
python fetch.py --compare          # Also compare against previous manual run
python fetch.py --history          # Show last 10 runs and exit
```

### Send / preview emails (standalone)

```bash
# Preview an email locally (no SES required)
python notify.py user@email.com --print-local

# Send a test email via SES
python notify.py user@email.com

# Notify all active subscribers
python notify.py --all

# Notify only subscribers whose categories changed
python notify.py --all --updated-only

# Preview all subscriber emails locally
python notify.py --all --print-local
```

Local previews are saved as `email_preview_<email>_<timestamp>.html` in the current directory and can be opened directly in a browser.

### Tag a run by type

```bash
python fetch.py --run-type test       # test run — compared only against previous test runs
python fetch.py --run-type benchmark
python fetch.py --run-type manual     # default for fetch.py standalone
```

Each run type maintains its own history. Comparisons are always within the same type.

### Database management (store.py)

Inspect run history and subscriptions directly without opening a sqlite3 shell:

```bash
# List runs
python store.py runs                           # last 20 runs (all types)
python store.py runs --type official           # filter by run type
python store.py runs --limit 50               # custom limit
python store.py runs --success-only           # only successful runs
python store.py runs --deleted                # include soft-deleted runs

# Inspect a specific run
python store.py run 20260218201515001         # show metadata + full bulletin data

# Soft-delete a run (marks is_deleted=1; data is preserved)
python store.py delete 20260218201515001

# List subscribers
python store.py subscribers                   # last 20 active subscribers
python store.py subscribers --all             # include inactive
python store.py subscribers --limit 50

# Custom database path
python store.py --db /path/to/other.db runs
```

Soft-deleted runs are hidden from normal listings and are skipped during comparison
(`get_last_successful_run` ignores them). They can be revealed with `--deleted` and
their data is never removed from the database.

### JSON-only mode (skip database)

```bash
python fetch.py --no-db
```

### All options — fetch.py

```
-o, --output FILE          Output JSON file path (default: visa_bulletin_data.json)
-t, --timestamp            Add timestamp to output filename
-v, --verbose              Enable verbose logging
--display                  Display extracted data summary after saving
--debug                    Save HTML for inspection if parsing fails
--run-type TYPE            Tag this run: official|test|benchmark|manual (default: manual)
--db PATH                  SQLite database file path (default: visa_bulletin.db)
--no-db                    Skip database storage (JSON-only mode)
--compare                  Compare this run against the previous run of the same type
--history                  Print the last 10 runs and exit
-h, --help                 Show help message
```

### All options — main.py

```
--db PATH                  SQLite database file path (default: visa_bulletin.db)
--no-notify                Skip email notification step
--updated-only             Only notify subscribers whose categories changed
--print-local              Save email previews as HTML instead of sending via SES
-v, --verbose              Enable verbose logging
-o, --output FILE          Output JSON file path (default: visa_bulletin_data.json)
```

### All options — notify.py

```
email                      Email address for test send (positional, optional)
--all                      Notify all active subscribers
--updated-only             (with --all) Only notify on changes
--print-local              Save emails locally instead of sending via SES
--db PATH                  SQLite database file path (default: visa_bulletin.db)
```

## Notification System

Email notifications are sent via AWS SES. Configure using environment variables:

| Variable | Required | Description |
|---|---|---|
| `SES_FROM_EMAIL` | Yes | Verified sender address in SES |
| `SES_REGION` | No | AWS region (default: `us-east-1`) |
| `AWS_ACCESS_KEY_ID` | No* | AWS credentials (not needed with IAM roles) |
| `AWS_SECRET_ACCESS_KEY` | No* | AWS credentials (not needed with IAM roles) |
| `APP_BASE_URL` | No | Base URL for unsubscribe links (default: `http://localhost:5000`) |

\* Standard AWS credential chain (environment, `~/.aws/credentials`, IAM role) is respected automatically.

Until SES is configured, use `--print-local` to preview email formatting locally:

```bash
# Preview what a notification would look like
python main.py --print-local --no-notify  # fetch + compare, save previews
python notify.py user@email.com --print-local  # test email preview
```

### How notification targeting works

The `updated_only` flag controls who receives notifications:

- `updated_only=True` (default with `--updated-only`): only subscribers whose subscribed categories changed receive an email
- `updated_only=False` (default): all active subscribers receive an email; the subject and body indicate whether their categories changed

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
| `is_deleted` | `1` = soft-deleted (hidden from normal queries, data preserved) |

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

### main.py
- `main()` — full pipeline: fetch (official run) → compare → store comparison → notify

### fetch.py
- `scrape_visa_bulletin()` — fetches, parses, saves JSON, records in DB; returns `(success, run_id, data)`
- `fetch_bulletin_page()` — downloads a page
- `extract_bulletin_url_from_landing_page()` — extracts current bulletin URL
- `create_argument_parser()` — CLI argument definitions

### notify.py
- `notify_subscribers()` — dispatches emails to all relevant active subscribers
- `send_test_email()` — sends a test email to a given address (bypasses subscription check)
- `build_email_html()` — renders `static/email_body.html` with subscriber and bulletin data
- `build_email_subject()` — builds the subject line
- `send_email_ses()` — sends via AWS SES (placeholder until SES is configured)
- `print_email_local()` — renders `static/email_preview.html` and saves it for browser preview

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
- `init_db()` — creates tables and indexes (idempotent); migrates `is_deleted` on existing databases
- `insert_run()` — records a run (success or failure)
- `get_last_successful_run()` — retrieves the most recent non-deleted successful run by type
- `get_run_by_id()` — retrieves a specific run by ID (including deleted)
- `soft_delete_run()` — marks a run as deleted (`is_deleted=1`); data is preserved
- `insert_comparison()` — stores a diff result
- `get_runs()` — lists runs with optional type/success/deleted filtering
- `get_subscriptions()` — lists subscriptions with optional active-only filtering
- `upsert_subscription()` — creates or updates a subscription
- `get_active_subscriptions_for_category()` — finds subscribers for a category
- `deactivate_subscription()` — unsubscribes via token
- `main()` — CLI entry point (`python store.py runs|run|delete|subscribers`)

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
python -m unittest tests.test_notify
python -m unittest tests.test_main
python -m unittest tests.test_e2e

# Run with verbose output
python tests/run_tests.py -v
```

The test suite covers 180+ tests across all modules. Tests use temporary files and mocks — no network access, real database, or AWS credentials are required.

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
- **flask** — web framework for the subscription UI
- **boto3** — AWS SDK for SES email sending (gracefully disabled if not installed)
- **sqlite3** — database (Python standard library, no installation needed)

## Notes

- The scraper uses a standard browser User-Agent and 30-second timeout
- WAL mode is enabled on the SQLite database for safe concurrent reads
- `persist.py` JSON functions remain available for JSON-only workflows
