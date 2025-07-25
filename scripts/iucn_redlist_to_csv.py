"""
IUCN Red List JSON to CSV Converter

This script is specifically designed to convert IUCN Red List assessment data from JSON to CSV format.
It handles the specific structure of the IUCN assessment records.

Usage:
    python iucn_redlist_to_csv.py input.json output.csv
"""

import json
import csv
import sys
import argparse
from typing import List, Dict, Any


def process_iucn_assessment(assessment: Dict) -> Dict:
    """
    Process a single IUCN assessment record, extracting key information.

    Args:
        assessment: A dictionary containing a single IUCN assessment record

    Returns:
        A dictionary with selected fields
    """
    processed = {
        "taxon_scientific_name": assessment.get("taxon_scientific_name"),
        "year_published": assessment.get("year_published"),
        "latest": assessment.get("latest"),
        "red_list_category_code": assessment.get("red_list_category_code"),
        "possibly_extinct": assessment.get("possibly_extinct"),
        "possibly_extinct_in_the_wild": assessment.get("possibly_extinct_in_the_wild"),
        "sis_taxon_id": assessment.get("sis_taxon_id"),
        "assessment_id": assessment.get("assessment_id"),
        "url": assessment.get("url"),
    }

    # Process scopes
    scopes = assessment.get("scopes", [])
    scope_descriptions = []
    scope_codes = []

    for scope in scopes:
        # Get the English description if available
        description = scope.get("description", {}).get("en")
        if description:
            scope_descriptions.append(description)

        # Get the code
        code = scope.get("code")
        if code:
            scope_codes.append(code)

    processed["scope_descriptions"] = (
        "; ".join(scope_descriptions) if scope_descriptions else None
    )
    processed["scope_codes"] = "; ".join(scope_codes) if scope_codes else None

    return processed


def convert_iucn_json_to_csv(input_file: str, output_file: str) -> None:
    """
    Convert IUCN Red List JSON data to CSV.

    Args:
        input_file: Path to the IUCN JSON file
        output_file: Path to the output CSV file
    """
    try:
        # Load the JSON data
        with open(input_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        # Check if this is the expected format with assessments
        if "assessments" not in data:
            print(
                "Error: This doesn't appear to be IUCN Red List data. No 'assessments' field found."
            )
            return

        # Process each assessment record
        assessments = data["assessments"]
        processed_records = [
            process_iucn_assessment(assessment) for assessment in assessments
        ]

        if not processed_records:
            print("No assessment records found in the data.")
            return

        # Define the fields to include in the CSV
        fieldnames = [
            "taxon_scientific_name",
            "red_list_category_code",
            "year_published",
            "latest",
            "possibly_extinct",
            "possibly_extinct_in_the_wild",
            "sis_taxon_id",
            "assessment_id",
            "url",
            "scope_descriptions",
            "scope_codes",
        ]

        # Write to CSV
        with open("data/" + output_file, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(processed_records)

        print(f"Successfully converted {input_file} to {output_file}")
        print(f"Total records: {len(processed_records)}")

    except FileNotFoundError:
        print(f"Error: The file '{input_file}' was not found.")
    except json.JSONDecodeError:
        print(f"Error: The file '{input_file}' is not valid JSON.")
    except Exception as e:
        print(f"Error converting JSON to CSV: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert IUCN Red List JSON data to CSV"
    )
    parser.add_argument("input", help="Input IUCN Red List JSON file")
    parser.add_argument("output", help="Output CSV file")

    args = parser.parse_args()

    convert_iucn_json_to_csv(args.input, args.output)


if __name__ == "__main__":
    main()
