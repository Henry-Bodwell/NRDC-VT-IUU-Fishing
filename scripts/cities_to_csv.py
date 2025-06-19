"""
Species+ JSON to CSV Converter

This script is specifically designed to convert Species+ API JSON data to CSV format.
It handles the nested structure of the taxon_concepts array and flattens the records.

Usage:
    python speciesplus_json_to_csv.py chordataCITES.json out.csv
"""

import json
import csv
import sys
import argparse
from typing import List, Dict, Any


def process_taxon_record(taxon: Dict) -> Dict:
    """
    Process a single taxon record, extracting and flattening key information.
    
    Args:
        taxon: A dictionary containing a single taxon record
        
    Returns:
        A flattened dictionary with selected fields
    """
    flat_record = {
        'id': taxon.get('id'),
        'full_name': taxon.get('full_name'),
        'author_year': taxon.get('author_year'),
        'rank': taxon.get('rank'),
        'name_status': taxon.get('name_status'),
        'active': taxon.get('active'),
        'cites_listing': taxon.get('cites_listing'),
        'updated_at': taxon.get('updated_at')
    }
    
    # Add higher taxa information
    higher_taxa = taxon.get('higher_taxa', {})
    flat_record['kingdom'] = higher_taxa.get('kingdom')
    flat_record['phylum'] = higher_taxa.get('phylum')
    flat_record['class'] = higher_taxa.get('class')
    flat_record['order'] = higher_taxa.get('order')
    flat_record['family'] = higher_taxa.get('family')
    
    # Process common names - extract first English name if available
    common_names = taxon.get('common_names', [])
    en_names = [cn['name'] for cn in common_names if cn.get('language') == 'EN']
    flat_record['common_name_en'] = en_names[0] if en_names else None
    
    # Get all common names as a semicolon-separated string
    all_common_names = [f"{cn['name']} ({cn['language']})" for cn in common_names]
    flat_record['all_common_names'] = "; ".join(all_common_names) if all_common_names else None
    
    return flat_record


def convert_speciesplus_json_to_csv(input_file: str, output_file: str) -> None:
    """
    Convert Species+ JSON data to CSV.
    
    Args:
        input_file: Path to the Species+ JSON file
        output_file: Path to the output CSV file
    """
    try:
        # Load the JSON data
        with open(input_file, 'r', encoding='utf-8') as file:
            data = json.load(file)
        
        # Check if this is the expected format with taxon_concepts
        if 'taxon_concepts' not in data:
            print("Error: This doesn't appear to be Species+ API data. No 'taxon_concepts' field found.")
            return
        
        # Process each taxon record
        taxon_concepts = data['taxon_concepts']
        if isinstance(taxon_concepts, str):
            # Sometimes the taxon_concepts might be a JSON string, so we need to parse it
            try:
                taxon_concepts = json.loads(taxon_concepts)
            except json.JSONDecodeError:
                print("Error: Could not parse the taxon_concepts field as JSON.")
                return
        
        # Process each taxon record
        processed_records = [process_taxon_record(taxon) for taxon in taxon_concepts]
        
        if not processed_records:
            print("No taxon records found in the data.")
            return
        
        # Define the fields to include in the CSV
        fieldnames = [
            'id', 'full_name', 'author_year', 'rank', 'name_status', 'active',
            'cites_listing', 'kingdom', 'phylum', 'class', 'order', 'family',
            'common_name_en', 'all_common_names', 'updated_at'
        ]
        
        # Write to CSV
        with open("data/"+output_file, 'w', newline='', encoding='utf-8') as csvfile:
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
    parser = argparse.ArgumentParser(description='Convert Species+ JSON data to CSV')
    parser.add_argument('input', help='Input Species+ JSON file')
    parser.add_argument('output', help='Output CSV file')
    
    args = parser.parse_args()
    
    convert_speciesplus_json_to_csv(args.input, args.output)


if __name__ == "__main__":
    main()