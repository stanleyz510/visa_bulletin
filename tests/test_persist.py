"""
Unit tests for the persist module.
Tests JSON saving, loading, and data formatting.
"""

import unittest
import json
import tempfile
import shutil
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from persist import (
    save_to_json,
    save_with_timestamp,
    load_from_json,
    format_data_for_display
)


class TestSaveToJson(unittest.TestCase):
    """Test the save_to_json function."""

    def setUp(self):
        """Set up a temporary directory for test files."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up the temporary directory."""
        shutil.rmtree(self.test_dir)

    def test_save_simple_data(self):
        """Test saving simple data to JSON."""
        data = {
            "bulletin_date": "January 2026",
            "categories": [{"category": "EB-1", "date": "Current"}],
            "total_categories": 1
        }
        output_path = Path(self.test_dir) / "test.json"

        result = save_to_json(data, str(output_path), verbose=False)

        self.assertTrue(result)
        self.assertTrue(output_path.exists())

        # Verify file contents
        with open(output_path, 'r') as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data, data)

    def test_save_with_nested_data(self):
        """Test saving data with nested structures."""
        data = {
            "bulletin_date": "February 2026",
            "categories": [
                {
                    "category": "F1",
                    "dates": {
                        "china": "01JAN20",
                        "india": "01FEB20"
                    }
                }
            ],
            "total_categories": 1
        }
        output_path = Path(self.test_dir) / "nested.json"

        result = save_to_json(data, str(output_path), verbose=False)

        self.assertTrue(result)
        with open(output_path, 'r') as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data['categories'][0]['dates']['china'], "01JAN20")

    def test_save_creates_parent_directories(self):
        """Test that save_to_json creates parent directories if needed."""
        data = {"test": "data"}
        output_path = Path(self.test_dir) / "subdir" / "nested" / "test.json"

        result = save_to_json(data, str(output_path), verbose=False)

        self.assertTrue(result)
        self.assertTrue(output_path.exists())
        self.assertTrue(output_path.parent.exists())

    def test_save_overwrites_existing_file(self):
        """Test that save_to_json overwrites existing files."""
        output_path = Path(self.test_dir) / "overwrite.json"

        # Save initial data
        data1 = {"version": 1}
        save_to_json(data1, str(output_path), verbose=False)

        # Save new data
        data2 = {"version": 2}
        result = save_to_json(data2, str(output_path), verbose=False)

        self.assertTrue(result)
        with open(output_path, 'r') as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data['version'], 2)

    def test_save_with_unicode_characters(self):
        """Test saving data with unicode characters."""
        data = {
            "bulletin_date": "Enero 2026",  # Spanish
            "note": "中文测试",  # Chinese
            "categories": []
        }
        output_path = Path(self.test_dir) / "unicode.json"

        result = save_to_json(data, str(output_path), verbose=False)

        self.assertTrue(result)
        with open(output_path, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data['bulletin_date'], "Enero 2026")
        self.assertEqual(loaded_data['note'], "中文测试")

    def test_save_with_verbose_mode(self):
        """Test that verbose mode doesn't break functionality."""
        data = {"test": "verbose"}
        output_path = Path(self.test_dir) / "verbose.json"

        result = save_to_json(data, str(output_path), verbose=True)

        self.assertTrue(result)
        self.assertTrue(output_path.exists())


class TestSaveWithTimestamp(unittest.TestCase):
    """Test the save_with_timestamp function."""

    def setUp(self):
        """Set up a temporary directory for test files."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up the temporary directory."""
        shutil.rmtree(self.test_dir)

    def test_save_with_timestamp_creates_file(self):
        """Test that save_with_timestamp creates a timestamped file."""
        data = {
            "bulletin_date": "March 2026",
            "categories": [],
            "total_categories": 0
        }

        saved_path = save_with_timestamp(data, output_dir=self.test_dir, verbose=False)

        self.assertIsNotNone(saved_path)
        self.assertTrue(Path(saved_path).exists())

    def test_save_with_timestamp_filename_format(self):
        """Test that timestamped filename follows correct format."""
        data = {"test": "data"}

        saved_path = save_with_timestamp(data, output_dir=self.test_dir, verbose=False)

        filename = Path(saved_path).name
        # Should match pattern: visa_bulletin_YYYYMMDD_HHMMSS.json
        self.assertTrue(filename.startswith("visa_bulletin_"))
        self.assertTrue(filename.endswith(".json"))

    def test_save_with_timestamp_multiple_saves_different_names(self):
        """Test that multiple saves create files with different names."""
        data = {"test": "data"}

        path1 = save_with_timestamp(data, output_dir=self.test_dir, verbose=False)
        # Small delay to ensure different timestamp
        import time
        time.sleep(1)
        path2 = save_with_timestamp(data, output_dir=self.test_dir, verbose=False)

        self.assertIsNotNone(path1)
        self.assertIsNotNone(path2)
        self.assertNotEqual(path1, path2)


class TestLoadFromJson(unittest.TestCase):
    """Test the load_from_json function."""

    def setUp(self):
        """Set up a temporary directory and test file."""
        self.test_dir = tempfile.mkdtemp()
        self.test_file = Path(self.test_dir) / "test.json"

        # Create a test JSON file
        self.test_data = {
            "bulletin_date": "April 2026",
            "categories": [{"category": "EB-1"}],
            "total_categories": 1
        }
        with open(self.test_file, 'w') as f:
            json.dump(self.test_data, f)

    def tearDown(self):
        """Clean up the temporary directory."""
        shutil.rmtree(self.test_dir)

    def test_load_valid_json(self):
        """Test loading valid JSON file."""
        data = load_from_json(str(self.test_file), verbose=False)

        self.assertIsNotNone(data)
        self.assertEqual(data['bulletin_date'], "April 2026")
        self.assertEqual(data['total_categories'], 1)

    def test_load_nonexistent_file(self):
        """Test loading non-existent file returns None."""
        data = load_from_json(str(Path(self.test_dir) / "nonexistent.json"), verbose=False)

        self.assertIsNone(data)

    def test_load_invalid_json(self):
        """Test loading invalid JSON returns None."""
        invalid_file = Path(self.test_dir) / "invalid.json"
        with open(invalid_file, 'w') as f:
            f.write("{ invalid json content }")

        data = load_from_json(str(invalid_file), verbose=False)

        self.assertIsNone(data)

    def test_load_with_unicode(self):
        """Test loading JSON with unicode characters."""
        unicode_file = Path(self.test_dir) / "unicode.json"
        unicode_data = {
            "bulletin_date": "五月 2026",  # Chinese
            "note": "Tëst"
        }
        with open(unicode_file, 'w', encoding='utf-8') as f:
            json.dump(unicode_data, f, ensure_ascii=False)

        data = load_from_json(str(unicode_file), verbose=False)

        self.assertIsNotNone(data)
        self.assertEqual(data['bulletin_date'], "五月 2026")

    def test_load_with_verbose_mode(self):
        """Test that verbose mode doesn't break functionality."""
        data = load_from_json(str(self.test_file), verbose=True)

        self.assertIsNotNone(data)
        self.assertEqual(data['bulletin_date'], "April 2026")


class TestFormatDataForDisplay(unittest.TestCase):
    """Test the format_data_for_display function."""

    def test_format_simple_data(self):
        """Test formatting simple data for display."""
        data = {
            "bulletin_date": "May 2026",
            "extracted_at": "2026-05-01T12:00:00",
            "total_categories": 2,
            "categories": [
                {"category": "EB-1", "date": "Current"},
                {"category": "EB-2", "date": "01DEC25"}
            ]
        }

        output = format_data_for_display(data, max_categories=10)

        self.assertIsInstance(output, str)
        self.assertIn("May 2026", output)
        self.assertIn("Total Categories: 2", output)
        self.assertIn("EB-1", output)

    def test_format_limits_categories(self):
        """Test that max_categories parameter limits output."""
        categories = [{"category": f"Cat{i}"} for i in range(20)]
        data = {
            "bulletin_date": "June 2026",
            "extracted_at": "2026-06-01T12:00:00",
            "total_categories": 20,
            "categories": categories
        }

        output = format_data_for_display(data, max_categories=5)

        self.assertIn("and 15 more categories", output)

    def test_format_no_categories(self):
        """Test formatting data with no categories."""
        data = {
            "bulletin_date": "July 2026",
            "extracted_at": "2026-07-01T12:00:00",
            "total_categories": 0,
            "categories": []
        }

        output = format_data_for_display(data, max_categories=10)

        self.assertIsInstance(output, str)
        self.assertIn("Total Categories: 0", output)

    def test_format_handles_missing_fields(self):
        """Test formatting handles missing fields gracefully."""
        data = {
            "categories": []
        }

        output = format_data_for_display(data, max_categories=10)

        self.assertIsInstance(output, str)
        self.assertIn("Unknown", output)  # For missing bulletin_date

    def test_format_with_complex_category_data(self):
        """Test formatting with complex category data."""
        data = {
            "bulletin_date": "August 2026",
            "extracted_at": "2026-08-01T12:00:00",
            "total_categories": 1,
            "categories": [
                {
                    "family-sponsored": "F1",
                    "all_chargeability_areas": "01JAN20",
                    "china": "01FEB20",
                    "india": "01MAR20"
                }
            ]
        }

        output = format_data_for_display(data, max_categories=10)

        self.assertIn("F1", output)
        self.assertIn("01JAN20", output)


if __name__ == '__main__':
    unittest.main()
