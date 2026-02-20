#!/usr/bin/env python3
"""
Email notification module for the Visa Bulletin tracker.

Builds HTML emails and dispatches them via AWS SES (or saves locally for preview).
SES credentials are read from environment variables; the module gracefully degrades
when they are not yet configured (use --print-local to test formatting).

Standalone usage:
    python notify.py user@email.com                   # Send test email via SES
    python notify.py user@email.com --print-local     # Save as HTML for browser preview
    python notify.py --all                            # Notify all active subscribers
    python notify.py --all --updated-only             # Only subscribers with changes
    python notify.py --all --print-local              # Preview all emails locally
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from jinja2 import Environment, FileSystemLoader

from store import (
    DEFAULT_DB_PATH,
    get_connection,
    get_last_successful_run,
    init_db,
)

_TEMPLATE_DIR = Path(__file__).parent / "static"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception    # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

DEFAULT_FROM_EMAIL: str = os.environ.get("SES_FROM_EMAIL", "")
DEFAULT_SES_REGION: str = os.environ.get("SES_REGION", "us-east-1")
APP_BASE_URL: str = os.environ.get("APP_BASE_URL", "http://localhost:5000")

# All valid subscription categories (mirrors app.py VALID_CATEGORIES)
_ALL_CATEGORIES: List[str] = sorted(
    ["EB-1", "EB-2", "EB-3", "EB-4", "EB-5", "F1", "F2A", "F2B", "F3", "F4", "DV"]
)

# Fields that identify a category row, not date values
_IDENTITY_KEYS: Set[str] = {
    "visa_category", "preference_level", "family_preference",
    "employment_preference", "category",
    # Actual parser output keys
    "family-sponsored", "employment-based", "region",
}

# Maps subscription EB codes to employment-based ordinals (for lookups)
_EB_CODE_TO_ORDINAL: Dict[str, str] = {
    "EB-1": "1st", "EB-2": "2nd", "EB-3": "3rd", "EB-4": "4th", "EB-5": "5th",
}
_EB_ORDINAL_TO_CODE: Dict[str, str] = {v: k for k, v in _EB_CODE_TO_ORDINAL.items()}

# Human-readable direction labels for email display
_DIRECTION_LABELS: Dict[str, str] = {
    "advanced": "Advanced",
    "retrogressed": "Retrogressed",
    "became_current": "Became Current",
    "lost_current": "Lost Current",
    "changed": "Changed",
    "added": "Added",
    "removed": "Removed",
}

# Colours for change directions (inline CSS for email clients)
_DIRECTION_COLOURS: Dict[str, str] = {
    "advanced": "#16a34a",      # green
    "became_current": "#16a34a",
    "retrogressed": "#dc2626",   # red
    "lost_current": "#dc2626",
    "changed": "#d97706",        # amber
    "added": "#2563eb",          # blue
    "removed": "#6b7280",        # grey
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_subscription_code(category: Dict[str, Any]) -> Optional[str]:
    """Derive the subscription category code (e.g. 'EB-2', 'F1', 'DV') for a bulletin row."""
    fs = category.get("family-sponsored")
    if fs:
        return str(fs).strip()

    eb = category.get("employment-based")
    if eb:
        eb_clean = str(eb).strip()
        code = _EB_ORDINAL_TO_CODE.get(eb_clean)
        if code:
            return code
        for ordinal, mapped_code in _EB_ORDINAL_TO_CODE.items():
            if eb_clean.lower().startswith(ordinal):
                return mapped_code
        return eb_clean

    if category.get("region"):
        return "DV"  # All DV regions map to the single "DV" subscription code

    for key in ("visa_category", "preference_level", "family_preference",
                "employment_preference", "category"):
        value = category.get(key)
        if value:
            return str(value).strip()

    return None


def _get_compare_key(category: Dict[str, Any]) -> str:
    """
    Get the comparison key for a bulletin row — mirrors compare._derive_category_key,
    but keeps the full DV-{region} key instead of collapsing to 'DV'.
    """
    fs = category.get("family-sponsored")
    if fs:
        return str(fs).strip()

    eb = category.get("employment-based")
    if eb:
        eb_clean = str(eb).strip()
        code = _EB_ORDINAL_TO_CODE.get(eb_clean)
        if code:
            return code
        for ordinal, mapped_code in _EB_ORDINAL_TO_CODE.items():
            if eb_clean.lower().startswith(ordinal):
                return mapped_code
        return eb_clean

    region = category.get("region")
    if region:
        return f"DV-{str(region).strip()}"

    for key in ("visa_category", "preference_level", "family_preference",
                "employment_preference", "category"):
        value = category.get(key)
        if value:
            return str(value).strip()

    return ""


def _find_categories_for_code(
    code: str, categories: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return all bulletin category rows that correspond to a subscription code."""
    return [c for c in categories if _extract_subscription_code(c) == code]


def _get_changed_category_keys(comparison: Dict[str, Any]) -> Set[str]:
    """Return the set of subscription codes that changed, were added, or were removed."""
    changed: Set[str] = set()
    for cat_diff in comparison.get("categories_changed", []):
        key = cat_diff["category_key"]
        # DV comparison keys are "DV-AFRICA" etc.; map to subscription code "DV"
        changed.add("DV" if key.startswith("DV-") else key)
    for cat in comparison.get("categories_added", []):
        code = _extract_subscription_code(cat)
        if code:
            changed.add(code)
    for cat in comparison.get("categories_removed", []):
        code = _extract_subscription_code(cat)
        if code:
            changed.add(code)
    return changed


def _build_config_from_env() -> Dict[str, Any]:
    """Read SES configuration from environment variables."""
    return {
        "from_email": os.environ.get("SES_FROM_EMAIL", ""),
        "region": os.environ.get("SES_REGION", "us-east-1"),
        "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
    }


def _empty_comparison(current_bulletin: Dict[str, Any]) -> Dict[str, Any]:
    """Return a synthetic empty comparison (no previous run available)."""
    return {
        "compared_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "current_run_bulletin_date": current_bulletin.get("bulletin_date"),
        "previous_run_bulletin_date": None,
        "has_changes": False,
        "summary": {
            "categories_added": 0,
            "categories_removed": 0,
            "categories_changed": 0,
            "total_field_changes": 0,
        },
        "categories_added": [],
        "categories_removed": [],
        "categories_changed": [],
        "error": None,
    }


# ---------------------------------------------------------------------------
# Email content builders
# ---------------------------------------------------------------------------

def build_email_subject(
    comparison: Dict[str, Any],
    current_bulletin: Dict[str, Any],
    has_relevant_changes: bool,
) -> str:
    """
    Build the email subject line.

    Args:
        comparison: Structured diff from compare.compare_bulletins()
        current_bulletin: Current bulletin data dict
        has_relevant_changes: True if subscriber's specific categories changed

    Returns:
        Subject string
    """
    bulletin_date = current_bulletin.get("bulletin_date", "Unknown")
    if has_relevant_changes:
        return f"Visa Bulletin Update ({bulletin_date}): Your categories changed"
    else:
        return f"Visa Bulletin Update ({bulletin_date}): No changes to your categories"


def build_email_html(
    subscription: Dict[str, Any],
    comparison: Dict[str, Any],
    current_bulletin: Dict[str, Any],
) -> str:
    """
    Build the HTML body for a subscriber's notification email.

    Args:
        subscription: DB row with keys: email, categories (list), unsubscribe_token
        comparison: Structured diff from compare.compare_bulletins()
        current_bulletin: Full parser output dict (bulletin_date, categories list)

    Returns:
        HTML string suitable for use as email body
    """
    email = subscription.get("email", "")
    subscribed_cats: List[str] = subscription.get("categories", [])
    unsubscribe_token = subscription.get("unsubscribe_token", "")
    unsubscribe_url = f"{APP_BASE_URL}/api/unsubscribe?token={unsubscribe_token}"

    bulletin_date = current_bulletin.get("bulletin_date", "Unknown")
    prev_date = comparison.get("previous_run_bulletin_date")
    has_changes = comparison.get("has_changes", False)

    # Build lookup: comparison key → field_changes list
    changed_index: Dict[str, List[Dict[str, Any]]] = {
        cd["category_key"]: cd.get("field_changes", [])
        for cd in comparison.get("categories_changed", [])
    }
    all_categories: List[Dict[str, Any]] = current_bulletin.get("categories", [])

    # Build per-category rows for subscribed categories
    category_rows_html = []
    for cat_key in subscribed_cats:
        matching_cats = _find_categories_for_code(cat_key, all_categories)

        # Determine if any matching row has changes
        has_cat_change = any(
            bool(changed_index.get(_get_compare_key(c), []))
            for c in matching_cats
        )

        row_bg = "#fef9c3" if has_cat_change else "#ffffff"  # yellow tint if changed
        row_header = (
            f'<tr style="background:{row_bg}">'
            f'<td colspan="3" style="padding:8px 12px;font-weight:bold;'
            f'border-bottom:1px solid #e5e7eb;color:#1f2937;">'
            f'{cat_key}'
        )
        if has_cat_change:
            row_header += ' <span style="color:#d97706;font-size:12px;">[UPDATED]</span>'
        row_header += "</td></tr>"
        category_rows_html.append(row_header)

        if matching_cats:
            for current_cat in matching_cats:
                compare_key = _get_compare_key(current_cat)
                field_changes = changed_index.get(compare_key, [])
                change_map: Dict[str, Dict[str, Any]] = {
                    fc["field"]: fc for fc in field_changes
                }

                # For DV with multiple region rows, show the region name as a sub-label
                if cat_key == "DV":
                    region = current_cat.get("region", "")
                    if region:
                        category_rows_html.append(
                            f'<tr style="background:{row_bg}">'
                            f'<td colspan="3" style="padding:3px 12px 2px 24px;'
                            f'color:#374151;font-size:12px;font-weight:bold;">'
                            f'{region}</td></tr>'
                        )

                # Gather date fields (exclude identity/label keys)
                date_fields = {
                    k: v for k, v in current_cat.items()
                    if k not in _IDENTITY_KEYS and v is not None
                }

                for field, current_val in sorted(date_fields.items()):
                    fc = change_map.get(field)
                    if fc:
                        direction = fc.get("direction", "changed")
                        colour = _DIRECTION_COLOURS.get(direction, "#6b7280")
                        label = _DIRECTION_LABELS.get(direction, direction.title())
                        prev_val = fc.get("previous") or "(none)"
                        change_cell = (
                            f'<span style="color:{colour};font-weight:bold;">'
                            f'{label}: {prev_val} → {current_val}'
                            f"</span>"
                        )
                    else:
                        change_cell = '<span style="color:#6b7280;">No change</span>'

                    field_label = (
                        field.replace("_", " ").replace("-", " ").title()
                    )
                    category_rows_html.append(
                        f'<tr style="background:{row_bg}">'
                        f'<td style="padding:4px 12px 4px 24px;color:#6b7280;font-size:13px;">'
                        f"{field_label}</td>"
                        f'<td style="padding:4px 12px;font-size:13px;">{current_val}</td>'
                        f'<td style="padding:4px 12px;font-size:13px;">{change_cell}</td>'
                        f"</tr>"
                    )
        else:
            category_rows_html.append(
                f'<tr style="background:{row_bg}">'
                f'<td colspan="3" style="padding:4px 12px 4px 24px;color:#9ca3af;'
                f'font-size:13px;font-style:italic;">No data available</td></tr>'
            )

    # Overall summary section
    summary = comparison.get("summary", {})
    total_changed = summary.get("categories_changed", 0)
    total_added = summary.get("categories_added", 0)
    total_removed = summary.get("categories_removed", 0)

    if has_changes:
        summary_text = (
            f"{total_changed} category(ies) changed, "
            f"{total_added} added, "
            f"{total_removed} removed"
        )
        summary_colour = "#d97706"
    else:
        summary_text = "No changes detected since the previous bulletin."
        summary_colour = "#16a34a"

    categories_table = "\n".join(category_rows_html) if category_rows_html else (
        '<tr><td colspan="4" style="padding:12px;color:#9ca3af;">No subscribed categories.</td></tr>'
    )

    template = _jinja_env.get_template("email_body.html")
    return template.render(
        bulletin_date=bulletin_date,
        prev_date=prev_date,
        summary_colour=summary_colour,
        summary_text=summary_text,
        categories_table=categories_table,
        unsubscribe_url=unsubscribe_url,
    )


# ---------------------------------------------------------------------------
# Email dispatch
# ---------------------------------------------------------------------------

def print_email_local(
    to_addr: str,
    subject: str,
    html_body: str,
    output_dir: str = tempfile.gettempdir(),
) -> Optional[str]:
    """
    Save an email as a standalone HTML file for browser preview.

    Args:
        to_addr: Recipient email address (used in filename)
        subject: Email subject (used as page title)
        html_body: HTML email body fragment
        output_dir: Directory to write the file (default: current directory)

    Returns:
        Absolute path to the saved file, or None on failure
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_email = to_addr.replace("@", "_at_").replace(".", "_")
    filename = f"email_preview_{safe_email}_{timestamp}.html"
    output_path = Path(output_dir) / filename

    template = _jinja_env.get_template("email_preview.html")
    full_html = template.render(subject=subject, to_addr=to_addr, html_body=html_body)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full_html, encoding="utf-8")
        print(f"[NOTIFY] Preview saved: {output_path.resolve()}")
        return str(output_path.resolve())
    except Exception as e:
        print(f"[NOTIFY] Failed to save preview for {to_addr}: {e}")
        return None


def send_email_ses(
    to_addr: str,
    subject: str,
    html_body: str,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send an email via AWS SES.

    NOTE: AWS SES is not yet configured. This function returns False until
    SES_FROM_EMAIL and AWS credentials are set. Use --print-local in the
    meantime to preview email formatting.

    Args:
        to_addr: Recipient email address
        subject: Email subject line
        html_body: HTML email body
        config: Optional dict with keys: from_email, region, aws_access_key_id,
                aws_secret_access_key. Falls back to environment variables.

    Returns:
        True if sent successfully, False otherwise
    """
    if not _BOTO3_AVAILABLE:
        print("[NOTIFY] boto3 is not installed. Run: pip install boto3")
        return False

    cfg = config or {}
    from_email = cfg.get("from_email") or DEFAULT_FROM_EMAIL
    region = cfg.get("region") or DEFAULT_SES_REGION
    aws_key = cfg.get("aws_access_key_id") or os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret = cfg.get("aws_secret_access_key") or os.environ.get("AWS_SECRET_ACCESS_KEY")

    if not from_email:
        print(
            "[NOTIFY] SES_FROM_EMAIL is not configured. "
            "Set it in the environment or use --print-local to preview emails."
        )
        return False

    try:
        ses_kwargs: Dict[str, Any] = {"region_name": region}
        if aws_key and aws_secret:
            ses_kwargs["aws_access_key_id"] = aws_key
            ses_kwargs["aws_secret_access_key"] = aws_secret

        client = boto3.client("ses", **ses_kwargs)
        client.send_email(
            Source=from_email,
            Destination={"ToAddresses": [to_addr]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            },
        )
        print(f"[NOTIFY] Email sent to {to_addr}")
        return True
    except (BotoCoreError, ClientError) as e:
        print(f"[NOTIFY] SES send failed for {to_addr}: {e}")
        return False
    except Exception as e:
        print(f"[NOTIFY] Unexpected error sending to {to_addr}: {e}")
        return False


# ---------------------------------------------------------------------------
# High-level notification functions
# ---------------------------------------------------------------------------

def notify_subscribers(
    comparison: Dict[str, Any],
    current_bulletin: Dict[str, Any],
    updated_only: bool = True,
    db_path: str = DEFAULT_DB_PATH,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Notify all relevant active subscribers by email.

    Args:
        comparison: Structured diff from compare.compare_bulletins()
        current_bulletin: Current bulletin data dict from parser
        updated_only: If True, only notify subscribers whose subscribed categories
                      changed. If False, notify all subscribers (noting in the email
                      whether their categories changed).
        db_path: Path to SQLite database
        config: SES config dict (from_email, region, etc.)
        dry_run: If True, save HTML locally instead of sending via SES

    Returns:
        Dict with keys: sent, skipped, failed (all int)
    """
    stats: Dict[str, int] = {"sent": 0, "skipped": 0, "failed": 0}
    changed_keys = _get_changed_category_keys(comparison)

    # Fetch all active subscriptions (one query, no per-category duplication)
    all_subscriptions: List[Dict[str, Any]] = []
    try:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE is_active = 1"
            ).fetchall()
            for row in rows:
                d = dict(row)
                d["categories"] = json.loads(d["categories"])
                all_subscriptions.append(d)
    except Exception as e:
        print(f"[NOTIFY] Failed to fetch subscriptions: {e}")
        return stats

    for subscription in all_subscriptions:
        subscriber_cats: Set[str] = set(subscription.get("categories", []))
        subscriber_changed = subscriber_cats & changed_keys
        has_relevant_changes = bool(subscriber_changed)

        if updated_only and not has_relevant_changes:
            stats["skipped"] += 1
            continue

        try:
            subject = build_email_subject(comparison, current_bulletin, has_relevant_changes)
            html_body = build_email_html(subscription, comparison, current_bulletin)

            if dry_run:
                result = print_email_local(subscription["email"], subject, html_body)
                if result:
                    stats["sent"] += 1
                else:
                    stats["failed"] += 1
            else:
                ok = send_email_ses(subscription["email"], subject, html_body, config)
                if ok:
                    stats["sent"] += 1
                else:
                    stats["failed"] += 1
        except Exception as e:
            print(f"[NOTIFY] Error processing subscriber {subscription.get('email', '?')}: {e}")
            stats["failed"] += 1

    return stats


def send_test_email(
    email: str,
    db_path: str = DEFAULT_DB_PATH,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> bool:
    """
    Send a test email to the given address using the latest bulletin data.
    Does not require a subscription — sends regardless of whether the address
    is in the database.

    Args:
        email: Recipient email address
        db_path: Path to SQLite database
        config: SES config dict
        dry_run: If True, save locally instead of sending via SES

    Returns:
        True if sent/saved successfully, False otherwise
    """
    try:
        with get_connection(db_path) as conn:
            run = get_last_successful_run(conn, "official")
    except Exception as e:
        print(f"[NOTIFY] Failed to fetch latest run: {e}")
        run = None

    if run is None:
        # Fall back to manual runs if no official run exists
        try:
            with get_connection(db_path) as conn:
                run = get_last_successful_run(conn, "manual")
        except Exception:
            pass

    if run is None:
        print("[NOTIFY] No successful runs found in DB. Cannot build test email.")
        return False

    current_bulletin = run.get("data") or {}
    synthetic_comparison = _empty_comparison(current_bulletin)

    # Use the subscriber's actual categories if they exist in the DB,
    # otherwise fall back to all categories (useful for non-subscriber previews)
    categories_for_email = list(_ALL_CATEGORIES)
    unsubscribe_token = "test-preview-no-token"
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT categories, unsubscribe_token FROM subscriptions "
                "WHERE email = ? AND is_active = 1",
                (email,),
            ).fetchone()
        if row:
            categories_for_email = json.loads(row["categories"])
            unsubscribe_token = row["unsubscribe_token"]
    except Exception:
        pass

    synthetic_subscription: Dict[str, Any] = {
        "email": email,
        "categories": categories_for_email,
        "unsubscribe_token": unsubscribe_token,
    }

    try:
        subject = f"[TEST] Visa Bulletin Preview - {current_bulletin.get('bulletin_date', 'Unknown')}"
        html_body = build_email_html(synthetic_subscription, synthetic_comparison, current_bulletin)

        if dry_run:
            result = print_email_local(email, subject, html_body)
            return result is not None
        else:
            return send_email_ses(email, subject, html_body, config)
    except Exception as e:
        print(f"[NOTIFY] Failed to build/send test email: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Visa Bulletin email notification tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python notify.py user@email.com                     Send test email via SES
  python notify.py user@email.com --print-local       Save test email as HTML
  python notify.py --all                              Notify all subscribers
  python notify.py --all --updated-only               Only notify on changes
  python notify.py --all --print-local                Save all emails locally
        """,
    )
    parser.add_argument(
        "email",
        nargs="?",
        help="Email address for test send (omit when using --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run full notification for all active subscribers",
    )
    parser.add_argument(
        "--updated-only",
        action="store_true",
        help="(with --all) Only notify subscribers whose categories changed",
    )
    parser.add_argument(
        "--print-local",
        action="store_true",
        help="Save emails as HTML files instead of sending via SES",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    return parser


def main() -> None:
    parser = _create_argument_parser()
    args = parser.parse_args()

    if not args.email and not args.all:
        parser.error("Provide an email address for test send, or use --all")

    if args.email and args.all:
        parser.error("Provide either an email address or --all, not both")

    config = _build_config_from_env()

    try:
        init_db(args.db)
    except Exception as e:
        print(f"[NOTIFY] Warning: could not initialize database: {e}")

    # --- Test email mode ---
    if args.email:
        ok = send_test_email(
            email=args.email,
            db_path=args.db,
            config=config,
            dry_run=args.print_local,
        )
        sys.exit(0 if ok else 1)

    # --- Full notification mode ---
    try:
        with get_connection(args.db) as conn:
            current_run = get_last_successful_run(conn, "official")
    except Exception as e:
        print(f"[NOTIFY] Could not fetch latest run: {e}")
        sys.exit(1)

    if current_run is None:
        print("[NOTIFY] No successful official runs found. Cannot notify.")
        sys.exit(1)

    current_bulletin = current_run.get("data") or {}

    # Get previous run for comparison
    try:
        with get_connection(args.db) as conn:
            prev_run = get_last_successful_run(
                conn, "official", exclude_run_id=current_run["id"]
            )
    except Exception:
        prev_run = None

    if prev_run is not None and prev_run.get("data"):
        from compare import compare_bulletins
        comparison = compare_bulletins(current_bulletin, prev_run["data"])
    else:
        comparison = _empty_comparison(current_bulletin)

    stats = notify_subscribers(
        comparison=comparison,
        current_bulletin=current_bulletin,
        updated_only=args.updated_only,
        db_path=args.db,
        config=config,
        dry_run=args.print_local,
    )
    print(
        f"[NOTIFY] Done. "
        f"Sent: {stats['sent']}, "
        f"Skipped: {stats['skipped']}, "
        f"Failed: {stats['failed']}"
    )
    sys.exit(0 if stats["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
