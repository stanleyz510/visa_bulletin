"""
End-to-end tests using real HTML snapshots.
Tests the full scraper workflow with actual saved HTML pages.
"""

import unittest
import sys
from pathlib import Path
import json

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from parser import parse_bulletin_html
from fetch import extract_bulletin_url_from_landing_page
from persist import save_to_json, load_from_json

# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "e2e_test"
LANDING_PAGE_HTML = FIXTURES_DIR / "20250124.html"


class TestE2ELandingPage(unittest.TestCase):
    """End-to-end tests using the actual landing page HTML snapshot."""

    @classmethod
    def setUpClass(cls):
        """Load the HTML snapshot once for all tests."""
        if not LANDING_PAGE_HTML.exists():
            raise FileNotFoundError(f"Test fixture not found: {LANDING_PAGE_HTML}")

        with open(LANDING_PAGE_HTML, 'r', encoding='utf-8') as f:
            cls.landing_page_html = f.read()

    def test_landing_page_file_exists(self):
        """Test that the landing page snapshot file exists."""
        self.assertTrue(LANDING_PAGE_HTML.exists())
        self.assertGreater(LANDING_PAGE_HTML.stat().st_size, 100000)  # At least 100KB

    def test_extract_bulletin_url_from_snapshot(self):
        """Test extracting bulletin URL from real landing page snapshot."""
        url = extract_bulletin_url_from_landing_page(self.landing_page_html, verbose=False)

        self.assertIsNotNone(url)
        self.assertIn("travel.state.gov", url)
        self.assertIn("visa-bulletin", url)
        # Should match pattern: /visa-bulletin/YYYY/visa-bulletin-for-month-YYYY.html
        self.assertRegex(url, r'/visa-bulletin/\d{4}/visa-bulletin-for-\w+-\d{4}\.html')

    def test_parse_landing_page_returns_no_categories(self):
        """Test that parsing landing page (not bulletin) returns no categories."""
        result = parse_bulletin_html(self.landing_page_html, verbose=False, debug=False)

        self.assertIsNotNone(result)
        self.assertIn('categories', result)
        self.assertIn('total_categories', result)
        # Landing page should have no visa category data
        self.assertEqual(result['total_categories'], 0)
        self.assertEqual(len(result['categories']), 0)

    def test_parse_landing_page_has_valid_structure(self):
        """Test that parsed landing page has valid JSON structure."""
        result = parse_bulletin_html(self.landing_page_html, verbose=False, debug=False)

        # Check required fields
        self.assertIn('bulletin_date', result)
        self.assertIn('extracted_at', result)
        self.assertIn('categories', result)
        self.assertIn('total_categories', result)

        # Check data types
        self.assertIsInstance(result['bulletin_date'], str)
        self.assertIsInstance(result['extracted_at'], str)
        self.assertIsInstance(result['categories'], list)
        self.assertIsInstance(result['total_categories'], int)


class TestE2EBulletinPageMock(unittest.TestCase):
    """End-to-end tests using a mock bulletin page with real data structure."""

    def setUp(self):
        """Create a mock bulletin page HTML for testing."""
        self.mock_bulletin_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Visa Bulletin For January 2025</title>
        </head>
        <body>
            <h1>Visa Bulletin for January 2025</h1>

            <h2>A. FINAL ACTION DATES FOR EMPLOYMENT-BASED PREFERENCE CASES</h2>
            <table>
                <tr>
                    <th>Employment-based</th>
                    <th>All Chargeability Areas Except Those Listed</th>
                    <th>CHINA-mainland born</th>
                    <th>India</th>
                    <th>Mexico</th>
                    <th>Philippines</th>
                </tr>
                <tr>
                    <td>1st</td>
                    <td>C</td>
                    <td>01FEB23</td>
                    <td>01FEB23</td>
                    <td>C</td>
                    <td>C</td>
                </tr>
                <tr>
                    <td>2nd</td>
                    <td>01APR24</td>
                    <td>01SEP21</td>
                    <td>15JUL13</td>
                    <td>01APR24</td>
                    <td>01APR24</td>
                </tr>
                <tr>
                    <td>3rd</td>
                    <td>01JUN23</td>
                    <td>01MAY21</td>
                    <td>15NOV13</td>
                    <td>01JUN23</td>
                    <td>01JUN23</td>
                </tr>
            </table>

            <h2>B. FINAL ACTION DATES FOR FAMILY-SPONSORED PREFERENCE CASES</h2>
            <table>
                <tr>
                    <th>Family-Sponsored</th>
                    <th>All Chargeability Areas Except Those Listed</th>
                    <th>CHINA-mainland born</th>
                    <th>India</th>
                    <th>Mexico</th>
                    <th>Philippines</th>
                </tr>
                <tr>
                    <td>F1</td>
                    <td>08NOV16</td>
                    <td>08NOV16</td>
                    <td>08NOV16</td>
                    <td>22DEC06</td>
                    <td>01MAR13</td>
                </tr>
                <tr>
                    <td>F2A</td>
                    <td>01FEB24</td>
                    <td>01FEB24</td>
                    <td>01FEB24</td>
                    <td>01FEB23</td>
                    <td>01FEB24</td>
                </tr>
                <tr>
                    <td>F2B</td>
                    <td>01DEC16</td>
                    <td>01DEC16</td>
                    <td>01DEC16</td>
                    <td>15FEB09</td>
                    <td>22DEC12</td>
                </tr>
            </table>
        </body>
        </html>
        """

    def test_parse_mock_bulletin_extracts_categories(self):
        """Test parsing mock bulletin page extracts visa categories."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        self.assertIsNotNone(result)
        self.assertGreater(result['total_categories'], 0)
        self.assertGreater(len(result['categories']), 0)

    def test_parse_mock_bulletin_extracts_date(self):
        """Test that bulletin date is correctly extracted."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        self.assertEqual(result['bulletin_date'], "January 2025")

    def test_parse_mock_bulletin_has_employment_categories(self):
        """Test that employment-based categories are extracted."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        # Check if any category has employment-based data
        employment_categories = [
            cat for cat in result['categories']
            if 'employment-based' in cat or 'employment_based' in cat
        ]
        self.assertGreater(len(employment_categories), 0)

    def test_parse_mock_bulletin_has_family_categories(self):
        """Test that family-sponsored categories are extracted."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        # Check if any category has family-sponsored data
        family_categories = [
            cat for cat in result['categories']
            if 'family-sponsored' in cat or 'family_sponsored' in cat or 'family_preference' in cat
        ]
        self.assertGreater(len(family_categories), 0)

    def test_parse_mock_bulletin_extracts_country_data(self):
        """Test that country-specific data is extracted."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        # At least one category should have China or India data
        has_country_data = any(
            'china' in str(cat).lower() or 'india' in str(cat).lower()
            for cat in result['categories']
        )
        self.assertTrue(has_country_data)

    def test_parse_mock_bulletin_extracts_dates(self):
        """Test that actual dates are extracted (not just structure)."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        # Check that we have actual date values
        categories_with_dates = [
            cat for cat in result['categories']
            if any('01' in str(v) or 'C' in str(v) for v in cat.values())
        ]
        self.assertGreater(len(categories_with_dates), 0)

    def test_parse_mock_bulletin_correct_category_count(self):
        """Test that total_categories matches actual count."""
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        self.assertEqual(result['total_categories'], len(result['categories']))

    def test_full_workflow_parse_and_save(self):
        """Test complete workflow: parse HTML and save to JSON."""
        import tempfile
        import os

        # Parse the mock bulletin
        result = parse_bulletin_html(self.mock_bulletin_html, verbose=False, debug=False)

        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_file = f.name

        try:
            # Save and load
            save_success = save_to_json(result, temp_file, verbose=False)
            self.assertTrue(save_success)

            loaded_data = load_from_json(temp_file, verbose=False)
            self.assertIsNotNone(loaded_data)

            # Verify data integrity
            self.assertEqual(loaded_data['bulletin_date'], result['bulletin_date'])
            self.assertEqual(loaded_data['total_categories'], result['total_categories'])
            self.assertEqual(len(loaded_data['categories']), len(result['categories']))
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestE2EDataValidation(unittest.TestCase):
    """End-to-end tests for data validation and quality."""

    def test_parse_bulletin_no_duplicate_categories(self):
        """Test that parsed data doesn't have duplicate categories."""
        mock_html = """
        <html>
        <body>
            <h1>January 2025 Bulletin</h1>
            <table>
                <tr><th>Category</th><th>Date</th></tr>
                <tr><td>EB-1</td><td>Current</td></tr>
                <tr><td>EB-2</td><td>01JAN25</td></tr>
            </table>
        </body>
        </html>
        """

        result = parse_bulletin_html(mock_html, verbose=False, debug=False)

        # Convert categories to JSON strings for comparison
        category_strings = [json.dumps(cat, sort_keys=True) for cat in result['categories']]
        unique_categories = set(category_strings)

        # Number of unique categories should equal total categories
        self.assertEqual(len(unique_categories), len(result['categories']))

    def test_parse_bulletin_all_categories_have_data(self):
        """Test that all extracted categories have actual data."""
        mock_html = """
        <html>
        <body>
            <h1>February 2025 Bulletin</h1>
            <table>
                <tr><th>Category</th><th>Date</th><th>Country</th></tr>
                <tr><td>F1</td><td>01JAN20</td><td>China</td></tr>
                <tr><td>F2A</td><td>01FEB20</td><td>India</td></tr>
            </table>
        </body>
        </html>
        """

        result = parse_bulletin_html(mock_html, verbose=False, debug=False)

        # All categories should have at least one field with data
        for category in result['categories']:
            self.assertGreater(len(category), 0, "Category should not be empty")
            # At least one value should be non-empty
            has_data = any(str(v).strip() for v in category.values())
            self.assertTrue(has_data, f"Category has no data: {category}")

    def test_parse_bulletin_extracted_at_is_recent(self):
        """Test that extracted_at timestamp is reasonable."""
        from datetime import datetime, timedelta

        mock_html = "<html><body><h1>March 2025</h1></body></html>"
        result = parse_bulletin_html(mock_html, verbose=False, debug=False)

        extracted_at = datetime.fromisoformat(result['extracted_at'])
        now = datetime.now()

        # Should be within the last minute
        time_diff = abs((now - extracted_at).total_seconds())
        self.assertLess(time_diff, 60, "Extraction timestamp should be recent")


if __name__ == '__main__':
    unittest.main()
