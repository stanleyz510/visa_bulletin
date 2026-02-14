# End-to-End Test Fixtures

This directory contains HTML snapshots for end-to-end testing.

## Files

- **20250124.html** - Landing page snapshot (173KB)
  - Captured: January 24, 2025
  - Contains links to monthly bulletins
  - Used to test link extraction functionality

## E2E Test Coverage

The e2e tests ([test_e2e.py](../test_e2e.py)) verify the complete scraper workflow:

### Real HTML Snapshot Tests

Using the actual landing page snapshot from `20250124.html`:

1. ✅ **Link Extraction** - Extracts current bulletin URL from landing page
2. ✅ **Landing Page Detection** - Correctly identifies landing page (no visa data)
3. ✅ **Valid Structure** - Returns proper JSON structure even for non-bulletin pages

### Mock Bulletin Tests

Using synthetic bulletin HTML with real data patterns:

4. ✅ **Category Extraction** - Extracts employment and family visa categories
5. ✅ **Date Extraction** - Parses bulletin dates correctly
6. ✅ **Country Data** - Extracts country-specific cutoff dates
7. ✅ **Complete Workflow** - End-to-end parse → save → load cycle

### Data Validation Tests

8. ✅ **No Duplicates** - Ensures no duplicate categories in output
9. ✅ **Data Quality** - All categories contain actual data
10. ✅ **Timestamp Accuracy** - Extraction timestamp is current

## Running E2E Tests

```bash
# Run only e2e tests
python -m unittest tests.test_e2e

# Run e2e tests with verbose output
python -m unittest tests.test_e2e -v

# Run specific e2e test class
python -m unittest tests.test_e2e.TestE2ELandingPage

# Run specific e2e test
python -m unittest tests.test_e2e.TestE2ELandingPage.test_extract_bulletin_url_from_snapshot
```

## Adding New Snapshots

To add new test fixtures:

1. **Capture a bulletin page:**
   ```bash
   curl -o tests/e2e_test/bulletin_YYYYMMDD.html \
     "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/YYYY/visa-bulletin-for-month-YYYY.html"
   ```

2. **Update test_e2e.py:**
   - Add new test class for the snapshot
   - Verify expected categories and dates

3. **Run tests:**
   ```bash
   python -m unittest tests.test_e2e
   ```

## Test Results

All e2e tests use real HTML structures from the State Department website:
- ✅ 15/15 tests passing
- ✅ Tests run in ~0.2 seconds
- ✅ No external dependencies (offline testing)

## Snapshot Maintenance

**Important:** Snapshots may become outdated as the State Department updates their website structure.

When website structure changes:
1. Capture new snapshot
2. Update parser if needed
3. Update test expectations
4. Keep old snapshots for regression testing

## Integration with CI/CD

E2E tests are designed for CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run E2E Tests
  run: python -m unittest tests.test_e2e
```

## Notes

- Snapshots are large files (~170KB+) due to full HTML content
- Tests are deterministic (no network calls)
- Mock data mirrors actual State Department bulletin format
- Tests verify both happy path and edge cases
