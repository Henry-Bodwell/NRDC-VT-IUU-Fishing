#!/bin/bash

# Multi-query Google Scholar fetcher
# This script runs multiple queries and deduplicates via SQLite
#
# Usage: ./fetch_multiple_queries.sh [options]
#   --year-low YYYY    Minimum publication year
#   --year-high YYYY   Maximum publication year
#   --db-path PATH     Database path (default: data/scholar.db)
#   --dry-run          Show queries without executing

set -e  # Exit on error

# Default settings
YEAR_LOW=""
YEAR_HIGH=""
DB_PATH="data/scholar.db"
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --year-low)
            YEAR_LOW="$2"
            shift 2
            ;;
        --year-high)
            YEAR_HIGH="$2"
            shift 2
            ;;
        --db-path)
            DB_PATH="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build common arguments
COMMON_ARGS="--db-path $DB_PATH"
if [ -n "$YEAR_LOW" ]; then
    COMMON_ARGS="$COMMON_ARGS --year-low $YEAR_LOW"
fi
if [ -n "$YEAR_HIGH" ]; then
    COMMON_ARGS="$COMMON_ARGS --year-high $YEAR_HIGH"
fi

# Function to run a query
run_query() {
    local query="$1"
    local num_results="$2"
    local description="$3"

    echo ""
    echo "========================================"
    echo "Query: $description"
    echo "Search: $query"
    echo "Results: $num_results"
    echo "========================================"

    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Would execute:"
        echo "python serpApi/fetch_scholar.py --query \"$query\" --num-results $num_results $COMMON_ARGS"
    else
        python serpApi/fetch_scholar.py --query "$query" --num-results "$num_results" $COMMON_ARGS

        # Show running stats after each query
        echo ""
        echo "Current database statistics:"
        python serpApi/fetch_scholar.py --query "placeholder" --stats $COMMON_ARGS
    fi
}

# =============================================================================
# QUERIES - Edit these as needed
# =============================================================================

echo "Starting multi-query fetch..."
echo "Database: $DB_PATH"
if [ -n "$YEAR_LOW" ]; then echo "Year range: $YEAR_LOW - ${YEAR_HIGH:-present}"; fi
echo ""

# # Query 1: Core IUU fishing terms (3,000 searches)
# run_query \
#     "IUU OR \"illegal fishing\" OR \"unreported fishing\" OR \"unregulated fishing\"" \
#     60000 \
#     "Core IUU fishing terminology"

# # Query 2: Seafood fraud and mislabeling (2,000 searches)
# run_query \
#     "\"seafood mislabeling\" OR \"seafood fraud\" OR \"seafood traceability\"" \
#     40000 \
#     "Seafood fraud and mislabeling"

# # Query 3: Transhipment with enforcement context (1,250 searches)
# run_query \
#     "transhipment fishing (enforcement OR arrest OR criminal OR investigation OR prosecution)" \
#     25000 \
#     "Transhipment and enforcement"

# # Query 4: Labor issues in fishing industry (1,000 searches)
# run_query \
#     "(\"forced labor\" OR \"unfree labor\" OR \"labor abuse\" OR \"human trafficking\") (fishing OR seafood OR vessel OR maritime)" \
#     20000 \
#     "Labor issues in fishing"

# # Query 5: Sanctions and fishing (750 searches)
# run_query \
#     "sanctions (fish OR seafood) (enforcement OR violation OR criminal OR prosecution)" \
#     15000 \
#     "Sanctions enforcement in fishing"

# Query 6: Workplace violations in fishing (750 searches)
run_query \
    "(\"workplace violations\" OR \"wage theft\") fishing (arrest OR criminal OR investigation)" \
    15000 \
    "Workplace violations in fishing"

# Query 7: IUU with criminal justice system (500 searches)
run_query \
    "IUU (arrest OR indictment OR prosecution OR \"search and seizure\" OR fine OR penalty)" \
    10000 \
    "IUU with criminal justice terms"

# Query 8: Illegal fishing enforcement (500 searches)
run_query \
    "\"illegal fishing\" (enforcement OR prosecution OR arrest OR criminal OR investigation)" \
    10000 \
    "Illegal fishing enforcement"

# =============================================================================
# FINAL STATISTICS
# =============================================================================

echo ""
echo "========================================"
echo "ALL QUERIES COMPLETE"
echo "========================================"
echo ""
python serpApi/fetch_scholar.py --query "placeholder" --stats $COMMON_ARGS

echo ""
echo "To process papers through the pipeline:"
echo "  python serpApi/process_papers.py --batch-size 25 --concurrency 3"
echo ""
echo "To download PDFs:"
echo "  python serpApi/fetch_scholar.py --query \"placeholder\" --download-pdfs"
