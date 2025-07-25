import json
import csv
import sys
from typing import List, Dict, Any


def flatten_footnotes(footnotes: List[Dict]) -> str:
    """Convert footnotes list to a readable string format."""
    if not footnotes:
        return ""

    footnote_strings = []
    for footnote in footnotes:
        columns = ", ".join(footnote.get("columns", []))
        value = footnote.get("value", "")
        note_type = footnote.get("type", "")
        footnote_strings.append(f"[{note_type}] {value} (cols: {columns})")

    return " | ".join(footnote_strings)


def flatten_units(units: List[str]) -> str:
    """Convert units list to comma-separated string."""
    if not units:
        return ""
    return ", ".join(units)


def convert_hts_json_to_csv(
    json_data: List[Dict[str, Any]], output_file: str = "hts_data.csv"
):
    """
    Convert HTS JSON data to CSV format.

    Args:
        json_data: List of HTS tariff dictionaries
        output_file: Output CSV filename
    """

    # Define the CSV headers based on the JSON structure
    headers = [
        "htsno",
        "indent",
        "description",
        "superior",
        "units",
        "general",
        "special",
        "other",
        "footnotes",
        "quotaQuantity",
        "additionalDuties",
        "addiitionalDuties",  # Note: keeping the typo as it exists in source
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)

        # Write headers
        writer.writerow(headers)

        # Process each row
        for item in json_data:
            row = []
            for header in headers:
                value = item.get(header, "")

                # Handle special formatting for certain fields
                if header == "footnotes" and isinstance(value, list):
                    value = flatten_footnotes(value)
                elif header == "units" and isinstance(value, list):
                    value = flatten_units(value)
                elif value is None:
                    value = ""

                row.append(str(value))

            writer.writerow(row)

    print(f"CSV file '{output_file}' has been created successfully!")
    print(f"Processed {len(json_data)} records.")


def load_json_from_file(file_path: str) -> List[Dict[str, Any]]:
    """Load JSON data from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format in '{file_path}': {e}")
        sys.exit(1)


def main():
    """Main function to run the converter."""

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "hts_output.csv"

    print(f"Loading JSON data from: {input_file}")
    json_data = load_json_from_file(input_file)
    convert_hts_json_to_csv(json_data, output_file)


if __name__ == "__main__":
    main()
