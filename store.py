"""
SQLite storage module for visa bulletin run history.

Persists run results by run type, enabling historical comparison and future
subscription/notification features.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = "visa_bulletin.db"

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY,
    run_type         TEXT    NOT NULL DEFAULT 'official',
    started_at       TEXT    NOT NULL,
    completed_at     TEXT,
    success          INTEGER NOT NULL DEFAULT 0,
    bulletin_date    TEXT,
    source_url       TEXT,
    data_json        TEXT,
    error_message    TEXT,
    categories_count INTEGER,
    CONSTRAINT chk_run_type CHECK (run_type IN ('official','test','benchmark','manual'))
);

CREATE TABLE IF NOT EXISTS comparisons (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    previous_run_id INTEGER NOT NULL REFERENCES runs(id),
    compared_at     TEXT    NOT NULL,
    has_changes     INTEGER NOT NULL DEFAULT 0,
    diff_json       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_type_success_started
    ON runs (run_type, success, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_comparisons_run_id ON comparisons (run_id);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                INTEGER PRIMARY KEY,
    email             TEXT    NOT NULL UNIQUE,
    categories        TEXT    NOT NULL,
    subscribed_at     TEXT    NOT NULL,
    updated_at        TEXT,
    ip_address        TEXT,
    user_agent        TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1,
    unsubscribe_token TEXT    NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_active
    ON subscriptions (is_active);

CREATE INDEX IF NOT EXISTS idx_subscriptions_token
    ON subscriptions (unsubscribe_token);
"""


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Open a WAL-mode SQLite connection with foreign keys enabled.
    Rows are accessible as dicts via sqlite3.Row factory.
    Use as a context manager to manage connection lifetime.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH, verbose: bool = False) -> None:
    """
    Create tables and indexes if they do not exist. Safe to call on every startup (idempotent).

    Args:
        db_path: Path to the SQLite database file
        verbose: Enable verbose logging
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.commit()
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()
        if verbose:
            print(f"[STORE] Database initialized: {db_path}")
    except Exception as e:
        print(f"[ERROR] Failed to initialize database: {str(e)}")
        raise


def generate_run_id(conn: sqlite3.Connection, table: str = "runs") -> int:
    """
    Generate a time-based integer ID of the form YYYYMMDDHHmmSS + 3-digit sequence.

    For example: 20260218201515001 (first in that second), 20260218201515002 (second), etc.
    Queries the given table for existing IDs within the same second to determine the next
    sequence number, safely handling multiple runs within a single second.

    Args:
        conn: Active SQLite connection
        table: Table name to check for existing IDs ('runs', 'comparisons', or 'subscriptions')

    Returns:
        A unique 17-digit integer ID
    """
    prefix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    low = int(prefix + "000")
    high = int(prefix + "999")
    row = conn.execute(
        f"SELECT MAX(id) FROM {table} WHERE id >= ? AND id <= ?",  # noqa: S608
        (low, high),
    ).fetchone()
    max_id = row[0]
    if max_id is None:
        return int(prefix + "001")
    seq = (max_id % 1000) + 1
    if seq > 999:
        raise RuntimeError(
            f"More than 999 {table} IDs generated in the same second; try again in a moment."
        )
    return int(prefix + f"{seq:03d}")


def insert_run(
    conn: sqlite3.Connection,
    run_type: str,
    started_at: str,
    success: bool,
    bulletin_date: Optional[str] = None,
    source_url: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    completed_at: Optional[str] = None,
    verbose: bool = False,
) -> int:
    """
    Insert a new row into the runs table.

    Args:
        conn: Active SQLite connection
        run_type: One of 'official', 'test', 'benchmark', 'manual'
        started_at: ISO-8601 UTC timestamp when the run started
        success: True if the run completed successfully
        bulletin_date: e.g. "January 2026"; None on failure
        source_url: URL of the fetched bulletin page
        data: Full parser output dict; serialised to compact JSON. None on failure.
        error_message: Error description; None on success.
        completed_at: ISO-8601 UTC timestamp when the run ended
        verbose: Enable verbose logging

    Returns:
        The new run's integer ID
    """
    try:
        run_id = generate_run_id(conn, "runs")
        data_json = (
            json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if data is not None
            else None
        )
        categories_count = len(data.get("categories", [])) if data else None
        conn.execute(
            """
            INSERT INTO runs
                (id, run_type, started_at, completed_at, success,
                 bulletin_date, source_url, data_json, error_message, categories_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_type,
                started_at,
                completed_at,
                int(success),
                bulletin_date,
                source_url,
                data_json,
                error_message,
                categories_count,
            ),
        )
        conn.commit()
        if verbose:
            status = "success" if success else "failure"
            print(f"[STORE] Recorded run {run_id} (type={run_type}, status={status})")
        return run_id
    except sqlite3.IntegrityError as e:
        print(f"[ERROR] Failed to insert run (constraint violation): {str(e)}")
        raise
    except Exception as e:
        print(f"[ERROR] Failed to insert run: {str(e)}")
        raise


def get_last_successful_run(
    conn: sqlite3.Connection,
    run_type: str,
    exclude_run_id: Optional[int] = None,
    verbose: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Return the most recent successful run of the given type as a dict.
    data_json is deserialised into a 'data' key. Returns None if no match.

    Args:
        conn: Active SQLite connection
        run_type: Filter by run type ('official', 'test', 'benchmark', 'manual')
        exclude_run_id: Skip this run ID (use to exclude the current run)
        verbose: Enable verbose logging
    """
    try:
        if exclude_run_id is not None:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE run_type = ? AND success = 1 AND id != ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (run_type, exclude_run_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE run_type = ? AND success = 1
                ORDER BY started_at DESC LIMIT 1
                """,
                (run_type,),
            ).fetchone()
        if row is None:
            if verbose:
                print(f"[STORE] No previous successful '{run_type}' run found.")
            return None
        result = dict(row)
        result["data"] = json.loads(result["data_json"]) if result["data_json"] else None
        if verbose:
            print(
                f"[STORE] Found previous run {result['id']} "
                f"(bulletin: {result['bulletin_date']})"
            )
        return result
    except Exception as e:
        print(f"[ERROR] Failed to query last successful run: {str(e)}")
        return None


def get_run_by_id(
    run_id: int,
    db_path: str = DEFAULT_DB_PATH,
    verbose: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Return a single run row by ID, with data_json deserialised into 'data'.
    Returns None if no run with that ID exists.

    Args:
        run_id: The integer run ID to look up
        db_path: Path to the SQLite database file
        verbose: Enable verbose logging
    """
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            if verbose:
                print(f"[STORE] No run found with id={run_id}")
            return None
        result = dict(row)
        result["data"] = json.loads(result["data_json"]) if result["data_json"] else None
        if verbose:
            print(f"[STORE] Found run {run_id} (bulletin: {result['bulletin_date']})")
        return result
    except Exception as e:
        print(f"[ERROR] Failed to query run by id: {str(e)}")
        return None


def insert_comparison(
    conn: sqlite3.Connection,
    run_id: int,
    previous_run_id: int,
    compared_at: str,
    diff: Dict[str, Any],
    verbose: bool = False,
) -> int:
    """
    Insert a comparison result between two runs.

    Args:
        conn: Active SQLite connection
        run_id: ID of the current (newer) run
        previous_run_id: ID of the reference (older) run
        compared_at: ISO-8601 UTC timestamp of the comparison
        diff: Structured diff dict from compare.compare_bulletins()
        verbose: Enable verbose logging

    Returns:
        The new comparison's integer ID
    """
    try:
        cmp_id = generate_run_id(conn, "comparisons")
        has_changes = int(diff.get("has_changes", False))
        diff_json = json.dumps(diff, ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            """
            INSERT INTO comparisons
                (id, run_id, previous_run_id, compared_at, has_changes, diff_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cmp_id, run_id, previous_run_id, compared_at, has_changes, diff_json),
        )
        conn.commit()
        if verbose:
            print(
                f"[STORE] Recorded comparison {cmp_id} "
                f"(run {run_id} vs {previous_run_id}, has_changes={bool(has_changes)})"
            )
        return cmp_id
    except Exception as e:
        print(f"[ERROR] Failed to insert comparison: {str(e)}")
        raise


def get_runs(
    conn: sqlite3.Connection,
    run_type: Optional[str] = None,
    limit: int = 20,
    success_only: bool = False,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """
    List runs in reverse chronological order. data_json is NOT deserialised (keep it cheap).

    Args:
        conn: Active SQLite connection
        run_type: Filter by type; None returns all types
        limit: Maximum number of rows to return
        success_only: If True, only return successful runs
        verbose: Enable verbose logging

    Returns:
        List of dicts matching the runs table columns (without data_json)
    """
    try:
        conditions = []
        params: list = []
        if run_type is not None:
            conditions.append("run_type = ?")
            params.append(run_type)
        if success_only:
            conditions.append("success = 1")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT id, run_type, started_at, completed_at, success, "  # noqa: S608
            f"bulletin_date, source_url, error_message, categories_count "
            f"FROM runs {where} ORDER BY started_at DESC LIMIT ?",
            params,
        ).fetchall()
        result = [dict(r) for r in rows]
        if verbose:
            print(f"[STORE] Retrieved {len(result)} run(s)")
        return result
    except Exception as e:
        print(f"[ERROR] Failed to retrieve runs: {str(e)}")
        return []


# ---------------------------------------------------------------------------
# Subscription functions
# ---------------------------------------------------------------------------


def upsert_subscription(
    conn: sqlite3.Connection,
    email: str,
    categories: List[str],
    subscribed_at: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Insert a new subscription or update an existing one for the same email.

    Returns a dict with keys:
      - id: subscription integer ID
      - status: 'created' | 'updated' | 'resubscribed'
      - email: the email address
      - categories: current list of subscribed categories
      - previous_categories: old list before update (None if status == 'created')
      - unsubscribe_token: UUID4 string for the one-click unsubscribe link

    Args:
        conn: Active SQLite connection
        email: Subscriber email address
        categories: List of visa category keys, e.g. ['EB-2', 'F2A']
        subscribed_at: ISO-8601 UTC timestamp of this request
        ip_address: Client IP address (may be None)
        user_agent: Browser User-Agent string (may be None)
    """
    categories_json = json.dumps(categories, ensure_ascii=False, separators=(",", ":"))

    existing = get_subscription_by_email(conn, email)

    if existing is None:
        sub_id = generate_run_id(conn, "subscriptions")
        token = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO subscriptions
                (id, email, categories, subscribed_at, ip_address, user_agent,
                 is_active, unsubscribe_token)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (sub_id, email, categories_json, subscribed_at, ip_address, user_agent, token),
        )
        conn.commit()
        return {
            "id": sub_id,
            "status": "created",
            "email": email,
            "categories": categories,
            "previous_categories": None,
            "unsubscribe_token": token,
        }
    else:
        was_active = existing["is_active"] == 1
        previous_categories = existing["categories"]
        conn.execute(
            """
            UPDATE subscriptions
               SET categories = ?, updated_at = ?, ip_address = ?,
                   user_agent = ?, is_active = 1
             WHERE email = ?
            """,
            (categories_json, subscribed_at, ip_address, user_agent, email),
        )
        conn.commit()
        status = "updated" if was_active else "resubscribed"
        return {
            "id": existing["id"],
            "status": status,
            "email": email,
            "categories": categories,
            "previous_categories": previous_categories,
            "unsubscribe_token": existing["unsubscribe_token"],
        }


def get_subscription_by_email(
    conn: sqlite3.Connection,
    email: str,
) -> Optional[Dict[str, Any]]:
    """
    Return the subscription row for the given email (regardless of is_active),
    or None if no row exists.

    The 'categories' key is returned as a Python list (deserialized from JSON).
    """
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE email = ?", (email,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["categories"] = json.loads(result["categories"])
    return result


def get_active_subscriptions_for_category(
    conn: sqlite3.Connection,
    category_key: str,
) -> List[Dict[str, Any]]:
    """
    Return all active subscriptions that include the given category key.

    Uses SQLite's json_each() to query the categories JSON array efficiently.
    The 'categories' key in each returned dict is a Python list.

    Args:
        conn: Active SQLite connection
        category_key: A visa category key, e.g. 'EB-2' or 'F2A'
    """
    rows = conn.execute(
        """
        SELECT s.*
          FROM subscriptions s, json_each(s.categories) cat
         WHERE cat.value = ? AND s.is_active = 1
        """,
        (category_key,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["categories"] = json.loads(d["categories"])
        result.append(d)
    return result


def deactivate_subscription(
    conn: sqlite3.Connection,
    unsubscribe_token: str,
) -> Optional[Dict[str, Any]]:
    """
    Mark a subscription as inactive (is_active = 0) using the unsubscribe token.

    Returns the subscription dict (with 'categories' as a list) if found and
    deactivated, or None if no active subscription matches the token.
    """
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE unsubscribe_token = ? AND is_active = 1",
        (unsubscribe_token,),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE subscriptions SET is_active = 0 WHERE unsubscribe_token = ?",
        (unsubscribe_token,),
    )
    conn.commit()
    result = dict(row)
    result["categories"] = json.loads(result["categories"])
    return result
