#!/usr/bin/env python3
"""
US Visa Bulletin Web Scraper
Fetches the US Visa Bulletin webpage, parses it, extracts visa category data,
and saves the results to JSON format.

Usage:
    python fetch.py                                    # Use default settings
    python fetch.py -o output.json                    # Specify output file
    python fetch.py -v                                # Enable verbose mode
    python fetch.py -t                                # Save with timestamp
    python fetch.py --display                         # Display results after saving
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] Required packages not found. Please install them:")
    print("  pip install requests beautifulsoup4")
    sys.exit(1)

from parser import parse_bulletin_html
from persist import save_to_json, save_with_timestamp, load_from_json, format_data_for_display
from store import DEFAULT_DB_PATH, init_db, get_connection, insert_run, get_last_successful_run, insert_comparison, get_runs
from compare import compare_bulletins, format_comparison_for_display


# Constants
VISA_BULLETIN_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
DEFAULT_OUTPUT_FILE = "visa_bulletin_data.json"
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)
BASE_DOMAIN = "https://travel.state.gov"


def fetch_bulletin_page(url: str, verbose: bool = False) -> Optional[str]:
    """
    Fetch the visa bulletin webpage.
    
    Args:
        url: URL to fetch
        verbose: Enable verbose logging
        
    Returns:
        HTML content as string, or None if failed
    """
    try:
        if verbose:
            print(f"[FETCH] Fetching URL: {url}")
        
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        if verbose:
            print(f"[FETCH] Successfully fetched page ({len(response.text)} bytes)")
            print(f"[FETCH] Status code: {response.status_code}")
        
        return response.text
    
    except requests.exceptions.Timeout:
        print(f"[ERROR] Request timeout after {REQUEST_TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Failed to connect to {url}: {str(e)}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP error: {str(e)}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error while fetching: {str(e)}")
        return None


def construct_bulletin_url(year: int, month: str) -> str:
    """
    Construct a visa bulletin URL based on year and month.

    Args:
        year: Year (e.g., 2026)
        month: Month name in lowercase (e.g., 'january')

    Returns:
        Absolute URL to the bulletin page
    """
    path = f"/content/travel/en/legal/visa-law0/visa-bulletin/{year}/visa-bulletin-for-{month.lower()}-{year}.html"
    return BASE_DOMAIN + path


def extract_bulletin_url_from_landing_page(html_content: str, verbose: bool = False) -> Optional[str]:
    """
    Extract the current bulletin URL from the landing page.

    Tries multiple strategies:
    1. Look for <a> tag with class 'btn btn-lg btn-success' in 'Current Visa Bulletin' section
    2. Look for first link in recent_bulletins list
    3. Construct URL based on current month/year

    Args:
        html_content: HTML content of the landing page
        verbose: Enable verbose logging

    Returns:
        Absolute URL to current bulletin, or None if extraction failed
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        if verbose:
            print("[EXTRACT] Attempting to extract current bulletin URL from landing page...")

        # Strategy 1: Look for "Current Visa Bulletin" section
        # Find all list items that might contain the current bulletin
        list_items = soup.find_all('li')
        for li in list_items:
            h2 = li.find('h2')
            if h2 and 'current' in h2.get_text().lower() and 'bulletin' in h2.get_text().lower():
                # Found the "Current Visa Bulletin" section
                link = li.find('a', class_='btn')
                if link and link.get('href'):
                    href = link['href']
                    # Convert relative URL to absolute if needed
                    if href.startswith('/'):
                        href = BASE_DOMAIN + href
                    if verbose:
                        print(f"[EXTRACT] Found current bulletin URL (Strategy 1): {href}")
                    return href

        # Strategy 2: Look for recent_bulletins list and take the first link
        recent_bulletins = soup.find('ul', id='recent_bulletins')
        if recent_bulletins:
            links = recent_bulletins.find_all('a')
            if links:
                href = links[0].get('href')
                if href:
                    if href.startswith('/'):
                        href = BASE_DOMAIN + href
                    if verbose:
                        print(f"[EXTRACT] Found bulletin URL (Strategy 2): {href}")
                    return href

        # Strategy 3: Construct URL based on current date
        current_date = datetime.now()
        month_name = current_date.strftime('%B').lower()  # e.g., 'february'
        year = current_date.year

        constructed_url = construct_bulletin_url(year, month_name)
        if verbose:
            print(f"[EXTRACT] Using constructed URL (Strategy 3): {constructed_url}")

        return constructed_url

    except Exception as e:
        print(f"[ERROR] Failed to extract bulletin URL: {str(e)}")
        if verbose:
            import traceback
            traceback.print_exc()
        return None


def scrape_visa_bulletin(
    output_file: Optional[str] = None,
    use_timestamp: bool = False,
    verbose: bool = False,
    display: bool = False,
    debug: bool = False,
    run_type: str = "official",
    db_path: str = DEFAULT_DB_PATH,
    use_db: bool = True,
    do_compare: bool = False,
) -> tuple:
    """
    Main scraping orchestration function.
    Fetches, parses, and saves visa bulletin data.

    Args:
        output_file: Path to output JSON file
        use_timestamp: Add timestamp to filename
        verbose: Enable verbose logging
        display: Display results after saving
        debug: Enable debug mode (saves HTML for inspection)
        run_type: Tag this run ('official', 'test', 'benchmark', 'manual')
        db_path: Path to the SQLite database file
        use_db: If False, skip all database operations (JSON-only mode)
        do_compare: Compare this run against the previous run of the same type

    Returns:
        Tuple of (success: bool, run_id: Optional[int], data: Optional[dict])
    """
    started_at = datetime.now(timezone.utc).isoformat()

    def _record_failure(error_message: str) -> None:
        """Record a failed run in the DB if use_db is enabled."""
        if not use_db:
            return
        try:
            completed_at = datetime.now(timezone.utc).isoformat()
            with get_connection(db_path) as conn:
                insert_run(
                    conn,
                    run_type=run_type,
                    started_at=started_at,
                    success=False,
                    error_message=error_message,
                    completed_at=completed_at,
                    verbose=verbose,
                )
        except Exception as e:
            print(f"[STORE] Warning: could not record failed run: {e}")

    if use_db:
        try:
            init_db(db_path, verbose=verbose)
        except Exception as e:
            print(f"[STORE] Warning: could not initialize database: {e}")

    if verbose:
        print("[MAIN] Starting visa bulletin scraper...")
        print(f"[MAIN] Target URL: {VISA_BULLETIN_URL}")

    # Step 1: Fetch the landing page
    html_content = fetch_bulletin_page(VISA_BULLETIN_URL, verbose)
    if not html_content:
        print("[ERROR] Failed to fetch landing page. Exiting.")
        _record_failure("Failed to fetch landing page")
        return False, None, None

    # Step 1.5: Extract bulletin URL from landing page
    if verbose:
        print("[MAIN] Extracting bulletin URL from landing page...")

    bulletin_url = extract_bulletin_url_from_landing_page(html_content, verbose)
    if not bulletin_url:
        print("[ERROR] Failed to extract bulletin URL from landing page.")
        print("[HELP] The landing page structure may have changed.")
        if debug:
            print("[DEBUG] Landing page HTML saved for inspection.")
        _record_failure("Failed to extract bulletin URL from landing page")
        return False, None, None

    if verbose:
        print(f"[MAIN] Found bulletin URL: {bulletin_url}")

    # Step 2: Fetch the actual bulletin page
    if verbose:
        print("[MAIN] Fetching actual bulletin page...")

    html_content = fetch_bulletin_page(bulletin_url, verbose)
    if not html_content:
        print("[ERROR] Failed to fetch bulletin page. Exiting.")
        _record_failure(f"Failed to fetch bulletin page: {bulletin_url}")
        return False, None, None

    # Step 3: Parse the bulletin HTML
    if verbose:
        print("[MAIN] Parsing bulletin HTML content...")

    data = parse_bulletin_html(html_content, verbose, debug)
    if not data:
        print("[ERROR] Failed to parse HTML content. Exiting.")
        _record_failure("Failed to parse bulletin HTML")
        return False, None, None

    # Step 4: Save to JSON
    if verbose:
        print("[MAIN] Saving extracted data...")

    if use_timestamp:
        saved_path = save_with_timestamp(data, verbose=verbose)
        if not saved_path:
            print("[ERROR] Failed to save data. Exiting.")
            _record_failure("Failed to save timestamped JSON file")
            return False, None, None
    else:
        output_path = output_file or DEFAULT_OUTPUT_FILE
        if not save_to_json(data, output_path, verbose):
            print("[ERROR] Failed to save data. Exiting.")
            _record_failure(f"Failed to save JSON to {output_path}")
            return False, None, None
        saved_path = output_path

    if verbose:
        print(f"[MAIN] Data successfully saved to: {saved_path}")

    # Step 5: Display results if requested
    if display:
        print("\n" + "=" * 60)
        print("EXTRACTED DATA SUMMARY")
        print("=" * 60)
        loaded_data = load_from_json(saved_path, verbose=False)
        if loaded_data:
            print(format_data_for_display(loaded_data))
        print("=" * 60 + "\n")

    # Step 6: Record run in DB and optionally compare with previous run
    run_id: Optional[int] = None
    if use_db:
        try:
            completed_at = datetime.now(timezone.utc).isoformat()
            with get_connection(db_path) as conn:
                run_id = insert_run(
                    conn,
                    run_type=run_type,
                    started_at=started_at,
                    success=True,
                    bulletin_date=data.get("bulletin_date"),
                    source_url=bulletin_url,
                    data=data,
                    completed_at=completed_at,
                    verbose=verbose,
                )
                if do_compare:
                    prev = get_last_successful_run(
                        conn, run_type, exclude_run_id=run_id, verbose=verbose
                    )
                    if prev is not None:
                        diff = compare_bulletins(data, prev["data"])
                        insert_comparison(
                            conn,
                            run_id=run_id,
                            previous_run_id=prev["id"],
                            compared_at=diff["compared_at"],
                            diff=diff,
                            verbose=verbose,
                        )
                        print(format_comparison_for_display(diff))
                    else:
                        print("[STORE] No previous run found for comparison.")
        except Exception as e:
            print(f"[STORE] Warning: could not record run in database: {e}")

    return True, run_id, data


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and return command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Fetch and parse US Visa Bulletin data from the State Department website",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetch.py                                   # Default behavior
  python fetch.py -o bulletin.json                 # Custom output file
  python fetch.py -v                               # Verbose output
  python fetch.py -t                               # Save with timestamp
  python fetch.py -v -t --display                  # Verbose + timestamp + display results
        """
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f'Output JSON file path (default: {DEFAULT_OUTPUT_FILE})'
    )
    
    parser.add_argument(
        '-t', '--timestamp',
        action='store_true',
        help='Add timestamp to output filename (overrides -o option for filename)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--display',
        action='store_true',
        help='Display extracted data summary after saving'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode (saves HTML for inspection if parsing fails)'
    )

    parser.add_argument(
        '--run-type',
        type=str,
        default='manual',
        choices=['official', 'test', 'benchmark', 'manual'],
        help='Tag this run with a type for historical tracking (default: official)'
    )

    parser.add_argument(
        '--db',
        type=str,
        default=DEFAULT_DB_PATH,
        help=f'Path to the SQLite database file (default: {DEFAULT_DB_PATH})'
    )

    parser.add_argument(
        '--no-db',
        action='store_true',
        help='Skip database storage and operate in JSON-only mode'
    )

    parser.add_argument(
        '--compare',
        action='store_true',
        help='Compare this run against the previous run of the same type and print diff'
    )

    parser.add_argument(
        '--history',
        action='store_true',
        help='Print the last 10 runs from the database and exit'
    )

    return parser


def main():
    """Main entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()

    try:
        if args.history:
            init_db(args.db, verbose=args.verbose)
            with get_connection(args.db) as conn:
                runs = get_runs(conn, limit=10, verbose=args.verbose)
            if not runs:
                print("No runs recorded yet.")
            else:
                print(f"{'ID':<20}  {'TYPE':<10}  {'SUCCESS':<8}  {'BULLETIN':<20}  STARTED")
                print("-" * 80)
                for r in runs:
                    success_str = "yes" if r["success"] else "no"
                    bulletin = r["bulletin_date"] or "(none)"
                    print(
                        f"{r['id']:<20}  {r['run_type']:<10}  {success_str:<8}  "
                        f"{bulletin:<20}  {r['started_at']}"
                    )
            sys.exit(0)

        success, _run_id, _data = scrape_visa_bulletin(
            output_file=args.output if not args.timestamp else None,
            use_timestamp=args.timestamp,
            verbose=args.verbose,
            display=args.display,
            debug=args.debug,
            run_type=args.run_type,
            db_path=args.db,
            use_db=not args.no_db,
            do_compare=args.compare,
        )

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n[INFO] Scraper interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
