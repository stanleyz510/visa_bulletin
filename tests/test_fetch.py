"""
Unit tests for the fetch module.
Tests URL construction, link extraction, and bulletin fetching logic.
"""

import unittest
from unittest.mock import patch, Mock
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetch import (
    construct_bulletin_url,
    create_argument_parser,
    extract_bulletin_url_from_landing_page,
    scrape_visa_bulletin,
    BASE_DOMAIN,
    DEFAULT_DB_PATH,
)


class TestConstructBulletinUrl(unittest.TestCase):
    """Test the construct_bulletin_url function."""

    def test_construct_url_january_2026(self):
        """Test URL construction for January 2026."""
        url = construct_bulletin_url(2026, "january")
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-january-2026.html"
        self.assertEqual(url, expected)

    def test_construct_url_february_2026(self):
        """Test URL construction for February 2026."""
        url = construct_bulletin_url(2026, "february")
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-february-2026.html"
        self.assertEqual(url, expected)

    def test_construct_url_different_year(self):
        """Test URL construction for different year."""
        url = construct_bulletin_url(2025, "december")
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2025/visa-bulletin-for-december-2025.html"
        self.assertEqual(url, expected)

    def test_construct_url_uppercase_month(self):
        """Test URL construction handles uppercase month names."""
        url = construct_bulletin_url(2026, "MARCH")
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-march-2026.html"
        self.assertEqual(url, expected)

    def test_construct_url_mixed_case_month(self):
        """Test URL construction handles mixed case month names."""
        url = construct_bulletin_url(2026, "ApRiL")
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-april-2026.html"
        self.assertEqual(url, expected)


class TestExtractBulletinUrl(unittest.TestCase):
    """Test the extract_bulletin_url_from_landing_page function."""

    def test_extract_from_current_bulletin_section(self):
        """Test extraction from 'Current Visa Bulletin' section (Strategy 1)."""
        html = """
        <html>
            <body>
                <ul id="recent_bulletins">
                    <li>
                        <h2>Current Visa Bulletin</h2>
                        <a class='btn btn-lg btn-success' href='/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-january-2026.html'>
                            January 2026
                        </a>
                    </li>
                </ul>
            </body>
        </html>
        """
        url = extract_bulletin_url_from_landing_page(html, verbose=False)
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-january-2026.html"
        self.assertEqual(url, expected)

    def test_extract_from_recent_bulletins_list(self):
        """Test extraction from recent_bulletins list (Strategy 2)."""
        html = """
        <html>
            <body>
                <ul id="recent_bulletins">
                    <li>
                        <a href='/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-february-2026.html'>
                            February 2026
                        </a>
                    </li>
                    <li>
                        <a href='/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-january-2026.html'>
                            January 2026
                        </a>
                    </li>
                </ul>
            </body>
        </html>
        """
        url = extract_bulletin_url_from_landing_page(html, verbose=False)
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-february-2026.html"
        self.assertEqual(url, expected)

    def test_extract_handles_absolute_url(self):
        """Test that function handles already absolute URLs correctly."""
        html = """
        <html>
            <body>
                <ul id="recent_bulletins">
                    <li>
                        <h2>Current Visa Bulletin</h2>
                        <a class='btn' href='https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-march-2026.html'>
                            March 2026
                        </a>
                    </li>
                </ul>
            </body>
        </html>
        """
        url = extract_bulletin_url_from_landing_page(html, verbose=False)
        expected = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-march-2026.html"
        self.assertEqual(url, expected)

    @patch('fetch.datetime')
    def test_extract_fallback_to_current_date(self, mock_datetime):
        """Test fallback to constructing URL from current date (Strategy 3)."""
        # Mock datetime to return a specific date
        mock_now = Mock()
        mock_now.strftime.return_value = 'february'
        mock_now.year = 2026
        mock_datetime.now.return_value = mock_now

        html = """
        <html>
            <body>
                <p>No bulletin links here</p>
            </body>
        </html>
        """
        url = extract_bulletin_url_from_landing_page(html, verbose=False)
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-february-2026.html"
        self.assertEqual(url, expected)

    def test_extract_handles_malformed_html(self):
        """Test that function handles malformed HTML gracefully."""
        html = "<html><body><p>Broken HTML"
        # Should fall back to Strategy 3 (construct from current date)
        url = extract_bulletin_url_from_landing_page(html, verbose=False)
        # Just verify it returns a URL, not None
        self.assertIsNotNone(url)
        self.assertIn(BASE_DOMAIN, url)

    def test_extract_with_verbose_output(self):
        """Test that verbose mode doesn't break functionality."""
        html = """
        <html>
            <body>
                <ul id="recent_bulletins">
                    <li>
                        <h2>Current Visa Bulletin</h2>
                        <a class='btn' href='/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-april-2026.html'>
                            April 2026
                        </a>
                    </li>
                </ul>
            </body>
        </html>
        """
        # With verbose=True, should still work
        url = extract_bulletin_url_from_landing_page(html, verbose=True)
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-april-2026.html"
        self.assertEqual(url, expected)

    def test_extract_case_insensitive_current_bulletin(self):
        """Test that 'Current Bulletin' detection is case-insensitive."""
        html = """
        <html>
            <body>
                <ul>
                    <li>
                        <h2>CURRENT visa BULLETIN</h2>
                        <a class='btn' href='/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-may-2026.html'>
                            May 2026
                        </a>
                    </li>
                </ul>
            </body>
        </html>
        """
        url = extract_bulletin_url_from_landing_page(html, verbose=False)
        expected = f"{BASE_DOMAIN}/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-may-2026.html"
        self.assertEqual(url, expected)


class TestNewCliArguments(unittest.TestCase):
    """Test the new CLI arguments added for DB storage and comparison."""

    def _parse(self, args):
        parser = create_argument_parser()
        return parser.parse_args(args)

    def test_run_type_default_is_manual(self):
        args = self._parse([])
        self.assertEqual(args.run_type, "manual")

    def test_run_type_accepts_valid_values(self):
        for rtype in ("official", "test", "benchmark", "manual"):
            args = self._parse([f"--run-type={rtype}"])
            self.assertEqual(args.run_type, rtype)

    def test_run_type_rejects_invalid_value(self):
        parser = create_argument_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--run-type=invalid"])

    def test_db_default(self):
        args = self._parse([])
        self.assertEqual(args.db, DEFAULT_DB_PATH)

    def test_db_custom_path(self):
        args = self._parse(["--db=/tmp/custom.db"])
        self.assertEqual(args.db, "/tmp/custom.db")

    def test_no_db_flag(self):
        args = self._parse(["--no-db"])
        self.assertTrue(args.no_db)

    def test_no_db_default_false(self):
        args = self._parse([])
        self.assertFalse(args.no_db)

    def test_compare_flag(self):
        args = self._parse(["--compare"])
        self.assertTrue(args.compare)

    def test_compare_default_false(self):
        args = self._parse([])
        self.assertFalse(args.compare)

    def test_history_flag(self):
        args = self._parse(["--history"])
        self.assertTrue(args.history)

    def test_history_default_false(self):
        args = self._parse([])
        self.assertFalse(args.history)


class TestScrapeVisaBulletinDbIntegration(unittest.TestCase):
    """Test that scrape_visa_bulletin interacts with store correctly."""

    def _make_data(self):
        return {
            "bulletin_date": "January 2026",
            "extracted_at": "2026-01-15T10:00:00",
            "categories": [{"visa_category": "EB-1", "china": "01 JAN 26"}],
            "total_categories": 1,
        }

    @patch("fetch.save_to_json", return_value=True)
    @patch("fetch.parse_bulletin_html")
    @patch("fetch.extract_bulletin_url_from_landing_page", return_value="http://example.com/bulletin")
    @patch("fetch.fetch_bulletin_page")
    @patch("fetch.insert_run")
    @patch("fetch.init_db")
    def test_db_not_called_when_no_db(
        self, mock_init_db, mock_insert_run, mock_fetch, mock_extract, mock_parse, mock_save
    ):
        mock_fetch.return_value = "<html></html>"
        mock_parse.return_value = self._make_data()
        scrape_visa_bulletin(use_db=False)
        mock_init_db.assert_not_called()
        mock_insert_run.assert_not_called()

    @patch("fetch.save_to_json", return_value=True)
    @patch("fetch.parse_bulletin_html")
    @patch("fetch.extract_bulletin_url_from_landing_page", return_value="http://example.com/bulletin")
    @patch("fetch.fetch_bulletin_page")
    @patch("fetch.get_connection")
    @patch("fetch.insert_run", return_value=20260101100000001)
    @patch("fetch.init_db")
    def test_insert_run_called_on_success(
        self,
        mock_init_db,
        mock_insert_run,
        mock_get_conn,
        mock_fetch,
        mock_extract,
        mock_parse,
        mock_save,
    ):
        mock_fetch.return_value = "<html></html>"
        mock_parse.return_value = self._make_data()
        # get_connection used as context manager
        mock_get_conn.return_value.__enter__ = Mock(return_value=Mock())
        mock_get_conn.return_value.__exit__ = Mock(return_value=False)
        success, _run_id, _data = scrape_visa_bulletin(use_db=True)
        self.assertTrue(success)
        mock_init_db.assert_called_once()
        mock_insert_run.assert_called_once()
        call_kwargs = mock_insert_run.call_args
        self.assertTrue(call_kwargs.kwargs.get("success") or call_kwargs.args[3])

    @patch("fetch.fetch_bulletin_page", return_value=None)
    @patch("fetch.get_connection")
    @patch("fetch.insert_run", return_value=20260101100000001)
    @patch("fetch.init_db")
    def test_failed_run_recorded_on_network_error(
        self, mock_init_db, mock_insert_run, mock_get_conn, mock_fetch
    ):
        mock_get_conn.return_value.__enter__ = Mock(return_value=Mock())
        mock_get_conn.return_value.__exit__ = Mock(return_value=False)
        success, _run_id, _data = scrape_visa_bulletin(use_db=True)
        self.assertFalse(success)
        mock_insert_run.assert_called_once()
        call_kwargs = mock_insert_run.call_args
        # success should be False on failure
        success_val = call_kwargs.kwargs.get("success", call_kwargs.args[3] if len(call_kwargs.args) > 3 else None)
        self.assertFalse(success_val)

    @patch("fetch.save_to_json", return_value=True)
    @patch("fetch.parse_bulletin_html")
    @patch("fetch.extract_bulletin_url_from_landing_page", return_value="http://example.com/bulletin")
    @patch("fetch.fetch_bulletin_page")
    @patch("fetch.get_last_successful_run", return_value=None)
    @patch("fetch.get_connection")
    @patch("fetch.insert_run", return_value=20260101100000001)
    @patch("fetch.init_db")
    def test_compare_skipped_gracefully_when_no_prev_run(
        self,
        mock_init_db,
        mock_insert_run,
        mock_get_conn,
        mock_get_last,
        mock_fetch,
        mock_extract,
        mock_parse,
        mock_save,
    ):
        mock_fetch.return_value = "<html></html>"
        mock_parse.return_value = self._make_data()
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = Mock(return_value=False)
        success, _run_id, _data = scrape_visa_bulletin(use_db=True, do_compare=True)
        self.assertTrue(success)
        # get_last_successful_run should have been called
        mock_get_last.assert_called_once()


if __name__ == '__main__':
    unittest.main()
