# US Visa Bulletin Web Scraper

A Python script to fetch, parse, and extract data from the US State Department Visa Bulletin website.

## Overview

This tool automatically:
- Fetches the official US Visa Bulletin webpage
- Parses HTML content to extract visa category data
- Extracts key information including visa categories, cutoff dates, and final action dates
- Saves structured data to JSON format for easy access and analysis

The scraper is organized into modular components for maintainability and reusability:
- **fetch.py** - Main script with HTTP request handling and CLI interface
- **parser.py** - HTML parsing and data extraction library
- **persist.py** - JSON file handling and data persistence library

## Installation

### Prerequisites
- Python 3.7 or higher
- pip (Python package manager)

### Setup

1. Clone or download the repository
2. Install required dependencies:

```bash
pip install requests beautifulsoup4
```

Or install from requirements file:
```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Run the scraper with default settings:
```bash
python fetch.py
```

This will:
- Fetch the latest visa bulletin
- Extract all visa category data
- Save results to `visa_bulletin_data.json`

### Command-Line Options

```
-o, --output FILE          Specify output JSON file path (default: visa_bulletin_data.json)
-t, --timestamp            Add timestamp to output filename for historical records
-v, --verbose              Enable verbose logging for debugging
--display                  Display extracted data summary after saving
-h, --help                 Show help message
```

### Examples

**Save with custom filename:**
```bash
python fetch.py -o my_bulletin.json
```

**Run with verbose output:**
```bash
python fetch.py -v
```

**Save with timestamp (e.g., visa_bulletin_20260124_143022.json):**
```bash
python fetch.py -t
```

**Display results after extraction:**
```bash
python fetch.py --display
```

**Combine multiple options:**
```bash
python fetch.py -v -t --display
```

## Output Format

The script generates a JSON file with the following structure:

```json
{
  "bulletin_date": "January 2026",
  "extracted_at": "2026-01-24T14:30:22.123456",
  "total_categories": 15,
  "categories": [
    {
      "preference_level": "EB-1",
      "cutoff_date": "01 JAN 26",
      "final_action_date": "Current",
      ...
    },
    {
      "preference_level": "EB-2",
      "cutoff_date": "15 DEC 25",
      "final_action_date": "15 DEC 25",
      ...
    }
  ]
}
```

## Module Documentation

### fetch.py
Main entry point with command-line interface.
- `fetch_bulletin_page()` - Downloads the visa bulletin webpage
- `scrape_visa_bulletin()` - Orchestrates the complete scraping workflow
- `main()` - CLI entry point

### parser.py
HTML parsing and data extraction library.
- `parse_bulletin_html()` - Main parsing function
- `parse_visa_table()` - Extracts data from individual tables
- `extract_bulletin_date()` - Finds bulletin date in page content
- `normalize_header()` - Standardizes table header names
- `extract_visa_type()` - Determines visa category type

### persist.py
File I/O and data persistence library.
- `save_to_json()` - Saves data to JSON file
- `save_with_timestamp()` - Saves with timestamped filename
- `load_from_json()` - Loads previously saved data
- `format_data_for_display()` - Formats data for terminal display

## Error Handling

The scraper includes comprehensive error handling for:
- Network connectivity issues
- HTTP errors
- Invalid HTML content
- File I/O errors
- JSON encoding/decoding errors

Enable verbose mode (`-v`) to see detailed error messages and debugging information.

## Data Structure

Each visa category entry contains:
- **preference_level** - Visa category (e.g., EB-1, F2A)
- **cutoff_date** - Priority date cutoff for visa availability
- **final_action_date** - Date through which cases are processed
- Additional fields based on the bulletin's table structure

Dates are typically formatted as "DD MON YY" (e.g., "01 JAN 26").
"Current" indicates visa numbers are currently available.

## Troubleshooting

### Connection errors
- Check your internet connection
- The target website may be temporarily unavailable
- Try again after a few minutes

### Parsing errors
- The website structure may have changed
- Check the verbose output for details on what was extracted
- Report issues with specific error messages

### File permission errors
- Ensure you have write permissions in the output directory
- Try specifying a different output location with `-o`

## Dependencies

- **requests** - HTTP library for fetching web pages
- **beautifulsoup4** - HTML parsing library

## License

This project is for informational and educational purposes.

## Notes

- The scraper respects the website's terms of service
- It uses a standard user agent and reasonable request timeouts
- Consider the frequency of requests to avoid overloading the server
- The extracted data is current as of the extraction time (see `extracted_at` field)
