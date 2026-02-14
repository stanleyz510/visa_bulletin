"""
Parser module for extracting visa bulletin data from HTML content.
Handles HTML parsing and data extraction from visa category tables and div-based structures.
"""

from bs4 import BeautifulSoup
from typing import Dict, List, Any, Optional
from datetime import datetime
import re


def parse_bulletin_html(html_content: str, verbose: bool = False, debug: bool = False) -> Optional[Dict[str, Any]]:
    """
    Parse visa bulletin HTML content and extract visa category data.
    Tries multiple parsing strategies to handle different HTML structures.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        if verbose:
            print("[PARSER] Starting HTML parsing...")
        
        # Try to extract bulletin date (preferring January/current)
        bulletin_date = extract_bulletin_date(soup, verbose)
        
        categories = []
        
        # Strategy 1: Look for <table> elements (traditional structure)
        tables = soup.find_all('table')
        if verbose:
            print(f"[PARSER] Found {len(tables)} <table> elements")
        
        for idx, table in enumerate(tables):
            table_data = parse_visa_table(table, verbose)
            if table_data:
                categories.extend(table_data)
        
        # Strategy 2: If no tables found, look for div-based structures
        if not categories and len(tables) == 0:
            if verbose:
                print("[PARSER] No tables found, trying div-based structure...")
            categories = parse_div_based_data(soup, verbose)
        
        # Strategy 3: Look for any structured text data
        if not categories:
            if verbose:
                print("[PARSER] No structured tables/divs found, trying text extraction...")
            categories = parse_text_based_data(soup, verbose)
        
        if verbose:
            print(f"[PARSER] Total extracted {len(categories)} visa categories")
        
        if debug and not categories:
            print("[DEBUG] No categories extracted. Saving HTML sample for analysis...")
            save_debug_html(html_content)
        
        result = {
            "bulletin_date": bulletin_date,
            "extracted_at": datetime.now().isoformat(),
            "categories": categories,
            "total_categories": len(categories)
        }
        
        return result
    
    except Exception as e:
        print(f"[ERROR] Failed to parse HTML content: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def extract_bulletin_date(soup: BeautifulSoup, verbose: bool = False) -> str:
    """
    Extract the bulletin date, preferring the current (January) bulletin.
    """
    try:
        text_content = soup.get_text()
        
        # Strategy 1: Look for "Current" marker followed by month-year
        current_match = re.search(
            r'current\s+bulletin.*?(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
            text_content,
            re.IGNORECASE | re.DOTALL
        )
        if current_match:
            date_str = f"{current_match.group(1)} {current_match.group(2)}"
            if verbose:
                print(f"[PARSER] Found current bulletin marker: {date_str}")
            return date_str
        
        # Strategy 2: Look for January specifically (likely the current)
        january_match = re.search(r'January\s+(\d{4})', text_content, re.IGNORECASE)
        if january_match:
            date_str = f"January {january_match.group(1)}"
            if verbose:
                print(f"[PARSER] Found January bulletin: {date_str}")
            return date_str
        
        # Strategy 3: Use the first month-year found (fallback)
        date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})'
        match = re.search(date_pattern, text_content, re.IGNORECASE)
        
        if match:
            date_str = f"{match.group(1)} {match.group(2)}"
            if verbose:
                print(f"[PARSER] Extracted bulletin date: {date_str}")
            return date_str
        
        current_date = datetime.now().strftime("%B %Y")
        if verbose:
            print(f"[PARSER] Bulletin date not found, using current: {current_date}")
        return current_date
    
    except Exception as e:
        print(f"[ERROR] Failed to extract bulletin date: {str(e)}")
        return datetime.now().strftime("%B %Y")


def parse_visa_table(table, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Parse a single visa table and extract category data.
    """
    try:
        rows = table.find_all('tr')
        if len(rows) < 2:
            return []
        
        header_cells = rows[0].find_all(['th', 'td'])
        headers = [cell.get_text(strip=True) for cell in header_cells]
        
        if verbose:
            print(f"[PARSER] Table headers: {headers[:3]}...")
        
        categories = []
        
        for row_idx in range(1, len(rows)):
            cells = rows[row_idx].find_all(['td', 'th'])
            if not cells:
                continue
            
            cell_values = [cell.get_text(strip=True) for cell in cells]
            
            category = {}
            for header_idx, header in enumerate(headers):
                if header_idx < len(cell_values):
                    category[normalize_header(header)] = cell_values[header_idx]
            
            if category:
                categories.append(category)
        
        if verbose and categories:
            print(f"[PARSER] Extracted {len(categories)} rows from table")
        
        return categories
    
    except Exception as e:
        print(f"[ERROR] Failed to parse table: {str(e)}")
        return []


def parse_div_based_data(soup: BeautifulSoup, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Parse visa data from div-based HTML structures (non-table layout).
    Looks for divs and other elements containing visa category information.
    """
    try:
        categories = []
        
        # Pattern to match visa categories
        visa_pattern = r'(EB-\d|F-?\d+[A-Z]?|DV|IR-|K-|V-|T-|U-|VAWA)'
        
        # Look for divs and other elements that might contain visa data
        potential_elements = soup.find_all(['div', 'p', 'li', 'span', 'td', 'dd'])
        
        for elem in potential_elements:
            text = elem.get_text(strip=True)
            # Check if this element contains visa category info
            if re.search(visa_pattern, text) and len(text) > 10:
                row_data = extract_row_from_element(elem, verbose)
                if row_data:
                    categories.append(row_data)
        
        # Deduplicate categories
        unique_categories = []
        seen = set()
        for cat in categories:
            cat_str = str(sorted(cat.items()))
            if cat_str not in seen:
                seen.add(cat_str)
                unique_categories.append(cat)
        
        if verbose and unique_categories:
            print(f"[PARSER] Extracted {len(unique_categories)} categories from div structure")
        
        return unique_categories
    
    except Exception as e:
        print(f"[ERROR] Failed to parse div-based data: {str(e)}")
        return []


def extract_row_from_element(elem, verbose: bool = False) -> Optional[Dict[str, Any]]:
    """
    Try to extract visa row data from any HTML element.
    """
    try:
        text = elem.get_text(strip=True)
        
        # Look for visa category pattern
        category_match = re.search(r'(EB-\d|F-?\d+[A-Z]?|DV|IR-|K-|V-|T-|U-|VAWA)', text)
        if not category_match:
            return None
        
        category_code = category_match.group(1)
        
        # Try to extract dates (look for date patterns)
        # Typical format: "DD MMM YY" or "Current"
        date_pattern = r'(\d{1,2}\s+[A-Z]{3}\s+\d{2}|Current)'
        dates = re.findall(date_pattern, text)
        
        row = {'visa_category': category_code}
        
        # Also try to find dates in the element's text nodes
        if not dates:
            # Look for parent's text content
            parent = elem.parent
            if parent:
                parent_text = parent.get_text(strip=True)
                dates = re.findall(date_pattern, parent_text)
        
        if len(dates) > 0:
            row['cutoff_date'] = dates[0]
        if len(dates) > 1:
            row['final_action_date'] = dates[1]
        
        return row if len(row) > 1 else None
    
    except Exception as e:
        return None


def parse_text_based_data(soup: BeautifulSoup, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Last resort: try to extract visa data from plain text.
    """
    try:
        text = soup.get_text()
        categories = []
        
        # Look for lines with visa categories
        lines = text.split('\n')
        for line in lines:
            if re.search(r'EB-\d|F-\d|DV', line) and len(line) > 5:
                # Try to parse this line
                row_data = extract_row_from_text(line)
                if row_data:
                    categories.append(row_data)
        
        if verbose and categories:
            print(f"[PARSER] Extracted {len(categories)} categories from text")
        
        return categories
    
    except Exception as e:
        print(f"[ERROR] Failed to parse text-based data: {str(e)}")
        return []


def extract_row_from_text(line: str) -> Optional[Dict[str, Any]]:
    """
    Extract visa category data from a text line.
    """
    try:
        # Look for visa category pattern
        category_match = re.search(r'(EB-\d|F-?\d+[A-Z]?|DV|IR-|K-|V-|T-|U-|VAWA)', line)
        if not category_match:
            return None
        
        category_code = category_match.group(1)
        
        # Look for dates
        date_pattern = r'(\d{1,2}\s+[A-Z]{3}\s+\d{2}|Current)'
        dates = re.findall(date_pattern, line)
        
        row = {'visa_category': category_code}
        
        if len(dates) > 0:
            row['cutoff_date'] = dates[0]
        if len(dates) > 1:
            row['final_action_date'] = dates[1]
        
        return row if len(row) > 1 else None
    
    except Exception as e:
        return None


def normalize_header(header: str) -> str:
    """
    Normalize table header names to standard keys.
    """
    header_lower = header.lower().strip()

    # Order matters - check more specific patterns first
    mappings = [
        ('visa category', 'visa_category'),
        ('preference level', 'preference_level'),
        ('family preference', 'family_preference'),
        ('employment preference', 'employment_preference'),
        ('final action date', 'final_action_date'),
        ('cutoff date', 'cutoff_date'),
        ('action date', 'action_date'),
        ('processing date', 'processing_date'),
        ('category', 'category'),
        ('current', 'current'),
    ]

    for key, value in mappings:
        if key in header_lower:
            return value

    # Normalize spaces: replace multiple spaces with single underscore
    import re
    return re.sub(r'\s+', '_', header_lower)


def extract_visa_type(category: Dict[str, Any]) -> str:
    """
    Determine visa type (Employment, Family, Diversity) from category data.
    """
    category_str = str(category).lower()

    # Check in order of specificity
    if any(term in category_str for term in ['eb-', 'employment']):
        return "Employment-Based"
    elif any(term in category_str for term in ['dv', 'diversity']):
        return "Diversity Visa"
    elif any(term in category_str for term in ['family', 'f1', 'f2', 'f3', 'f4', 'f-']):
        return "Family-Based"
    else:
        return "Unknown"


def save_debug_html(html_content: str, filename: str = "debug_page.html"):
    """
    Save HTML content for manual inspection and debugging.
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[DEBUG] HTML saved to {filename} for inspection")
    except Exception as e:
        print(f"[DEBUG] Failed to save HTML: {e}")
