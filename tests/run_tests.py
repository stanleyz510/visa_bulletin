#!/usr/bin/env python3
"""
Test runner for all unit tests.

Usage:
    python tests/run_tests.py              # Run all tests
    python tests/run_tests.py -v           # Run with verbose output
    python tests/run_tests.py TestClass    # Run specific test class
"""

import unittest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_all_tests(verbosity=2):
    """Run all unit tests in the tests directory."""
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = Path(__file__).parent
    suite = loader.discover(start_dir, pattern='test_*.py')

    runner = unittest.TextTestRunner(verbosity=verbosity, buffer=True)
    result = runner.run(suite)

    # Return exit code based on results
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    verbosity = 2 if '-v' in sys.argv or '--verbose' in sys.argv else 1
    exit_code = run_all_tests(verbosity)
    sys.exit(exit_code)
