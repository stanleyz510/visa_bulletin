"""Tests for compare.py — bulletin diff logic."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compare import (
    _build_category_index,
    _derive_category_key,
    _diff_category,
    _diff_date_field,
    compare_bulletins,
    format_comparison_for_display,
)


def _bulletin(bulletin_date: str = "January 2026", categories=None) -> dict:
    if categories is None:
        categories = []
    return {
        "bulletin_date": bulletin_date,
        "extracted_at": "2026-01-15T10:00:00",
        "categories": categories,
        "total_categories": len(categories),
    }


def _cat(visa_category: str = "EB-1", **fields) -> dict:
    return {"visa_category": visa_category, **fields}


class TestDeriveCategoryKey(unittest.TestCase):
    def test_uses_visa_category(self):
        cat = {"visa_category": "EB-1", "china": "01 JAN 26"}
        self.assertEqual(_derive_category_key(cat), "EB-1")

    def test_falls_back_to_preference_level(self):
        cat = {"preference_level": "Employment-Based", "china": "01 JAN 26"}
        self.assertEqual(_derive_category_key(cat), "Employment-Based")

    def test_falls_back_to_sorted_items(self):
        cat = {"china": "01 JAN 26", "india": "01 FEB 25"}
        key = _derive_category_key(cat)
        self.assertIsInstance(key, str)
        self.assertTrue(len(key) > 0)


class TestBuildCategoryIndex(unittest.TestCase):
    def test_indexes_by_visa_category(self):
        cats = [
            {"visa_category": "EB-1", "china": "01 JAN 26"},
            {"visa_category": "EB-2", "china": "01 SEP 21"},
        ]
        index = _build_category_index(cats)
        self.assertIn("EB-1", index)
        self.assertIn("EB-2", index)
        self.assertEqual(index["EB-1"]["china"], "01 JAN 26")

    def test_duplicate_keys_last_write_wins(self):
        cats = [
            {"visa_category": "EB-1", "china": "01 JAN 25"},
            {"visa_category": "EB-1", "china": "01 JAN 26"},
        ]
        index = _build_category_index(cats)
        self.assertEqual(index["EB-1"]["china"], "01 JAN 26")

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(_build_category_index([]), {})


class TestDiffDateField(unittest.TestCase):
    def test_equal_values_returns_none(self):
        self.assertIsNone(_diff_date_field("china", "01 JAN 26", "01 JAN 26"))

    def test_both_current_returns_none(self):
        self.assertIsNone(_diff_date_field("china", "C", "Current"))

    def test_advanced_direction(self):
        result = _diff_date_field("china", "01 FEB 26", "01 JAN 26")
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "advanced")
        self.assertEqual(result["previous"], "01 JAN 26")
        self.assertEqual(result["current"], "01 FEB 26")

    def test_retrogressed_direction(self):
        result = _diff_date_field("china", "01 DEC 25", "01 JAN 26")
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "retrogressed")

    def test_became_current(self):
        result = _diff_date_field("china", "C", "01 JAN 26")
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "became_current")

    def test_lost_current(self):
        result = _diff_date_field("china", "01 FEB 26", "Current")
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "lost_current")

    def test_unparseable_date_direction_changed(self):
        result = _diff_date_field("china", "foo", "bar")
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "changed")

    def test_field_name_preserved(self):
        result = _diff_date_field("india", "01 FEB 26", "01 JAN 26")
        self.assertEqual(result["field"], "india")


class TestDiffCategory(unittest.TestCase):
    def test_identical_returns_none(self):
        cat = {"visa_category": "EB-1", "china": "01 JAN 26"}
        self.assertIsNone(_diff_category("EB-1", cat, cat.copy()))

    def test_one_field_changed(self):
        current = {"visa_category": "EB-1", "china": "01 FEB 26"}
        previous = {"visa_category": "EB-1", "china": "01 JAN 26"}
        result = _diff_category("EB-1", current, previous)
        self.assertIsNotNone(result)
        self.assertEqual(result["category_key"], "EB-1")
        self.assertEqual(len(result["field_changes"]), 1)
        self.assertEqual(result["field_changes"][0]["field"], "china")

    def test_multiple_fields_changed(self):
        current = {"visa_category": "EB-2", "china": "01 OCT 21", "india": "01 AUG 13"}
        previous = {"visa_category": "EB-2", "china": "01 SEP 21", "india": "01 JUN 13"}
        result = _diff_category("EB-2", current, previous)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["field_changes"]), 2)

    def test_identity_fields_skipped(self):
        current = {"visa_category": "EB-1", "preference_level": "Employment-Based"}
        previous = {"visa_category": "EB-1", "preference_level": "Employment-Based"}
        result = _diff_category("EB-1", current, previous)
        self.assertIsNone(result)

    def test_new_country_column_detected(self):
        """A country column present in current but not previous = 'added'."""
        current = {"visa_category": "EB-1", "china": "01 JAN 26", "mexico": "C"}
        previous = {"visa_category": "EB-1", "china": "01 JAN 26"}
        result = _diff_category("EB-1", current, previous)
        self.assertIsNotNone(result)
        directions = {fc["field"]: fc["direction"] for fc in result["field_changes"]}
        self.assertEqual(directions["mexico"], "added")

    def test_removed_country_column_detected(self):
        """A country column in previous but not current = 'removed'."""
        current = {"visa_category": "EB-1", "china": "01 JAN 26"}
        previous = {"visa_category": "EB-1", "china": "01 JAN 26", "mexico": "C"}
        result = _diff_category("EB-1", current, previous)
        self.assertIsNotNone(result)
        directions = {fc["field"]: fc["direction"] for fc in result["field_changes"]}
        self.assertEqual(directions["mexico"], "removed")


class TestCompareBulletins(unittest.TestCase):
    def _make_bulletins(self, current_cats, previous_cats, current_date="Feb 2026", prev_date="Jan 2026"):
        current = _bulletin(current_date, current_cats)
        previous = _bulletin(prev_date, previous_cats)
        return current, previous

    def test_identical_bulletins_no_changes(self):
        cats = [_cat("EB-1", china="01 JAN 26"), _cat("EB-2", china="01 SEP 21")]
        current, previous = self._make_bulletins(cats, cats)
        diff = compare_bulletins(current, previous)
        self.assertFalse(diff["has_changes"])
        self.assertEqual(diff["summary"]["categories_changed"], 0)
        self.assertIsNone(diff["error"])

    def test_added_category_detected(self):
        previous_cats = [_cat("EB-1", china="01 JAN 26")]
        current_cats = [_cat("EB-1", china="01 JAN 26"), _cat("EB-5R", china="01 JAN 24")]
        current, previous = self._make_bulletins(current_cats, previous_cats)
        diff = compare_bulletins(current, previous)
        self.assertTrue(diff["has_changes"])
        self.assertEqual(diff["summary"]["categories_added"], 1)
        self.assertEqual(diff["categories_added"][0]["visa_category"], "EB-5R")

    def test_removed_category_detected(self):
        previous_cats = [_cat("EB-1", china="01 JAN 26"), _cat("EB-5R", china="01 JAN 24")]
        current_cats = [_cat("EB-1", china="01 JAN 26")]
        current, previous = self._make_bulletins(current_cats, previous_cats)
        diff = compare_bulletins(current, previous)
        self.assertTrue(diff["has_changes"])
        self.assertEqual(diff["summary"]["categories_removed"], 1)
        self.assertEqual(diff["categories_removed"][0]["visa_category"], "EB-5R")

    def test_changed_date_detected(self):
        previous_cats = [_cat("EB-2", china="01 SEP 21", india="01 JUN 13")]
        current_cats = [_cat("EB-2", china="01 OCT 21", india="01 JUN 13")]
        current, previous = self._make_bulletins(current_cats, previous_cats)
        diff = compare_bulletins(current, previous)
        self.assertTrue(diff["has_changes"])
        self.assertEqual(diff["summary"]["categories_changed"], 1)
        self.assertEqual(diff["summary"]["total_field_changes"], 1)
        field_change = diff["categories_changed"][0]["field_changes"][0]
        self.assertEqual(field_change["field"], "china")
        self.assertEqual(field_change["direction"], "advanced")

    def test_bulletin_dates_captured(self):
        cats = [_cat("EB-1", china="01 JAN 26")]
        current, previous = self._make_bulletins(cats, cats, "Feb 2026", "Jan 2026")
        diff = compare_bulletins(current, previous)
        self.assertEqual(diff["current_run_bulletin_date"], "Feb 2026")
        self.assertEqual(diff["previous_run_bulletin_date"], "Jan 2026")

    def test_empty_categories_both_sides(self):
        current = _bulletin("Feb 2026", [])
        previous = _bulletin("Jan 2026", [])
        diff = compare_bulletins(current, previous)
        self.assertFalse(diff["has_changes"])
        self.assertIsNone(diff["error"])

    def test_summary_counts_correct(self):
        previous_cats = [
            _cat("EB-1", china="01 JAN 26"),
            _cat("EB-2", china="01 SEP 21"),
            _cat("EB-3", china="01 JAN 22"),
        ]
        current_cats = [
            _cat("EB-1", china="01 FEB 26"),   # changed
            _cat("EB-2", china="01 SEP 21"),   # unchanged
            _cat("EB-4", china="C"),            # added
            # EB-3 removed
        ]
        current, previous = self._make_bulletins(current_cats, previous_cats)
        diff = compare_bulletins(current, previous)
        self.assertEqual(diff["summary"]["categories_added"], 1)
        self.assertEqual(diff["summary"]["categories_removed"], 1)
        self.assertEqual(diff["summary"]["categories_changed"], 1)

    def test_error_field_none_on_success(self):
        cats = [_cat("EB-1", china="01 JAN 26")]
        current, previous = self._make_bulletins(cats, cats)
        diff = compare_bulletins(current, previous)
        self.assertIsNone(diff["error"])

    def test_error_captured_on_bad_input(self):
        # Passing non-dicts should not raise; error should be captured
        diff = compare_bulletins("not a dict", "also not a dict")
        self.assertIsNotNone(diff["error"])
        self.assertFalse(diff["has_changes"])


class TestFormatComparisonForDisplay(unittest.TestCase):
    def _no_change_diff(self):
        return {
            "compared_at": "2026-01-15T10:05:00",
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

    def _change_diff(self):
        diff = self._no_change_diff()
        diff["has_changes"] = True
        diff["summary"]["categories_changed"] = 1
        diff["summary"]["total_field_changes"] = 1
        diff["categories_changed"] = [
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
        ]
        return diff

    def test_no_changes_message(self):
        output = format_comparison_for_display(self._no_change_diff())
        self.assertIn("No changes detected", output)

    def test_header_contains_bulletin_dates(self):
        output = format_comparison_for_display(self._no_change_diff())
        self.assertIn("February 2026", output)
        self.assertIn("January 2026", output)

    def test_change_shows_category(self):
        output = format_comparison_for_display(self._change_diff())
        self.assertIn("EB-2", output)

    def test_change_shows_direction(self):
        output = format_comparison_for_display(self._change_diff())
        self.assertIn("ADVANCED", output)

    def test_error_shown_in_output(self):
        diff = self._no_change_diff()
        diff["error"] = "Something went wrong"
        output = format_comparison_for_display(diff)
        self.assertIn("Something went wrong", output)


if __name__ == "__main__":
    unittest.main()
