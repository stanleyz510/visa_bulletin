"""Tests for main.py — full pipeline orchestration."""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import create_argument_parser
from store import DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _sample_bulletin(bulletin_date: str = "February 2026") -> dict:
    return {
        "bulletin_date": bulletin_date,
        "extracted_at": "2026-02-15T10:00:00",
        "categories": [
            {"visa_category": "EB-2", "china": "01 OCT 21", "india": "01 JUL 13"},
        ],
        "total_categories": 1,
    }


def _sample_comparison() -> dict:
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


# ---------------------------------------------------------------------------
# Tests: argument parsing
# ---------------------------------------------------------------------------

class TestMainArgParsing(unittest.TestCase):

    def _parse(self, args):
        return create_argument_parser().parse_args(args)

    def test_default_db_path(self):
        args = self._parse([])
        self.assertEqual(args.db, DEFAULT_DB_PATH)

    def test_no_notify_flag(self):
        args = self._parse(["--no-notify"])
        self.assertTrue(args.no_notify)

    def test_no_notify_default_false(self):
        args = self._parse([])
        self.assertFalse(args.no_notify)

    def test_updated_only_flag(self):
        args = self._parse(["--updated-only"])
        self.assertTrue(args.updated_only)

    def test_updated_only_default_false(self):
        args = self._parse([])
        self.assertFalse(args.updated_only)

    def test_print_local_flag(self):
        args = self._parse(["--print-local"])
        self.assertTrue(args.print_local)

    def test_print_local_default_false(self):
        args = self._parse([])
        self.assertFalse(args.print_local)

    def test_verbose_flag(self):
        args = self._parse(["-v"])
        self.assertTrue(args.verbose)

    def test_custom_output_file(self):
        args = self._parse(["-o", "custom.json"])
        self.assertEqual(args.output, "custom.json")


# ---------------------------------------------------------------------------
# Tests: pipeline orchestration
# ---------------------------------------------------------------------------

class TestMainPipeline(unittest.TestCase):
    """Test the main() orchestration logic with mocked dependencies."""

    def _run_main(self, extra_argv=None):
        """Run main.main() with given extra CLI args, capturing sys.exit."""
        import main as main_module
        argv = ["main.py"] + (extra_argv or [])
        with patch("sys.argv", argv):
            try:
                main_module.main()
            except SystemExit as e:
                return e.code
        return 0

    @patch("main.notify_subscribers", return_value={"sent": 1, "skipped": 0, "failed": 0})
    @patch("main.insert_comparison")
    @patch("main.format_comparison_for_display", return_value="[comparison output]")
    @patch("main.compare_bulletins")
    @patch("main.scrape_visa_bulletin")
    @patch("main.get_last_successful_run")
    @patch("main.get_connection")
    @patch("main.init_db")
    def test_successful_full_pipeline(
        self,
        mock_init,
        mock_get_conn,
        mock_get_last,
        mock_scrape,
        mock_compare,
        mock_format,
        mock_insert_cmp,
        mock_notify,
    ):
        """Full pipeline calls fetch, compare, store comparison, and notify."""
        prev_data = _sample_bulletin("January 2026")
        curr_data = _sample_bulletin("February 2026")
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_last.return_value = {
            "id": 100,
            "bulletin_date": "January 2026",
            "data": prev_data,
        }
        mock_scrape.return_value = (True, 200, curr_data)
        mock_compare.return_value = _sample_comparison()

        exit_code = self._run_main(["--print-local"])

        self.assertEqual(exit_code, 0)
        mock_scrape.assert_called_once()
        mock_compare.assert_called_once()
        mock_insert_cmp.assert_called_once()
        mock_notify.assert_called_once()

    @patch("main.scrape_visa_bulletin")
    @patch("main.get_last_successful_run")
    @patch("main.get_connection")
    @patch("main.init_db")
    def test_exits_1_on_fetch_failure(
        self, mock_init, mock_get_conn, mock_get_last, mock_scrape
    ):
        """Pipeline exits with code 1 when fetch fails."""
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_last.return_value = None
        mock_scrape.return_value = (False, None, None)

        exit_code = self._run_main(["--no-notify"])

        self.assertEqual(exit_code, 1)

    @patch("main.compare_bulletins")
    @patch("main.scrape_visa_bulletin")
    @patch("main.get_last_successful_run")
    @patch("main.get_connection")
    @patch("main.init_db")
    def test_skips_comparison_when_no_previous_run(
        self, mock_init, mock_get_conn, mock_get_last, mock_scrape, mock_compare
    ):
        """When there is no previous run, comparison is skipped."""
        curr_data = _sample_bulletin("February 2026")
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_last.return_value = None  # no previous run
        mock_scrape.return_value = (True, 200, curr_data)

        self._run_main(["--no-notify"])

        mock_compare.assert_not_called()

    @patch("main.notify_subscribers")
    @patch("main.insert_comparison")
    @patch("main.format_comparison_for_display", return_value="")
    @patch("main.compare_bulletins")
    @patch("main.scrape_visa_bulletin")
    @patch("main.get_last_successful_run")
    @patch("main.get_connection")
    @patch("main.init_db")
    def test_no_notify_flag_skips_notify(
        self,
        mock_init,
        mock_get_conn,
        mock_get_last,
        mock_scrape,
        mock_compare,
        mock_format,
        mock_insert_cmp,
        mock_notify,
    ):
        """--no-notify prevents notify_subscribers from being called."""
        prev_data = _sample_bulletin("January 2026")
        curr_data = _sample_bulletin("February 2026")
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_last.return_value = {"id": 1, "bulletin_date": "January 2026", "data": prev_data}
        mock_scrape.return_value = (True, 2, curr_data)
        mock_compare.return_value = _sample_comparison()

        exit_code = self._run_main(["--no-notify"])

        self.assertEqual(exit_code, 0)
        mock_notify.assert_not_called()

    @patch("main.notify_subscribers", return_value={"sent": 0, "skipped": 0, "failed": 0})
    @patch("main.insert_comparison")
    @patch("main.format_comparison_for_display", return_value="")
    @patch("main.compare_bulletins")
    @patch("main.scrape_visa_bulletin")
    @patch("main.get_last_successful_run")
    @patch("main.get_connection")
    @patch("main.init_db")
    def test_comparison_stored_in_db(
        self,
        mock_init,
        mock_get_conn,
        mock_get_last,
        mock_scrape,
        mock_compare,
        mock_format,
        mock_insert_cmp,
        mock_notify,
    ):
        """Comparison result is persisted via insert_comparison."""
        prev_data = _sample_bulletin("January 2026")
        curr_data = _sample_bulletin("February 2026")
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_last.return_value = {"id": 1, "bulletin_date": "January 2026", "data": prev_data}
        mock_scrape.return_value = (True, 2, curr_data)
        cmp = _sample_comparison()
        mock_compare.return_value = cmp

        self._run_main(["--print-local"])

        mock_insert_cmp.assert_called_once()
        call_kwargs = mock_insert_cmp.call_args
        # run_id=2 should be passed (as keyword arg)
        run_id_val = call_kwargs.kwargs.get("run_id")
        if run_id_val is None:
            # If passed positionally: (conn, run_id, previous_run_id, ...)
            args_list = list(call_kwargs.args)
            run_id_val = args_list[1] if len(args_list) > 1 else None
        self.assertEqual(run_id_val, 2)

    @patch("main.notify_subscribers", return_value={"sent": 1, "skipped": 0, "failed": 0})
    @patch("main.insert_comparison")
    @patch("main.format_comparison_for_display", return_value="")
    @patch("main.compare_bulletins")
    @patch("main.scrape_visa_bulletin")
    @patch("main.get_last_successful_run")
    @patch("main.get_connection")
    @patch("main.init_db")
    def test_print_local_forwarded_to_notify(
        self,
        mock_init,
        mock_get_conn,
        mock_get_last,
        mock_scrape,
        mock_compare,
        mock_format,
        mock_insert_cmp,
        mock_notify,
    ):
        """--print-local is forwarded as dry_run=True to notify_subscribers."""
        prev_data = _sample_bulletin("January 2026")
        curr_data = _sample_bulletin("February 2026")
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_last.return_value = {"id": 1, "bulletin_date": "January 2026", "data": prev_data}
        mock_scrape.return_value = (True, 2, curr_data)
        mock_compare.return_value = _sample_comparison()

        self._run_main(["--print-local"])

        call_kwargs = mock_notify.call_args
        dry_run_val = (
            call_kwargs.kwargs.get("dry_run")
            if call_kwargs.kwargs
            else None
        )
        if dry_run_val is None and call_kwargs.args:
            # positional: (comparison, current_bulletin, updated_only, db_path, config, dry_run)
            args_list = list(call_kwargs.args)
            if len(args_list) >= 6:
                dry_run_val = args_list[5]
        self.assertTrue(dry_run_val)


if __name__ == "__main__":
    unittest.main()
