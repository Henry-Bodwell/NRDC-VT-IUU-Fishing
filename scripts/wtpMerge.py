import pandas as pd
import os
from pathlib import Path
import glob
from collections import defaultdict


def merge_and_deduplicate_csvs_by_type(base_path="data/WildlifeTradePortal"):
    """
    Merge and deduplicate CSV files by file type across multiple folders.
    Groups files by their base name (incident-data, incident-summary-and-locations, etc.)
    Deduplicates BEFORE adding source tracking to catch true duplicates across folders.

    Args:
        base_path (str): Base path to the Wildlife Trade Portal data directory
    """

    # Convert to Path object for easier manipulation
    base_dir = Path(base_path)

    if not base_dir.exists():
        print(f"Error: Directory {base_dir} does not exist!")
        return

    # Find all subdirectories
    subdirs = [d for d in base_dir.iterdir() if d.is_dir()]

    if not subdirs:
        print(f"No subdirectories found in {base_dir}")
        return

    print(f"Found {len(subdirs)} subdirectories to process:")
    for subdir in subdirs:
        print(f"  - {subdir.name}")

    # Dictionary to group files by their base type
    file_groups = defaultdict(list)

    # Process each subdirectory to categorize files
    for subdir in subdirs:
        print(f"\nScanning directory: {subdir.name}")

        # Find all CSV files in the subdirectory
        csv_files = list(subdir.glob("*.csv"))

        if not csv_files:
            print(f"  No CSV files found in {subdir.name}")
            continue

        print(f"  Found {len(csv_files)} CSV files:")

        # Categorize each CSV file by its base name
        for csv_file in csv_files:
            file_name = csv_file.stem  # filename without extension

            # Determine the base type
            if file_name.startswith("incident-data-"):
                base_type = "incident-data"
            elif file_name.startswith("incident-summary-and-locations-"):
                base_type = "incident-summary-and-locations"
            elif file_name.startswith("incident-summary-and-species-"):
                base_type = "incident-summary-and-species"
            else:
                base_type = "other"
                print(f"    Warning: Unrecognized file pattern: {file_name}")

            file_groups[base_type].append(
                {"path": csv_file, "folder": subdir.name, "filename": csv_file.name}
            )

            print(f"    {csv_file.name} -> {base_type}")

    # Create output directory
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # Process each file group
    results = {}

    for base_type, files in file_groups.items():
        if not files:
            continue

        print(f"\n{'='*60}")
        print(f"Processing {base_type} files ({len(files)} files)")
        print(f"{'='*60}")

        # List to store dataframes for this file type (WITHOUT source info initially)
        type_dataframes = []
        source_tracking = []  # Track source info separately
        file_info = []

        # Process each file of this type
        for file_info_dict in files:
            csv_file = file_info_dict["path"]
            folder_name = file_info_dict["folder"]
            filename = file_info_dict["filename"]

            try:
                print(f"  Reading {folder_name}/{filename}...")
                df = pd.read_csv(csv_file)

                # Store original data WITHOUT source columns
                type_dataframes.append(df)

                # Track source info separately for each row
                source_info = pd.DataFrame(
                    {
                        "source_folder": [folder_name] * len(df),
                        "source_file": [filename] * len(df),
                    }
                )
                source_tracking.append(source_info)

                file_info.append(
                    {
                        "folder": folder_name,
                        "file": filename,
                        "rows": len(df),
                        "columns": len(df.columns),
                    }
                )

                print(f"    Loaded {len(df)} rows, {len(df.columns)} columns")

            except Exception as e:
                print(f"    Error reading {filename}: {str(e)}")
                continue

        if not type_dataframes:
            print(f"  No files successfully loaded for {base_type}")
            continue

        # Merge all dataframes of this type (without source info)
        print(f"\n  Merging {len(type_dataframes)} {base_type} dataframes...")
        merged_df = pd.concat(type_dataframes, ignore_index=True)
        merged_sources = pd.concat(source_tracking, ignore_index=True)

        print(
            f"  Merged dataframe has {len(merged_df)} rows and {len(merged_df.columns)} columns"
        )

        # Remove exact duplicates BEFORE adding source info
        print(
            f"  Removing exact duplicates from {base_type} (before adding source tracking)..."
        )

        initial_count = len(merged_df)

        # Find duplicates and keep track of which rows to keep
        duplicated_mask = merged_df.duplicated(keep="first")
        unique_indices = ~duplicated_mask

        # Apply the same mask to both data and source tracking
        deduplicated_df = merged_df[unique_indices].reset_index(drop=True)
        deduplicated_sources = merged_sources[unique_indices].reset_index(drop=True)

        # Now add source information to the deduplicated data
        final_df = pd.concat([deduplicated_df, deduplicated_sources], axis=1)

        final_count = len(final_df)
        duplicates_removed = initial_count - final_count

        print(f"  Removed {duplicates_removed} duplicate rows from {base_type}")
        print(f"  Final {base_type} dataset has {final_count} rows")

        # Save the merged and deduplicated data for this type
        safe_filename = base_type.replace("-", "_")
        output_file = output_dir / f"merged_{safe_filename}.csv"
        final_df.to_csv(output_file, index=False)
        print(f"  Saved to: {output_file}")

        # Store results
        results[base_type] = {
            "dataframe": final_df,
            "file_info": file_info,
            "initial_count": initial_count,
            "final_count": final_count,
            "duplicates_removed": duplicates_removed,
            "output_file": output_file,
        }

        # Display sample of final data
        print(f"  Sample of {base_type} data (first 3 rows):")
        print(f"  {final_df.head(3).to_string()}")

    # Create joined dataset on Report ID
    print(f"\n{'='*60}")
    print(f"Creating joined dataset on Report ID")
    print(f"{'='*60}")

    joined_df = None
    join_info = {}

    if len(results) >= 2:  # Need at least 2 datasets to join
        # Get the datasets
        datasets = {}
        for base_type, result in results.items():
            df = result["dataframe"].copy()
            # Remove source columns for joining (we'll add them back differently)
            data_cols = [
                col for col in df.columns if col not in ["source_folder", "source_file"]
            ]
            datasets[base_type] = df[data_cols]

        # Check if Report ID column exists in datasets
        report_id_cols = []
        for base_type, df in datasets.items():
            # Look for Report ID column (case insensitive)
            possible_cols = [
                col
                for col in df.columns
                if "report" in col.lower() and "id" in col.lower()
            ]
            if possible_cols:
                report_id_cols.append((base_type, possible_cols[0]))
                print(f"  Found Report ID column in {base_type}: '{possible_cols[0]}'")
            else:
                print(f"  Warning: No Report ID column found in {base_type}")
                print(f"    Available columns: {list(df.columns)}")

        if len(report_id_cols) >= 2:
            # Start with the first dataset
            first_type, first_col = report_id_cols[0]
            joined_df = datasets[first_type].copy()
            joined_df = joined_df.rename(
                columns={first_col: "Report_ID"}
            )  # Standardize column name

            join_info[first_type] = {
                "original_rows": len(joined_df),
                "join_column": first_col,
            }

            print(f"  Starting join with {first_type} ({len(joined_df)} rows)")

            # Join with remaining datasets
            for base_type, report_col in report_id_cols[1:]:
                df_to_join = datasets[base_type].copy()
                df_to_join = df_to_join.rename(columns={report_col: "Report_ID"})

                # Add suffix to avoid column name conflicts
                suffix = f"_{base_type.replace('-', '_')}"

                before_join = len(joined_df)
                joined_df = joined_df.merge(
                    df_to_join,
                    on="Report_ID",
                    how="outer",  # Keep all records
                    suffixes=("", suffix),
                )
                after_join = len(joined_df)

                join_info[base_type] = {
                    "original_rows": len(df_to_join),
                    "join_column": report_col,
                    "rows_after_join": after_join,
                }

                print(f"  Joined with {base_type} ({len(df_to_join)} rows)")
                print(
                    f"    Result: {after_join} rows ({after_join - before_join} new rows)"
                )

            # Save joined dataset
            joined_output_file = output_dir / "joined_all_incident_data.csv"
            joined_df.to_csv(joined_output_file, index=False)
            print(f"  Saved joined dataset to: {joined_output_file}")
            print(
                f"  Final joined dataset: {len(joined_df)} rows, {len(joined_df.columns)} columns"
            )

            # Show sample
            print(f"  Sample of joined data (first 3 rows, first 10 columns):")
            sample_cols = joined_df.columns[:10]
            print(f"  {joined_df[sample_cols].head(3).to_string()}")

        else:
            print(
                f"  Cannot create joined dataset: Need Report ID columns in at least 2 datasets"
            )
            print(f"  Found Report ID columns in {len(report_id_cols)} datasets")
    else:
        print(f"  Cannot create joined dataset: Need at least 2 datasets to join")

    # Create comprehensive summary report
    summary_file = output_dir / "merge_summary_by_type.txt"
    with open(summary_file, "w") as f:
        f.write("Wildlife Trade Portal Data Merge Summary (By File Type)\n")
        f.write("=" * 60 + "\n\n")

        for base_type, result in results.items():
            f.write(f"{base_type.upper()}\n")
            f.write("-" * len(base_type) + "\n")
            f.write(f"Source Files:\n")
            for info in result["file_info"]:
                f.write(
                    f"  {info['folder']}/{info['file']}: {info['rows']} rows, {info['columns']} columns\n"
                )

            f.write(f"\nFiles processed: {len(result['file_info'])}\n")
            f.write(f"Initial merged rows: {result['initial_count']}\n")
            f.write(f"Duplicates removed: {result['duplicates_removed']}\n")
            f.write(f"Final rows: {result['final_count']}\n")
            f.write(f"Final columns: {len(result['dataframe'].columns)}\n")
            f.write(f"Output file: {result['output_file'].name}\n")

            if len(result["dataframe"].columns) > 0:
                f.write(f"\nColumn names:\n")
                for i, col in enumerate(result["dataframe"].columns, 1):
                    f.write(f"  {i:2d}. {col}\n")

            f.write("\n" + "=" * 60 + "\n\n")

        # Add join information
        if joined_df is not None:
            f.write("JOINED DATASET\n")
            f.write("-" * 15 + "\n")
            f.write(f"Final joined rows: {len(joined_df)}\n")
            f.write(f"Final joined columns: {len(joined_df.columns)}\n")
            f.write(f"Output file: joined_all_incident_data.csv\n\n")

            f.write("Join details:\n")
            for base_type, info in join_info.items():
                f.write(
                    f"  {base_type}: {info['original_rows']} rows, joined on '{info['join_column']}'\n"
                )

            f.write(f"\nJoined column names:\n")
            for i, col in enumerate(joined_df.columns, 1):
                f.write(f"  {i:2d}. {col}\n")
        else:
            f.write("JOINED DATASET\n")
            f.write("-" * 15 + "\n")
            f.write("Could not create joined dataset - see log for details\n")

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    for base_type, result in results.items():
        print(
            f"{base_type}: {result['final_count']} rows (removed {result['duplicates_removed']} duplicates)"
        )

    if joined_df is not None:
        print(f"joined dataset: {len(joined_df)} rows")

    print(f"\nSaved comprehensive summary to: {summary_file}")
    print(f"All merged files saved to: {output_dir}")

    return results, joined_df


if __name__ == "__main__":
    # Run the merge and deduplication by file type
    results, joined_data = merge_and_deduplicate_csvs_by_type()

    if results:
        print(f"\nProcess completed successfully!")
        print(f"Generated {len(results)} merged datasets:")
        for base_type in results.keys():
            print(f"  - {base_type}")
        if joined_data is not None:
            print(f"  - joined dataset with all data")
        print(
            f"\nAccess individual dataframes using: results['{list(results.keys())[0]}']['dataframe']"
        )
        print(f"Access joined dataframe using: joined_data")
    else:
        print("\nProcess completed with errors - check the messages above")
