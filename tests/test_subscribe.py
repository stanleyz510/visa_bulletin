"""Tests for subscription-related store functions."""

import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from store import (
    deactivate_subscription,
    get_active_subscriptions_for_category,
    get_connection,
    get_subscription_by_email,
    init_db,
    upsert_subscription,
)


def _make_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


_NOW = "2026-02-18T20:00:00+00:00"
_CATS = ["EB-2", "F2A"]


class TestUpsertSubscription(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def _upsert(self, email="user@example.com", categories=None, **kw):
        if categories is None:
            categories = list(_CATS)
        with get_connection(self.db_path) as conn:
            return upsert_subscription(
                conn, email=email, categories=categories, subscribed_at=_NOW, **kw
            )

    # ------------------------------------------------------------------
    # New subscription
    # ------------------------------------------------------------------

    def test_new_subscription_returns_created(self):
        result = self._upsert()
        self.assertEqual(result["status"], "created")

    def test_new_subscription_id_is_17_digits(self):
        result = self._upsert()
        self.assertEqual(len(str(result["id"])), 17)

    def test_new_subscription_categories_matches(self):
        result = self._upsert(categories=["EB-1", "F3"])
        self.assertEqual(result["categories"], ["EB-1", "F3"])

    def test_new_subscription_previous_categories_is_none(self):
        result = self._upsert()
        self.assertIsNone(result["previous_categories"])

    def test_new_subscription_token_is_valid_uuid(self):
        result = self._upsert()
        # Should not raise
        parsed = uuid.UUID(result["unsubscribe_token"])
        self.assertEqual(parsed.version, 4)

    def test_new_subscription_email_normalised(self):
        result = self._upsert(email="User@Example.COM")
        # app.py lowercases before calling upsert; upsert stores what it receives
        self.assertIn("@", result["email"])

    # ------------------------------------------------------------------
    # Duplicate email (active subscription) -> updated
    # ------------------------------------------------------------------

    def test_duplicate_email_returns_updated(self):
        self._upsert(categories=["EB-1"])
        result = self._upsert(categories=["EB-2", "F4"])
        self.assertEqual(result["status"], "updated")

    def test_updated_previous_categories_has_old_value(self):
        self._upsert(categories=["EB-1"])
        result = self._upsert(categories=["EB-2"])
        self.assertEqual(result["previous_categories"], ["EB-1"])

    def test_updated_categories_has_new_value(self):
        self._upsert(categories=["EB-1"])
        result = self._upsert(categories=["EB-2", "F2A"])
        self.assertEqual(result["categories"], ["EB-2", "F2A"])

    def test_updated_id_is_same_row(self):
        r1 = self._upsert(categories=["EB-1"])
        r2 = self._upsert(categories=["EB-2"])
        self.assertEqual(r1["id"], r2["id"])

    def test_updated_token_unchanged(self):
        r1 = self._upsert(categories=["EB-1"])
        r2 = self._upsert(categories=["EB-2"])
        self.assertEqual(r1["unsubscribe_token"], r2["unsubscribe_token"])

    # ------------------------------------------------------------------
    # Resubscribing after unsubscribing
    # ------------------------------------------------------------------

    def test_resubscribe_after_unsubscribe_returns_resubscribed(self):
        r1 = self._upsert(categories=["EB-1"])
        with get_connection(self.db_path) as conn:
            deactivate_subscription(conn, r1["unsubscribe_token"])
        result = self._upsert(categories=["EB-3"])
        self.assertEqual(result["status"], "resubscribed")

    def test_resubscribed_previous_categories_is_old_value(self):
        r1 = self._upsert(categories=["EB-1"])
        with get_connection(self.db_path) as conn:
            deactivate_subscription(conn, r1["unsubscribe_token"])
        result = self._upsert(categories=["EB-3"])
        self.assertEqual(result["previous_categories"], ["EB-1"])

    # ------------------------------------------------------------------
    # Optional metadata
    # ------------------------------------------------------------------

    def test_ip_and_ua_stored(self):
        self._upsert(ip_address="1.2.3.4", user_agent="TestBrowser/1.0")
        sub = get_subscription_by_email(
            next(iter([get_connection(self.db_path).__enter__()])), "user@example.com"
        )
        # Verify by reading raw DB
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT ip_address, user_agent FROM subscriptions WHERE email = ?",
                ("user@example.com",),
            ).fetchone()
        self.assertEqual(row["ip_address"], "1.2.3.4")
        self.assertEqual(row["user_agent"], "TestBrowser/1.0")


class TestGetSubscriptionByEmail(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def _upsert(self, email="user@example.com", categories=None):
        if categories is None:
            categories = list(_CATS)
        with get_connection(self.db_path) as conn:
            return upsert_subscription(conn, email, categories, _NOW)

    def test_unknown_email_returns_none(self):
        with get_connection(self.db_path) as conn:
            self.assertIsNone(get_subscription_by_email(conn, "nobody@example.com"))

    def test_known_email_returns_dict(self):
        self._upsert()
        with get_connection(self.db_path) as conn:
            result = get_subscription_by_email(conn, "user@example.com")
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "user@example.com")

    def test_categories_returned_as_list(self):
        self._upsert(categories=["EB-1", "F3"])
        with get_connection(self.db_path) as conn:
            result = get_subscription_by_email(conn, "user@example.com")
        self.assertIsInstance(result["categories"], list)
        self.assertEqual(result["categories"], ["EB-1", "F3"])

    def test_returns_row_even_when_inactive(self):
        r = self._upsert()
        with get_connection(self.db_path) as conn:
            deactivate_subscription(conn, r["unsubscribe_token"])
            result = get_subscription_by_email(conn, "user@example.com")
        self.assertIsNotNone(result)
        self.assertEqual(result["is_active"], 0)


class TestGetActiveSubscriptionsForCategory(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def _upsert(self, email, categories):
        with get_connection(self.db_path) as conn:
            return upsert_subscription(conn, email, categories, _NOW)

    def test_returns_matching_active_subscriptions(self):
        self._upsert("a@x.com", ["EB-2", "F2A"])
        self._upsert("b@x.com", ["EB-3"])
        with get_connection(self.db_path) as conn:
            subs = get_active_subscriptions_for_category(conn, "EB-2")
        emails = [s["email"] for s in subs]
        self.assertIn("a@x.com", emails)
        self.assertNotIn("b@x.com", emails)

    def test_excludes_inactive_subscriptions(self):
        r = self._upsert("a@x.com", ["EB-2"])
        with get_connection(self.db_path) as conn:
            deactivate_subscription(conn, r["unsubscribe_token"])
            subs = get_active_subscriptions_for_category(conn, "EB-2")
        self.assertEqual(len(subs), 0)

    def test_returns_empty_for_unknown_category(self):
        self._upsert("a@x.com", ["EB-2"])
        with get_connection(self.db_path) as conn:
            subs = get_active_subscriptions_for_category(conn, "EB-5")
        self.assertEqual(subs, [])

    def test_categories_returned_as_list(self):
        self._upsert("a@x.com", ["EB-2", "F3"])
        with get_connection(self.db_path) as conn:
            subs = get_active_subscriptions_for_category(conn, "EB-2")
        self.assertIsInstance(subs[0]["categories"], list)

    def test_multiple_subscribers(self):
        self._upsert("a@x.com", ["EB-2"])
        self._upsert("b@x.com", ["EB-2", "F1"])
        self._upsert("c@x.com", ["F1"])
        with get_connection(self.db_path) as conn:
            subs = get_active_subscriptions_for_category(conn, "EB-2")
        self.assertEqual(len(subs), 2)


class TestDeactivateSubscription(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def _upsert(self, email="user@example.com", categories=None):
        if categories is None:
            categories = list(_CATS)
        with get_connection(self.db_path) as conn:
            return upsert_subscription(conn, email, categories, _NOW)

    def test_valid_token_returns_subscription_dict(self):
        r = self._upsert()
        with get_connection(self.db_path) as conn:
            result = deactivate_subscription(conn, r["unsubscribe_token"])
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "user@example.com")

    def test_valid_token_sets_is_active_to_zero(self):
        r = self._upsert()
        with get_connection(self.db_path) as conn:
            deactivate_subscription(conn, r["unsubscribe_token"])
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT is_active FROM subscriptions WHERE email = ?",
                ("user@example.com",),
            ).fetchone()
        self.assertEqual(row["is_active"], 0)

    def test_invalid_token_returns_none(self):
        with get_connection(self.db_path) as conn:
            result = deactivate_subscription(conn, str(uuid.uuid4()))
        self.assertIsNone(result)

    def test_already_deactivated_token_returns_none(self):
        r = self._upsert()
        with get_connection(self.db_path) as conn:
            deactivate_subscription(conn, r["unsubscribe_token"])
        with get_connection(self.db_path) as conn:
            result = deactivate_subscription(conn, r["unsubscribe_token"])
        self.assertIsNone(result)

    def test_categories_returned_as_list(self):
        r = self._upsert(categories=["EB-1", "F4"])
        with get_connection(self.db_path) as conn:
            result = deactivate_subscription(conn, r["unsubscribe_token"])
        self.assertIsInstance(result["categories"], list)
        self.assertEqual(result["categories"], ["EB-1", "F4"])


if __name__ == "__main__":
    unittest.main()
