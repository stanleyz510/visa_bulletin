"""Tests for store.py — SQLite storage module."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from store import (
    DEFAULT_DB_PATH,
    generate_run_id,
    get_connection,
    get_last_successful_run,
    get_runs,
    init_db,
    insert_comparison,
    insert_run,
)


def _make_db() -> str:
    """Create a fresh temp DB file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _sample_data(bulletin_date: str = "January 2026") -> dict:
    return {
        "bulletin_date": bulletin_date,
        "extracted_at": "2026-01-15T10:00:00",
        "categories": [
            {"visa_category": "EB-1", "china": "01 JAN 26", "india": "01 JAN 26"},
            {"visa_category": "EB-2", "china": "01 SEP 21", "india": "01 JUN 13"},
        ],
        "total_categories": 2,
    }


class TestInitDb(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_creates_runs_table(self):
        init_db(self.db_path)
        with get_connection(self.db_path) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        self.assertIn("runs", tables)

    def test_creates_comparisons_table(self):
        init_db(self.db_path)
        with get_connection(self.db_path) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        self.assertIn("comparisons", tables)

    def test_idempotent_double_call(self):
        """Calling init_db twice must not raise or corrupt the DB."""
        init_db(self.db_path)
        init_db(self.db_path)  # should not raise
        with get_connection(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        self.assertEqual(count, 0)

    def test_wal_mode_enabled(self):
        init_db(self.db_path)
        with get_connection(self.db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode, "wal")


class TestGenerateRunId(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def test_id_is_17_digits(self):
        with get_connection(self.db_path) as conn:
            run_id = generate_run_id(conn, "runs")
        self.assertEqual(len(str(run_id)), 17)

    def test_id_starts_with_valid_datetime(self):
        with get_connection(self.db_path) as conn:
            run_id = generate_run_id(conn, "runs")
        prefix = str(run_id)[:14]
        # Should parse as a valid datetime
        dt = datetime.strptime(prefix, "%Y%m%d%H%M%S")
        self.assertIsNotNone(dt)

    def test_first_id_ends_with_001(self):
        with get_connection(self.db_path) as conn:
            run_id = generate_run_id(conn, "runs")
        self.assertEqual(run_id % 1000, 1)

    def test_sequential_ids_within_same_second(self):
        """Insert a run with the current-second prefix, then generate next ID."""
        now = datetime.now(timezone.utc)
        prefix = now.strftime("%Y%m%d%H%M%S")
        existing_id = int(prefix + "001")
        with get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs (id, run_type, started_at, success) VALUES (?, 'official', ?, 1)",
                (existing_id, now.isoformat()),
            )
            conn.commit()
            new_id = generate_run_id(conn, "runs")
        self.assertEqual(new_id, existing_id + 1)

    def test_comparisons_table_uses_separate_id_space(self):
        """IDs in runs and comparisons are independent; no cross-table uniqueness required."""
        with get_connection(self.db_path) as conn:
            run_id = generate_run_id(conn, "runs")
            cmp_id = generate_run_id(conn, "comparisons")
        # Both end with 001 (first in their respective tables for this second)
        self.assertEqual(run_id % 1000, 1)
        self.assertEqual(cmp_id % 1000, 1)


class TestInsertRun(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def test_successful_run_returns_id(self):
        with get_connection(self.db_path) as conn:
            run_id = insert_run(
                conn,
                run_type="official",
                started_at="2026-01-15T10:00:00",
                success=True,
                bulletin_date="January 2026",
                data=_sample_data(),
            )
        self.assertIsInstance(run_id, int)
        self.assertEqual(len(str(run_id)), 17)

    def test_failed_run_with_error_message(self):
        with get_connection(self.db_path) as conn:
            run_id = insert_run(
                conn,
                run_type="official",
                started_at="2026-01-15T10:00:00",
                success=False,
                error_message="Network timeout",
            )
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        self.assertEqual(row["success"], 0)
        self.assertEqual(row["error_message"], "Network timeout")
        self.assertIsNone(row["data_json"])

    def test_data_serialised_to_json(self):
        data = _sample_data()
        with get_connection(self.db_path) as conn:
            run_id = insert_run(
                conn,
                run_type="test",
                started_at="2026-01-15T10:00:00",
                success=True,
                data=data,
            )
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT data_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        loaded = json.loads(row["data_json"])
        self.assertEqual(loaded["bulletin_date"], "January 2026")
        self.assertEqual(len(loaded["categories"]), 2)

    def test_categories_count_denormalised(self):
        data = _sample_data()
        with get_connection(self.db_path) as conn:
            run_id = insert_run(
                conn,
                run_type="official",
                started_at="2026-01-15T10:00:00",
                success=True,
                data=data,
            )
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT categories_count FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        self.assertEqual(row["categories_count"], 2)

    def test_invalid_run_type_raises(self):
        with get_connection(self.db_path) as conn:
            with self.assertRaises(Exception):
                insert_run(
                    conn,
                    run_type="invalid_type",
                    started_at="2026-01-15T10:00:00",
                    success=True,
                )

    def test_all_run_types_accepted(self):
        with get_connection(self.db_path) as conn:
            for rtype in ("official", "test", "benchmark", "manual"):
                run_id = insert_run(
                    conn,
                    run_type=rtype,
                    started_at="2026-01-15T10:00:00",
                    success=True,
                )
                self.assertIsInstance(run_id, int)


class TestGetLastSuccessfulRun(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def _insert(self, run_type="official", success=True, started_at=None, data=None):
        if started_at is None:
            started_at = datetime.now(timezone.utc).isoformat()
        with get_connection(self.db_path) as conn:
            return insert_run(
                conn,
                run_type=run_type,
                started_at=started_at,
                success=success,
                bulletin_date="January 2026",
                data=data or _sample_data(),
            )

    def test_returns_none_when_no_runs(self):
        with get_connection(self.db_path) as conn:
            result = get_last_successful_run(conn, "official")
        self.assertIsNone(result)

    def test_returns_most_recent_successful_run(self):
        self._insert(started_at="2026-01-01T10:00:00")
        self._insert(started_at="2026-01-15T10:00:00")
        with get_connection(self.db_path) as conn:
            result = get_last_successful_run(conn, "official")
        self.assertIsNotNone(result)
        self.assertEqual(result["started_at"], "2026-01-15T10:00:00")

    def test_ignores_failed_runs(self):
        self._insert(success=False, started_at="2026-01-15T12:00:00")
        self._insert(success=True, started_at="2026-01-01T10:00:00")
        with get_connection(self.db_path) as conn:
            result = get_last_successful_run(conn, "official")
        self.assertIsNotNone(result)
        self.assertEqual(result["started_at"], "2026-01-01T10:00:00")

    def test_filters_by_run_type(self):
        self._insert(run_type="test", started_at="2026-01-15T10:00:00")
        with get_connection(self.db_path) as conn:
            result = get_last_successful_run(conn, "official")
        self.assertIsNone(result)

    def test_exclude_run_id(self):
        run_id1 = self._insert(started_at="2026-01-01T10:00:00")
        run_id2 = self._insert(started_at="2026-01-15T10:00:00")
        with get_connection(self.db_path) as conn:
            result = get_last_successful_run(conn, "official", exclude_run_id=run_id2)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], run_id1)

    def test_data_json_deserialised(self):
        self._insert(data=_sample_data("February 2026"))
        with get_connection(self.db_path) as conn:
            result = get_last_successful_run(conn, "official")
        self.assertIn("data", result)
        self.assertEqual(result["data"]["bulletin_date"], "February 2026")
        self.assertIsInstance(result["data"]["categories"], list)


class TestInsertComparison(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)
        # Insert two runs to reference
        with get_connection(self.db_path) as conn:
            self.run_id1 = insert_run(
                conn,
                run_type="official",
                started_at="2026-01-01T10:00:00",
                success=True,
                data=_sample_data("January 2026"),
            )
            self.run_id2 = insert_run(
                conn,
                run_type="official",
                started_at="2026-02-01T10:00:00",
                success=True,
                data=_sample_data("February 2026"),
            )

    def tearDown(self):
        os.unlink(self.db_path)

    def _sample_diff(self, has_changes=True):
        return {
            "compared_at": "2026-02-01T10:05:00",
            "current_run_bulletin_date": "February 2026",
            "previous_run_bulletin_date": "January 2026",
            "has_changes": has_changes,
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

    def test_insert_comparison_returns_id(self):
        diff = self._sample_diff()
        with get_connection(self.db_path) as conn:
            cmp_id = insert_comparison(
                conn,
                run_id=self.run_id2,
                previous_run_id=self.run_id1,
                compared_at=diff["compared_at"],
                diff=diff,
            )
        self.assertIsInstance(cmp_id, int)
        self.assertEqual(len(str(cmp_id)), 17)

    def test_diff_json_round_trips(self):
        diff = self._sample_diff()
        with get_connection(self.db_path) as conn:
            cmp_id = insert_comparison(
                conn,
                run_id=self.run_id2,
                previous_run_id=self.run_id1,
                compared_at=diff["compared_at"],
                diff=diff,
            )
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT diff_json, has_changes FROM comparisons WHERE id = ?", (cmp_id,)
            ).fetchone()
        loaded = json.loads(row["diff_json"])
        self.assertEqual(loaded["current_run_bulletin_date"], "February 2026")
        self.assertEqual(row["has_changes"], 1)

    def test_no_changes_recorded_correctly(self):
        diff = self._sample_diff(has_changes=False)
        with get_connection(self.db_path) as conn:
            cmp_id = insert_comparison(
                conn,
                run_id=self.run_id2,
                previous_run_id=self.run_id1,
                compared_at=diff["compared_at"],
                diff=diff,
            )
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT has_changes FROM comparisons WHERE id = ?", (cmp_id,)
            ).fetchone()
        self.assertEqual(row["has_changes"], 0)


class TestGetRuns(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_db()
        init_db(self.db_path)
        # Insert a variety of runs
        timestamps = [
            "2026-01-01T10:00:00",
            "2026-01-15T10:00:00",
            "2026-02-01T10:00:00",
        ]
        with get_connection(self.db_path) as conn:
            for i, ts in enumerate(timestamps):
                insert_run(
                    conn,
                    run_type="official" if i < 2 else "test",
                    started_at=ts,
                    success=(i != 1),  # second run is a failure
                    data=_sample_data(),
                )

    def tearDown(self):
        os.unlink(self.db_path)

    def test_returns_all_runs_by_default(self):
        with get_connection(self.db_path) as conn:
            runs = get_runs(conn)
        self.assertEqual(len(runs), 3)

    def test_reverse_chronological_order(self):
        with get_connection(self.db_path) as conn:
            runs = get_runs(conn)
        dates = [r["started_at"] for r in runs]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_limit_respected(self):
        with get_connection(self.db_path) as conn:
            runs = get_runs(conn, limit=2)
        self.assertEqual(len(runs), 2)

    def test_run_type_filter(self):
        with get_connection(self.db_path) as conn:
            runs = get_runs(conn, run_type="test")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_type"], "test")

    def test_success_only_filter(self):
        with get_connection(self.db_path) as conn:
            runs = get_runs(conn, success_only=True)
        self.assertTrue(all(r["success"] == 1 for r in runs))
        self.assertEqual(len(runs), 2)

    def test_data_json_not_included(self):
        """get_runs should not return the heavy data_json column."""
        with get_connection(self.db_path) as conn:
            runs = get_runs(conn)
        for r in runs:
            self.assertNotIn("data_json", r)


if __name__ == "__main__":
    unittest.main()
