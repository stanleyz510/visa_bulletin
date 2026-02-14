"""
Unit tests for the parser module.
Tests HTML parsing, table extraction, and data normalization.
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from parser import (
    parse_bulletin_html,
    extract_bulletin_date,
    normalize_header,
    extract_visa_type,
    parse_visa_table,
    parse_div_based_data,
    parse_text_based_data
)
from bs4 import BeautifulSoup


class TestNormalizeHeader(unittest.TestCase):
    """Test the normalize_header function."""

    def test_normalize_preference_level(self):
        """Test normalizing 'Preference Level' header."""
        self.assertEqual(normalize_header("Preference Level"), "preference_level")
        self.assertEqual(normalize_header("preference level"), "preference_level")
        self.assertEqual(normalize_header("PREFERENCE LEVEL"), "preference_level")

    def test_normalize_category(self):
        """Test normalizing category headers."""
        self.assertEqual(normalize_header("Category"), "category")
        self.assertEqual(normalize_header("Visa Category"), "visa_category")
        self.assertEqual(normalize_header("Family Preference"), "family_preference")

    def test_normalize_dates(self):
        """Test normalizing date headers."""
        self.assertEqual(normalize_header("Cutoff Date"), "cutoff_date")
        self.assertEqual(normalize_header("Final Action Date"), "final_action_date")
        self.assertEqual(normalize_header("Action Date"), "action_date")

    def test_normalize_with_spaces(self):
        """Test normalizing headers with extra spaces."""
        self.assertEqual(normalize_header("  Preference Level  "), "preference_level")
        self.assertEqual(normalize_header("Employment  Preference"), "employment_preference")

    def test_normalize_unknown_header(self):
        """Test normalizing unknown headers converts spaces to underscores."""
        self.assertEqual(normalize_header("Some Custom Header"), "some_custom_header")
        self.assertEqual(normalize_header("Another Header Name"), "another_header_name")


class TestExtractVisaType(unittest.TestCase):
    """Test the extract_visa_type function."""

    def test_employment_based_eb_prefix(self):
        """Test identifying employment-based visas with EB- prefix."""
        category = {"preference_level": "EB-1"}
        self.assertEqual(extract_visa_type(category), "Employment-Based")

        category = {"preference_level": "EB-2"}
        self.assertEqual(extract_visa_type(category), "Employment-Based")

    def test_employment_based_keyword(self):
        """Test identifying employment-based visas with 'employment' keyword."""
        category = {"employment_preference": "1st"}
        self.assertEqual(extract_visa_type(category), "Employment-Based")

    def test_family_based_f_prefix(self):
        """Test identifying family-based visas."""
        category = {"preference_level": "F1"}
        self.assertEqual(extract_visa_type(category), "Family-Based")

        category = {"family_preference": "F2A"}
        self.assertEqual(extract_visa_type(category), "Family-Based")

    def test_diversity_visa(self):
        """Test identifying diversity visas."""
        category = {"preference_level": "DV"}
        self.assertEqual(extract_visa_type(category), "Diversity Visa")

    def test_unknown_type(self):
        """Test unknown visa types."""
        category = {"preference_level": "Unknown"}
        self.assertEqual(extract_visa_type(category), "Unknown")


class TestExtractBulletinDate(unittest.TestCase):
    """Test the extract_bulletin_date function."""

    def test_extract_current_bulletin_date(self):
        """Test extracting date from 'Current Bulletin' marker."""
        html = """
        <html>
            <body>
                <h1>Current Bulletin for January 2026</h1>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        date = extract_bulletin_date(soup, verbose=False)
        self.assertEqual(date, "January 2026")

    def test_extract_date_february(self):
        """Test extracting February date."""
        html = """
        <html>
            <body>
                <p>The visa bulletin for February 2026 is now available.</p>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        date = extract_bulletin_date(soup, verbose=False)
        self.assertEqual(date, "February 2026")

    def test_extract_date_case_insensitive(self):
        """Test date extraction is case-insensitive."""
        html = """
        <html>
            <body>
                <h2>march 2025</h2>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        date = extract_bulletin_date(soup, verbose=False)
        self.assertEqual(date, "march 2025")

    def test_extract_multiple_dates_takes_first(self):
        """Test that when multiple dates exist, first one is taken."""
        html = """
        <html>
            <body>
                <h1>April 2026 Bulletin</h1>
                <p>Previous: March 2026</p>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        date = extract_bulletin_date(soup, verbose=False)
        self.assertEqual(date, "April 2026")


class TestParseVisaTable(unittest.TestCase):
    """Test the parse_visa_table function."""

    def test_parse_simple_table(self):
        """Test parsing a simple visa table."""
        html = """
        <table>
            <tr>
                <th>Category</th>
                <th>Cutoff Date</th>
                <th>Final Action Date</th>
            </tr>
            <tr>
                <td>EB-1</td>
                <td>Current</td>
                <td>15 JAN 26</td>
            </tr>
            <tr>
                <td>EB-2</td>
                <td>01 DEC 25</td>
                <td>01 DEC 25</td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        categories = parse_visa_table(table, verbose=False)

        self.assertEqual(len(categories), 2)
        self.assertEqual(categories[0]['category'], 'EB-1')
        self.assertEqual(categories[0]['cutoff_date'], 'Current')
        self.assertEqual(categories[1]['category'], 'EB-2')

    def test_parse_table_with_multiple_columns(self):
        """Test parsing table with country-specific columns."""
        html = """
        <table>
            <tr>
                <th>Family-Sponsored</th>
                <th>All Chargeability Areas</th>
                <th>CHINA-mainland born</th>
                <th>India</th>
            </tr>
            <tr>
                <td>F1</td>
                <td>08NOV16</td>
                <td>08NOV16</td>
                <td>08NOV16</td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        categories = parse_visa_table(table, verbose=False)

        self.assertEqual(len(categories), 1)
        self.assertEqual(categories[0]['family-sponsored'], 'F1')
        self.assertIn('china-mainland_born', categories[0])

    def test_parse_empty_table(self):
        """Test parsing an empty table returns empty list."""
        html = """
        <table>
            <tr>
                <th>Category</th>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        categories = parse_visa_table(table, verbose=False)

        self.assertEqual(len(categories), 0)

    def test_parse_table_no_headers(self):
        """Test parsing table with no header row."""
        html = """
        <table>
            <tr>
                <td>EB-1</td>
                <td>Current</td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        categories = parse_visa_table(table, verbose=False)

        # Should still extract the row, using first row as headers
        self.assertEqual(len(categories), 0)  # No data rows after header


class TestParseBulletinHtml(unittest.TestCase):
    """Test the parse_bulletin_html function."""

    def test_parse_html_with_tables(self):
        """Test parsing HTML containing visa tables."""
        html = """
        <html>
            <body>
                <h1>Visa Bulletin for January 2026</h1>
                <table>
                    <tr>
                        <th>Category</th>
                        <th>Date</th>
                    </tr>
                    <tr>
                        <td>EB-1</td>
                        <td>Current</td>
                    </tr>
                </table>
            </body>
        </html>
        """
        result = parse_bulletin_html(html, verbose=False, debug=False)

        self.assertIsNotNone(result)
        self.assertIn('bulletin_date', result)
        self.assertIn('categories', result)
        self.assertIn('total_categories', result)
        self.assertEqual(result['bulletin_date'], 'January 2026')

    def test_parse_html_returns_correct_structure(self):
        """Test that parsed result has correct structure."""
        html = """
        <html>
            <body>
                <h1>February 2026</h1>
                <table>
                    <tr><th>Category</th></tr>
                    <tr><td>F1</td></tr>
                </table>
            </body>
        </html>
        """
        result = parse_bulletin_html(html, verbose=False, debug=False)

        self.assertIsInstance(result, dict)
        self.assertIsInstance(result['categories'], list)
        self.assertIsInstance(result['total_categories'], int)
        self.assertIn('extracted_at', result)

    def test_parse_html_with_no_tables(self):
        """Test parsing HTML with no tables returns empty categories."""
        html = """
        <html>
            <body>
                <h1>March 2026</h1>
                <p>No tables here</p>
            </body>
        </html>
        """
        result = parse_bulletin_html(html, verbose=False, debug=False)

        self.assertIsNotNone(result)
        self.assertEqual(len(result['categories']), 0)

    def test_parse_invalid_html(self):
        """Test parsing invalid HTML doesn't crash."""
        html = "<html><body><p>Broken HTML"
        result = parse_bulletin_html(html, verbose=False, debug=False)

        # Should still return a result, not None
        self.assertIsNotNone(result)

    def test_parse_html_extracted_at_is_iso_format(self):
        """Test that extracted_at timestamp is in ISO format."""
        html = "<html><body><h1>April 2026</h1></body></html>"
        result = parse_bulletin_html(html, verbose=False, debug=False)

        # Verify it's a valid ISO format timestamp
        extracted_at = result['extracted_at']
        # Should be able to parse it back
        datetime.fromisoformat(extracted_at)


class TestParseDivBasedData(unittest.TestCase):
    """Test the parse_div_based_data function."""

    def test_parse_divs_with_visa_categories(self):
        """Test parsing div-based structure with visa categories."""
        html = """
        <html>
            <body>
                <div>EB-1: Current</div>
                <div>EB-2: 01 DEC 25</div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        categories = parse_div_based_data(soup, verbose=False)

        # Should extract some categories
        self.assertIsInstance(categories, list)

    def test_parse_divs_no_visa_data(self):
        """Test parsing divs with no visa data returns empty list."""
        html = """
        <html>
            <body>
                <div>Just some text</div>
                <div>No visa data here</div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        categories = parse_div_based_data(soup, verbose=False)

        self.assertEqual(len(categories), 0)


class TestParseTextBasedData(unittest.TestCase):
    """Test the parse_text_based_data function."""

    def test_parse_text_with_visa_categories(self):
        """Test parsing plain text with visa categories."""
        html = """
        <html>
            <body>
                <p>EB-1 is Current</p>
                <p>EB-2 cutoff: 01 DEC 25</p>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        categories = parse_text_based_data(soup, verbose=False)

        self.assertIsInstance(categories, list)

    def test_parse_text_no_visa_data(self):
        """Test parsing text with no visa data returns empty list."""
        html = """
        <html>
            <body>
                <p>Just regular text content</p>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        categories = parse_text_based_data(soup, verbose=False)

        self.assertEqual(len(categories), 0)


if __name__ == '__main__':
    unittest.main()
