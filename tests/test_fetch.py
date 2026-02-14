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
    extract_bulletin_url_from_landing_page,
    BASE_DOMAIN
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


if __name__ == '__main__':
    unittest.main()
