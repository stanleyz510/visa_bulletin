#!/usr/bin/env python3
"""
Full pipeline entry point for the Visa Bulletin tracker.

Fetches the current bulletin (as an 'official' run), compares it against the
previous official run, stores the comparison result, and dispatches email
notifications to subscribers.

Usage:
    python main.py                      # Full pipeline: fetch + compare + notify
    python main.py --no-notify          # Fetch and compare only
    python main.py --updated-only       # Only notify subscribers with changes
    python main.py --print-local        # Save email previews instead of sending
    python main.py -v                   # Verbose logging
    python main.py -o output.json       # Custom output JSON file
    python main.py --db /path/to.db     # Custom database path
"""

import argparse
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from store import (
    DEFAULT_DB_PATH,
    get_connection,
    get_last_successful_run,
    init_db,
    insert_comparison,
)
from fetch import scrape_visa_bulletin, DEFAULT_OUTPUT_FILE
from compare import compare_bulletins, format_comparison_for_display
from notify import notify_subscribers, _build_config_from_env, _empty_comparison


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and return the CLI argument parser for main.py."""
    parser = argparse.ArgumentParser(
        description=(
            "Visa Bulletin full pipeline: fetch current bulletin, "
            "compare against previous, and notify subscribers."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                         Full pipeline run (official run type)
  python main.py --no-notify            Fetch + compare only, skip notifications
  python main.py --updated-only         Only notify subscribers with changes
  python main.py --print-local          Preview emails as HTML instead of sending
  python main.py -v --print-local       Verbose + local email preview
        """,
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip email notification step (fetch and compare only)",
    )
    parser.add_argument(
        "--updated-only",
        action="store_true",
        help="Only notify subscribers whose subscribed categories have changes",
    )
    parser.add_argument(
        "--print-local",
        action="store_true",
        help="Save email previews as HTML files instead of sending via SES",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT_FILE})",
    )
    return parser


def main() -> None:
    """Main pipeline: fetch → compare → notify."""
    parser = create_argument_parser()
    args = parser.parse_args()

    try:
        # Step 1: Initialize database
        try:
            init_db(args.db, verbose=args.verbose)
        except Exception as e:
            print(f"[MAIN] Warning: could not initialize database: {e}")

        # Step 2: Capture the PREVIOUS official run BEFORE fetching the new one.
        # This ensures we compare the new run against the truly prior bulletin.
        previous_run: Optional[Dict[str, Any]] = None
        try:
            with get_connection(args.db) as conn:
                previous_run = get_last_successful_run(conn, "official", verbose=args.verbose)
            if args.verbose:
                if previous_run:
                    print(
                        f"[MAIN] Previous official run: {previous_run['id']} "
                        f"({previous_run['bulletin_date']})"
                    )
                else:
                    print("[MAIN] No previous official run found — this will be the first.")
        except Exception as e:
            print(f"[MAIN] Warning: could not fetch previous run: {e}")

        # Step 3: Fetch and store the new official run
        if args.verbose:
            print("[MAIN] Starting fetch (run_type=official)...")

        success, run_id, current_data = scrape_visa_bulletin(
            output_file=args.output,
            verbose=args.verbose,
            run_type="official",
            db_path=args.db,
            use_db=True,
            do_compare=False,  # Comparison is handled here in main.py
        )

        if not success or current_data is None:
            print("[MAIN] Fetch failed. Exiting.")
            sys.exit(1)

        if args.verbose:
            print(f"[MAIN] Fetch succeeded. Run ID: {run_id}")

        # Step 4: Compare current vs previous bulletin
        comparison: Optional[Dict[str, Any]] = None
        if previous_run is not None and previous_run.get("data"):
            if args.verbose:
                print("[MAIN] Comparing against previous run...")

            comparison = compare_bulletins(current_data, previous_run["data"])

            # Always print comparison (shows "no changes" if identical)
            print(format_comparison_for_display(comparison))

            # Persist the comparison result
            if run_id is not None:
                try:
                    with get_connection(args.db) as conn:
                        insert_comparison(
                            conn,
                            run_id=run_id,
                            previous_run_id=previous_run["id"],
                            compared_at=comparison["compared_at"],
                            diff=comparison,
                            verbose=args.verbose,
                        )
                except Exception as e:
                    print(f"[MAIN] Warning: could not store comparison: {e}")
        else:
            print("[MAIN] No previous run to compare against — skipping comparison.")

        # Step 5: Send notifications (unless --no-notify)
        if args.no_notify:
            if args.verbose:
                print("[MAIN] --no-notify set, skipping notifications.")
            sys.exit(0)

        # If no comparison was made (first run), use an empty comparison so
        # subscribers still receive a bulletin announcement email.
        if comparison is None:
            comparison = _empty_comparison(current_data)

        config = _build_config_from_env()
        stats = notify_subscribers(
            comparison=comparison,
            current_bulletin=current_data,
            updated_only=args.updated_only,
            db_path=args.db,
            config=config,
            dry_run=args.print_local,
        )

        print(
            f"[MAIN] Notifications complete. "
            f"Sent: {stats['sent']}, "
            f"Skipped: {stats['skipped']}, "
            f"Failed: {stats['failed']}"
        )
        sys.exit(0 if stats["failed"] == 0 else 1)

    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"[MAIN] Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
