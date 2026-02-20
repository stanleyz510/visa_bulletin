"""Tests for notify.py — email building and notification dispatch."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notify as notify_module
from store import get_connection, init_db, insert_run, upsert_subscription
from notify import (
    _ALL_CATEGORIES,
    _build_config_from_env,
    _empty_comparison,
    _get_changed_category_keys,
    build_email_html,
    build_email_subject,
    notify_subscribers,
    print_email_local,
    send_email_ses,
    send_test_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> str:
    """Create a temporary SQLite DB and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    return path


def _sample_bulletin(bulletin_date: str = "February 2026") -> dict:
    return {
        "bulletin_date": bulletin_date,
        "extracted_at": "2026-02-15T10:00:00",
        "categories": [
            {
                "visa_category": "EB-1",
                "china": "Current",
                "india": "01 JAN 22",
                "mexico": "Current",
            },
            {
                "visa_category": "EB-2",
                "china": "01 OCT 21",
                "india": "01 JUL 13",
                "mexico": "01 OCT 21",
            },
            {
                "visa_category": "EB-3",
                "china": "01 JUN 18",
                "india": "01 NOV 12",
                "mexico": "01 JUN 18",
            },
        ],
        "total_categories": 3,
    }


def _sample_comparison(has_changes: bool = True) -> dict:
    """Return a comparison dict with optional EB-2 change."""
    if has_changes:
        return {
            "compared_at": "2026-02-15T10:00:00",
            "current_run_bulletin_date": "February 2026",
            "previous_run_bulletin_date": "January 2026",
            "has_changes": True,
            "summary": {
                "categories_added": 0,
                "categories_removed": 0,
                "categories_changed": 1,
                "total_field_changes": 1,
            },
            "categories_added": [],
            "categories_removed": [],
            "categories_changed": [
                {
                    "category_key": "EB-2",
                    "field_changes": [
                        {
                            "field": "china",
                            "previous": "01 SEP 21",
                            "current": "01 OCT 21",
                            "direction": "advanced",
                        }
                    ],
                }
            ],
            "error": None,
        }
    else:
        return {
            "compared_at": "2026-02-15T10:00:00",
            "current_run_bulletin_date": "February 2026",
            "previous_run_bulletin_date": "January 2026",
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


def _sample_subscription(
    email: str = "user@example.com",
    categories: list = None,
) -> dict:
    return {
        "email": email,
        "categories": categories if categories is not None else ["EB-2"],
        "unsubscribe_token": "test-token-abc",
    }


def _insert_subscription(db_path: str, email: str, categories: list) -> None:
    """Insert an active subscription directly into the DB."""
    subscribed_at = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        upsert_subscription(
            conn,
            email=email,
            categories=categories,
            subscribed_at=subscribed_at,
        )


def _insert_run(
    db_path: str, bulletin_date: str = "February 2026", run_type: str = "official"
) -> int:
    """Insert a successful run and return its run_id."""
    data = _sample_bulletin(bulletin_date)
    started_at = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        return insert_run(
            conn,
            run_type=run_type,
            started_at=started_at,
            success=True,
            bulletin_date=bulletin_date,
            data=data,
            completed_at=started_at,
        )


# ---------------------------------------------------------------------------
# Tests: _get_changed_category_keys
# ---------------------------------------------------------------------------

class TestGetChangedCategoryKeys(unittest.TestCase):

    def test_extracts_changed_category_keys(self):
        comparison = _sample_comparison(has_changes=True)
        keys = _get_changed_category_keys(comparison)
        self.assertIn("EB-2", keys)

    def test_extracts_added_category_keys(self):
        comparison = _sample_comparison(has_changes=False)
        comparison["categories_added"] = [{"visa_category": "EB-5", "china": "01 JAN 20"}]
        keys = _get_changed_category_keys(comparison)
        self.assertIn("EB-5", keys)

    def test_empty_comparison_returns_empty_set(self):
        comparison = _sample_comparison(has_changes=False)
        keys = _get_changed_category_keys(comparison)
        self.assertEqual(keys, set())


# ---------------------------------------------------------------------------
# Tests: build_email_subject
# ---------------------------------------------------------------------------

class TestBuildEmailSubject(unittest.TestCase):

    def test_subject_with_relevant_changes(self):
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()
        subject = build_email_subject(comparison, bulletin, has_relevant_changes=True)
        self.assertIn("changed", subject.lower())
        self.assertNotIn("no changes", subject.lower())

    def test_subject_without_relevant_changes(self):
        comparison = _sample_comparison(has_changes=False)
        bulletin = _sample_bulletin()
        subject = build_email_subject(comparison, bulletin, has_relevant_changes=False)
        self.assertIn("no changes", subject.lower())

    def test_subject_includes_bulletin_date(self):
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin("March 2026")
        subject = build_email_subject(comparison, bulletin, has_relevant_changes=True)
        self.assertIn("March 2026", subject)

    def test_subject_with_missing_bulletin_date(self):
        comparison = _sample_comparison(has_changes=False)
        bulletin = {}  # no bulletin_date key
        # Should not raise, falls back to "Unknown"
        subject = build_email_subject(comparison, bulletin, has_relevant_changes=False)
        self.assertIsInstance(subject, str)
        self.assertTrue(len(subject) > 0)


# ---------------------------------------------------------------------------
# Tests: build_email_html
# ---------------------------------------------------------------------------

class TestBuildEmailHtml(unittest.TestCase):

    def test_html_contains_subscriber_categories(self):
        subscription = _sample_subscription(categories=["EB-2", "EB-3"])
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()
        html = build_email_html(subscription, comparison, bulletin)
        self.assertIn("EB-2", html)
        self.assertIn("EB-3", html)

    def test_html_contains_unsubscribe_link(self):
        subscription = _sample_subscription()
        comparison = _sample_comparison(has_changes=False)
        bulletin = _sample_bulletin()
        html = build_email_html(subscription, comparison, bulletin)
        self.assertIn("unsubscribe", html.lower())
        self.assertIn("test-token-abc", html)

    def test_html_shows_change_direction(self):
        subscription = _sample_subscription(categories=["EB-2"])
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()
        html = build_email_html(subscription, comparison, bulletin)
        # "Advanced" direction should appear
        self.assertIn("Advanced", html)

    def test_html_shows_updated_tag_for_changed_category(self):
        subscription = _sample_subscription(categories=["EB-2"])
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()
        html = build_email_html(subscription, comparison, bulletin)
        self.assertIn("UPDATED", html)

    def test_html_no_updated_tag_when_no_changes(self):
        subscription = _sample_subscription(categories=["EB-1"])
        comparison = _sample_comparison(has_changes=False)
        bulletin = _sample_bulletin()
        html = build_email_html(subscription, comparison, bulletin)
        # EB-1 is not in categories_changed, should not be marked as updated
        self.assertNotIn("UPDATED", html)

    def test_html_handles_category_not_in_current_bulletin(self):
        subscription = _sample_subscription(categories=["EB-5"])  # not in bulletin
        comparison = _sample_comparison(has_changes=False)
        bulletin = _sample_bulletin()  # only has EB-1, EB-2, EB-3
        # Should not raise; renders gracefully
        html = build_email_html(subscription, comparison, bulletin)
        self.assertIn("EB-5", html)
        self.assertIsInstance(html, str)


# ---------------------------------------------------------------------------
# Tests: print_email_local
# ---------------------------------------------------------------------------

class TestPrintEmailLocal(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_saves_html_file(self):
        path = print_email_local(
            "user@test.com", "Test Subject", "<p>Hello</p>",
            output_dir=self.tmpdir,
        )
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))

    def test_filename_contains_sanitized_email(self):
        path = print_email_local(
            "user@test.com", "Test Subject", "<p>Hi</p>",
            output_dir=self.tmpdir,
        )
        filename = os.path.basename(path)
        self.assertIn("user_at_test_com", filename)

    def test_html_file_contains_subject_in_title(self):
        path = print_email_local(
            "user@test.com", "My Subject", "<p>Body</p>",
            output_dir=self.tmpdir,
        )
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("My Subject", content)

    def test_output_dir_created_if_missing(self):
        nested = os.path.join(self.tmpdir, "sub", "dir")
        path = print_email_local(
            "a@b.com", "Subj", "<p>x</p>",
            output_dir=nested,
        )
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))


# ---------------------------------------------------------------------------
# Tests: send_email_ses
# ---------------------------------------------------------------------------

class TestSendEmailSes(unittest.TestCase):

    def test_returns_false_when_boto3_unavailable(self):
        with patch("notify._BOTO3_AVAILABLE", False):
            result = send_email_ses("to@example.com", "Subject", "<p>body</p>")
        self.assertFalse(result)

    def test_returns_false_when_from_email_not_configured(self):
        with patch("notify.DEFAULT_FROM_EMAIL", ""):
            result = send_email_ses(
                "to@example.com", "Subject", "<p>body</p>",
                config={"from_email": ""},
            )
        self.assertFalse(result)

    def test_calls_ses_send_email(self):
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        config = {"from_email": "from@example.com", "region": "us-east-1"}

        with patch("notify._BOTO3_AVAILABLE", True), \
             patch.object(notify_module, "boto3", mock_boto3, create=True):
            result = send_email_ses("to@example.com", "Subject", "<p>body</p>", config)

        self.assertTrue(result)
        mock_client.send_email.assert_called_once()
        call_kwargs = mock_client.send_email.call_args[1]
        self.assertEqual(call_kwargs["Destination"]["ToAddresses"], ["to@example.com"])
        self.assertEqual(call_kwargs["Source"], "from@example.com")

    def test_returns_false_on_client_error(self):
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_client.send_email.side_effect = Exception("SES error")
        mock_boto3.client.return_value = mock_client
        config = {"from_email": "from@example.com", "region": "us-east-1"}

        with patch("notify._BOTO3_AVAILABLE", True), \
             patch.object(notify_module, "boto3", mock_boto3, create=True):
            result = send_email_ses("to@example.com", "Subject", "<p>body</p>", config)

        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Tests: notify_subscribers
# ---------------------------------------------------------------------------

class TestNotifySubscribers(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_db()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _add_subscriber(self, email: str, categories: list) -> None:
        _insert_subscription(self.db_path, email, categories)

    def test_sends_to_all_subscribers_when_not_updated_only(self):
        self._add_subscriber("a@example.com", ["EB-1"])
        self._add_subscriber("b@example.com", ["EB-3"])  # EB-3 has no changes
        comparison = _sample_comparison(has_changes=True)  # only EB-2 changed
        bulletin = _sample_bulletin()

        with patch("notify.print_email_local", return_value="/tmp/preview.html"):
            stats = notify_subscribers(
                comparison, bulletin,
                updated_only=False,
                db_path=self.db_path,
                dry_run=True,
            )

        self.assertEqual(stats["sent"], 2)
        self.assertEqual(stats["skipped"], 0)

    def test_skips_unchanged_subscribers_when_updated_only(self):
        self._add_subscriber("a@example.com", ["EB-1"])  # EB-1 not changed
        comparison = _sample_comparison(has_changes=True)  # only EB-2 changed
        bulletin = _sample_bulletin()

        stats = notify_subscribers(
            comparison, bulletin,
            updated_only=True,
            db_path=self.db_path,
            dry_run=True,
        )

        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["skipped"], 1)

    def test_sends_to_changed_subscribers_when_updated_only(self):
        self._add_subscriber("a@example.com", ["EB-2"])  # EB-2 changed
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()

        with patch("notify.print_email_local", return_value="/tmp/preview.html"):
            stats = notify_subscribers(
                comparison, bulletin,
                updated_only=True,
                db_path=self.db_path,
                dry_run=True,
            )

        self.assertEqual(stats["sent"], 1)
        self.assertEqual(stats["skipped"], 0)

    def test_no_subscribers_returns_zero_stats(self):
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()

        stats = notify_subscribers(
            comparison, bulletin,
            updated_only=False,
            db_path=self.db_path,
            dry_run=True,
        )

        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(stats["failed"], 0)

    def test_dry_run_saves_html_locally(self):
        self._add_subscriber("a@example.com", ["EB-2"])
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()
        saved_paths = []

        def capture_local(to_addr, subject, html_body, output_dir="."):
            # Redirect to tmpdir so we don't litter the workspace
            path = print_email_local(to_addr, subject, html_body, output_dir=self.tmpdir)
            if path:
                saved_paths.append(path)
            return path

        with patch("notify.print_email_local", side_effect=capture_local):
            stats = notify_subscribers(
                comparison, bulletin,
                updated_only=False,
                db_path=self.db_path,
                dry_run=True,
            )

        self.assertTrue(any(os.path.exists(p) for p in saved_paths))

    def test_ses_failure_increments_failed_count(self):
        self._add_subscriber("a@example.com", ["EB-2"])
        comparison = _sample_comparison(has_changes=True)
        bulletin = _sample_bulletin()

        with patch("notify.send_email_ses", return_value=False):
            stats = notify_subscribers(
                comparison, bulletin,
                updated_only=False,
                db_path=self.db_path,
                dry_run=False,
            )

        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["sent"], 0)

    def test_returns_correct_stats_sent_skipped_failed(self):
        self._add_subscriber("changed@example.com", ["EB-2"])  # will be sent
        self._add_subscriber("unchanged@example.com", ["EB-1"])  # will be skipped
        comparison = _sample_comparison(has_changes=True)  # only EB-2 changed
        bulletin = _sample_bulletin()

        with patch("notify.print_email_local", return_value="/tmp/preview.html"):
            stats = notify_subscribers(
                comparison, bulletin,
                updated_only=True,
                db_path=self.db_path,
                dry_run=True,
            )

        self.assertEqual(stats["sent"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["failed"], 0)


# ---------------------------------------------------------------------------
# Tests: send_test_email
# ---------------------------------------------------------------------------

class TestSendTestEmail(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_db()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_false_when_no_runs_in_db(self):
        result = send_test_email("user@example.com", db_path=self.db_path, dry_run=True)
        self.assertFalse(result)

    def test_dry_run_saves_html_file(self):
        _insert_run(self.db_path, bulletin_date="February 2026")

        def capture_local(to_addr, subject, html_body, output_dir="."):
            return print_email_local(to_addr, subject, html_body, output_dir=self.tmpdir)

        with patch("notify.print_email_local", side_effect=capture_local):
            result = send_test_email("user@example.com", db_path=self.db_path, dry_run=True)

        self.assertTrue(result)

    def test_uses_latest_run_bulletin_date(self):
        _insert_run(self.db_path, bulletin_date="March 2026")
        html_bodies = []

        def capture_local(to_addr, subject, html_body, output_dir="."):
            html_bodies.append(html_body)
            return "/tmp/fake.html"

        with patch("notify.print_email_local", side_effect=capture_local):
            send_test_email("user@example.com", db_path=self.db_path, dry_run=True)

        # The bulletin date should appear in the email content
        self.assertTrue(any("March 2026" in h for h in html_bodies))

    def test_sends_via_ses_when_not_dry_run(self):
        _insert_run(self.db_path, bulletin_date="February 2026")
        config = {"from_email": "from@example.com", "region": "us-east-1"}
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch("notify._BOTO3_AVAILABLE", True), \
             patch.object(notify_module, "boto3", mock_boto3, create=True):
            result = send_test_email(
                "user@example.com",
                db_path=self.db_path,
                config=config,
                dry_run=False,
            )

        self.assertTrue(result)
        mock_client.send_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
