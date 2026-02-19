#!/usr/bin/env python3
"""
Flask web application for the Visa Bulletin subscription service.

Routes:
    GET  /                      Subscription page
    POST /api/subscribe         Subscribe or update subscription
    GET  /api/unsubscribe       Unsubscribe via token

Usage:
    python app.py               # Start on 0.0.0.0:5000
    python app.py --port 8080   # Custom port
    python app.py --db /path/to/visa_bulletin.db
"""

import argparse
import re
import sys
from datetime import datetime, timezone

try:
    from flask import Flask, jsonify, render_template, request
except ImportError:
    print("[ERROR] Flask is required. Install it with:")
    print("  pip install flask")
    sys.exit(1)

from store import (
    DEFAULT_DB_PATH,
    deactivate_subscription,
    get_connection,
    init_db,
    upsert_subscription,
)

app = Flask(__name__)

# Set at startup by main()
_DB_PATH = DEFAULT_DB_PATH

# Canonical set of subscribable visa categories
VALID_CATEGORIES = {
    "EB-1", "EB-2", "EB-3", "EB-4", "EB-5",
    "F1", "F2A", "F2B", "F3", "F4",
    "DV",
}

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def _client_ip() -> str | None:
    """Return best-effort client IP, honouring X-Forwarded-For for reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    """
    Request body (JSON):
        {"email": "user@example.com", "categories": ["EB-2", "F2A"]}

    Successful responses:
        {"status": "created",      "email": "...", "categories": [...]}
        {"status": "updated",      "email": "...", "categories": [...], "previous_categories": [...]}
        {"status": "resubscribed", "email": "...", "categories": [...], "previous_categories": [...]}

    Error responses (HTTP 400 / 500):
        {"status": "error", "message": "..."}
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"status": "error", "message": "Request body must be JSON."}), 400

    # Validate email
    email = (body.get("email") or "").strip().lower()
    if not email:
        return jsonify({"status": "error", "message": "Email is required."}), 400
    if not _validate_email(email):
        return jsonify({"status": "error", "message": "Invalid email address."}), 400

    # Validate categories
    raw_cats = body.get("categories")
    if not isinstance(raw_cats, list) or len(raw_cats) == 0:
        return jsonify({"status": "error", "message": "Select at least one visa category."}), 400
    invalid = [c for c in raw_cats if c not in VALID_CATEGORIES]
    if invalid:
        return jsonify({
            "status": "error",
            "message": f"Unknown category/categories: {', '.join(sorted(invalid))}",
        }), 400
    # Deduplicate and sort for stable storage
    categories = sorted(set(raw_cats))

    try:
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(_DB_PATH) as conn:
            result = upsert_subscription(
                conn,
                email=email,
                categories=categories,
                subscribed_at=now,
                ip_address=_client_ip(),
                user_agent=request.headers.get("User-Agent"),
            )
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database error: {e}"}), 500

    # Don't expose unsubscribe_token to the browser
    response = {
        "status": result["status"],
        "email": result["email"],
        "categories": result["categories"],
    }
    if result["previous_categories"] is not None:
        response["previous_categories"] = result["previous_categories"]

    return jsonify(response), 200


@app.route("/api/unsubscribe")
def unsubscribe():
    """
    GET /api/unsubscribe?token=<uuid>

    On success: renders unsubscribe.html with the subscriber's email.
    On failure: returns JSON error (400).
    """
    token = (request.args.get("token") or "").strip()
    if not token:
        return jsonify({"status": "error", "message": "Missing unsubscribe token."}), 400

    try:
        with get_connection(_DB_PATH) as conn:
            subscription = deactivate_subscription(conn, token)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database error: {e}"}), 500

    if subscription is None:
        return jsonify({
            "status": "error",
            "message": "Invalid or already-used unsubscribe link.",
        }), 400

    return render_template("unsubscribe.html", email=subscription["email"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args():
    parser = argparse.ArgumentParser(description="Visa Bulletin subscription web server")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH,
                        help=f"SQLite database path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    return parser.parse_args()


def main():
    global _DB_PATH
    args = _parse_args()
    _DB_PATH = args.db
    init_db(_DB_PATH)
    print(f"[APP] Starting on http://{args.host}:{args.port}")
    print(f"[APP] Database: {_DB_PATH}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
