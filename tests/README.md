# Visa Bulletin Scraper - Unit Tests

This directory contains comprehensive unit tests for the visa bulletin scraper.

## Test Structure

```
tests/
├── __init__.py           # Package initialization
├── run_tests.py          # Test runner script
├── test_fetch.py         # Tests for fetch module (URL construction, link extraction)
├── test_parser.py        # Tests for parser module (HTML parsing, data extraction)
├── test_persist.py       # Tests for persist module (JSON save/load)
├── e2e_test/            # End-to-end test fixtures
│   └── 20250124.html    # Sample bulletin HTML
└── README.md            # This file
```

## Running Tests

### Run All Tests

```bash
# From the visa_bulletin directory
python tests/run_tests.py

# Or using unittest directly
python -m unittest discover tests

# With verbose output
python tests/run_tests.py -v
```

### Run Specific Test Module

```bash
# Run only fetch tests
python -m unittest tests.test_fetch

# Run only parser tests
python -m unittest tests.test_parser

# Run only persist tests
python -m unittest tests.test_persist
```

### Run Specific Test Class

```bash
# Run a specific test class
python -m unittest tests.test_fetch.TestConstructBulletinUrl

# Run a specific test method
python -m unittest tests.test_fetch.TestConstructBulletinUrl.test_construct_url_january_2026
```

## Test Coverage

### test_fetch.py

Tests for the `fetch` module:
- **TestConstructBulletinUrl**: Tests URL construction for different months/years
- **TestExtractBulletinUrl**: Tests extraction of bulletin URLs from landing pages
  - Strategy 1: Current Bulletin section
  - Strategy 2: Recent bulletins list
  - Strategy 3: Fallback to date construction
  - Edge cases: malformed HTML, verbose mode, case insensitivity

### test_parser.py

Tests for the `parser` module:
- **TestNormalizeHeader**: Tests header name normalization
- **TestExtractVisaType**: Tests visa type identification (Employment/Family/Diversity)
- **TestExtractBulletinDate**: Tests bulletin date extraction
- **TestParseVisaTable**: Tests HTML table parsing
- **TestParseBulletinHtml**: Tests complete HTML bulletin parsing
- **TestParseDivBasedData**: Tests div-based structure parsing
- **TestParseTextBasedData**: Tests plain text parsing

### test_persist.py

Tests for the `persist` module:
- **TestSaveToJson**: Tests JSON file saving
  - Simple data, nested data, unicode characters
  - Directory creation, file overwriting
- **TestSaveWithTimestamp**: Tests timestamped file creation
- **TestLoadFromJson**: Tests JSON file loading
  - Valid/invalid JSON, missing files, unicode
- **TestFormatDataForDisplay**: Tests data formatting for terminal display

## Test Data

### Fixtures

The `e2e_test/` directory contains sample HTML files for testing:
- `20250124.html` - Real visa bulletin HTML for end-to-end testing

### Mock Data

Tests use inline HTML strings and mock data to avoid external dependencies.

## Requirements

All tests use only Python standard library modules:
- `unittest` - Testing framework
- `unittest.mock` - Mocking for datetime and external calls
- `tempfile` - Temporary directories for file I/O tests

The scraper's dependencies (requests, beautifulsoup4) are imported within test modules.

## Writing New Tests

### Template for New Test Class

```python
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from module_name import function_to_test


class TestNewFeature(unittest.TestCase):
    """Test description."""

    def setUp(self):
        """Set up test fixtures."""
        pass

    def tearDown(self):
        """Clean up after tests."""
        pass

    def test_basic_functionality(self):
        """Test the basic case."""
        result = function_to_test("input")
        self.assertEqual(result, "expected")

    def test_edge_case(self):
        """Test an edge case."""
        result = function_to_test(None)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
```

## Best Practices

1. **Isolation**: Each test should be independent and not rely on other tests
2. **Cleanup**: Use `setUp()` and `tearDown()` to manage test state
3. **Descriptive Names**: Test method names should describe what they test
4. **One Assertion**: Prefer one logical assertion per test method
5. **Mock External Calls**: Use mocks for HTTP requests and file I/O where appropriate
6. **Edge Cases**: Test error conditions, empty inputs, and boundary cases

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: python tests/run_tests.py
```

## Troubleshooting

### Import Errors

If you get import errors, ensure you're running tests from the `visa_bulletin` directory:

```bash
cd /path/to/visa_bulletin
python tests/run_tests.py
```

### ModuleNotFoundError

Make sure all dependencies are installed:

```bash
pip install -r requirements.txt
```

## Future Test Additions

Potential areas for additional testing:
- Integration tests with actual State Department website (with rate limiting)
- Performance tests for large HTML documents
- Regression tests for specific bulletin formats
- End-to-end tests with the full scraper pipeline
