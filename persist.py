"""
Persistence module for saving visa bulletin data to JSON files.
Handles JSON export functionality and file operations with error handling.
"""

import json
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime


def save_to_json(
    data: Dict[str, Any],
    output_path: str = "visa_bulletin_data.json",
    verbose: bool = False
) -> bool:
    """
    Save extracted visa bulletin data to a JSON file.
    
    Args:
        data: Dictionary containing the visa bulletin data
        output_path: Path where the JSON file will be saved
        verbose: Enable verbose logging
        
    Returns:
        True if successful, False otherwise
    """
    try:
        output_file = Path(output_path)
        
        # Create parent directories if they don't exist
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        if verbose:
            print(f"[PERSIST] Saving data to {output_path}...")
        
        # Write JSON with pretty formatting
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        file_size = output_file.stat().st_size
        if verbose:
            print(f"[PERSIST] Successfully saved {len(data.get('categories', []))} categories")
            print(f"[PERSIST] File size: {file_size:,} bytes")
        
        return True
    
    except IOError as e:
        print(f"[ERROR] Failed to write to {output_path}: {str(e)}")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error while saving JSON: {str(e)}")
        return False


def save_with_timestamp(
    data: Dict[str, Any],
    output_dir: str = "data",
    verbose: bool = False
) -> Optional[str]:
    """
    Save visa bulletin data with a timestamp in the filename.
    Useful for maintaining historical records.
    
    Args:
        data: Dictionary containing the visa bulletin data
        output_dir: Directory where timestamped files will be saved
        verbose: Enable verbose logging
        
    Returns:
        Path to the saved file, or None if failed
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"visa_bulletin_{timestamp}.json"
        output_path = str(Path(output_dir) / filename)
        
        if save_to_json(data, output_path, verbose):
            if verbose:
                print(f"[PERSIST] Timestamped file saved: {filename}")
            return output_path
        return None
    
    except Exception as e:
        print(f"[ERROR] Failed to save timestamped file: {str(e)}")
        return None


def load_from_json(input_path: str, verbose: bool = False) -> Optional[Dict[str, Any]]:
    """
    Load previously saved visa bulletin data from a JSON file.
    
    Args:
        input_path: Path to the JSON file to load
        verbose: Enable verbose logging
        
    Returns:
        Dictionary containing the data, or None if failed
    """
    try:
        input_file = Path(input_path)
        
        if not input_file.exists():
            print(f"[ERROR] File not found: {input_path}")
            return None
        
        if verbose:
            print(f"[PERSIST] Loading data from {input_path}...")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if verbose:
            print(f"[PERSIST] Successfully loaded {len(data.get('categories', []))} categories")
        
        return data
    
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in {input_path}: {str(e)}")
        return None
    except IOError as e:
        print(f"[ERROR] Failed to read {input_path}: {str(e)}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error while loading JSON: {str(e)}")
        return None


def format_data_for_display(data: Dict[str, Any], max_categories: int = 10) -> str:
    """
    Format visa bulletin data as a readable string for display.
    
    Args:
        data: Dictionary containing the visa bulletin data
        max_categories: Maximum number of categories to display
        
    Returns:
        Formatted string representation
    """
    try:
        lines = []
        lines.append(f"Visa Bulletin Data")
        lines.append(f"==================")
        lines.append(f"Bulletin Date: {data.get('bulletin_date', 'Unknown')}")
        lines.append(f"Extracted At: {data.get('extracted_at', 'Unknown')}")
        lines.append(f"Total Categories: {data.get('total_categories', 0)}")
        lines.append("")
        lines.append("Categories:")
        lines.append("-" * 50)
        
        categories = data.get('categories', [])
        display_count = min(max_categories, len(categories))
        
        for i, category in enumerate(categories[:display_count]):
            lines.append(f"\n{i+1}. Category Data:")
            for key, value in category.items():
                lines.append(f"   {key}: {value}")
        
        if len(categories) > max_categories:
            lines.append(f"\n... and {len(categories) - max_categories} more categories")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"Error formatting data: {str(e)}"
