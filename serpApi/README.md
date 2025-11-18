# Google Scholar Paper Fetcher (SerpAPI)

This module fetches academic papers from Google Scholar using SerpAPI and processes them through the IUU incident analysis pipeline.

## Features

- **Incremental Fetching**: Papers saved as they're fetched, safe to interrupt
- **SQLite Tracking**: Database tracks which papers have been processed
- **PDF Support**: Automatically extracts and downloads PDF links
- **Author Metadata**: Parses author information and publication years
- **Batch Processing**: Process papers through pipeline with concurrency control
- **Idempotent**: Safe to re-run, skips duplicates automatically

## Setup

1. **Install Dependencies**:
```bash
pip install requests aiohttp
```

2. **Get SerpAPI Key**:
   - Sign up at https://serpapi.com/
   - Get your API key from the dashboard

3. **Set Environment Variable**:
```bash
export SERPAPI_KEY="your_api_key_here"
```

## Database Schema

Papers are tracked in SQLite with the following schema:

```sql
CREATE TABLE papers (
    result_id TEXT PRIMARY KEY,           -- Unique identifier from SerpAPI
    title TEXT,
    authors TEXT,                         -- Parsed from publication_info
    publication_year INTEGER,             -- Extracted from publication_info
    publication_info TEXT,                -- Full publication summary
    pdf_link TEXT,                        -- Direct PDF link (if available)
    pdf_source TEXT,                      -- PDF source domain
    main_link TEXT,                       -- Main paper link
    snippet TEXT,                         -- Paper excerpt
    cited_by_count INTEGER,               -- Citation count
    cluster_id TEXT,                      -- Google Scholar cluster ID
    filepath TEXT,                        -- Path to saved JSON
    downloaded_at TIMESTAMP,              -- When fetched
    processed BOOLEAN DEFAULT 0,          -- Processing status
    processed_at TIMESTAMP,               -- When processed
    processing_error TEXT                 -- Error message if failed
)
```

## Usage

### 1. Fetch Papers

Fetch papers from Google Scholar and save to SQLite:

```bash
# Basic search
python fetch_scholar.py --query "illegal fishing" --num-results 100

# With year filters
python fetch_scholar.py \
  --query "IUU fishing enforcement" \
  --num-results 200 \
  --year-low 2020 \
  --year-high 2024

# Custom database location
python fetch_scholar.py \
  --query "fisheries crime" \
  --num-results 50 \
  --db-path /custom/path/scholar.db
```

**Features:**
- Automatically skips papers already in database (uses `result_id` PRIMARY KEY)
- Saves papers to `data/scholar/v0.1_raw/YYYY/MM/DD.json` (newline-delimited JSON)
- Extracts PDF links, author data, citations, and metadata
- Rate-limited to 1 request/second

### 2. Download PDFs

Download PDFs for papers that have PDF links:

```bash
# Download PDFs for all unprocessed papers
python fetch_scholar.py \
  --query "placeholder" \
  --download-pdfs

# PDFs saved to: data/scholar/pdfs/
```

**Filename format**: `{year}_{title_slug}_{result_id}.pdf`

### 3. Check Statistics

View processing status:

```bash
python fetch_scholar.py --stats

# Or via process_papers.py
python process_papers.py --stats
```

**Output:**
```
Processing Statistics:
  Total papers: 250
  Processed: 180
  Unprocessed: 65
  Errors: 5
  Progress: 72.0%
```

### 4. Process Papers Through Pipeline

Send papers to the IUU incident analysis pipeline:

```bash
# Process a batch of 10 papers
python process_papers.py --batch-size 10 --concurrency 3

# Process all unprocessed papers
python process_papers.py --all --concurrency 5

# Custom API URL
python process_papers.py \
  --batch-size 20 \
  --api-url http://api.example.com:8000

# With authentication
python process_papers.py \
  --batch-size 10 \
  --auth-token "your_token_here"
# Or: export API_AUTH_TOKEN="your_token_here"
```

**Parameters:**
- `--batch-size`: Number of papers to process in this run
- `--concurrency`: Number of simultaneous API requests (default: 3)
- `--api-url`: Base URL of the IUU pipeline API (default: http://localhost:8000)
- `--all`: Process all unprocessed papers (ignores batch-size)
- `--stats`: Show statistics without processing

## Workflow Example

Complete workflow for fetching and processing papers:

```bash
# 1. Fetch papers from Google Scholar
export SERPAPI_KEY="your_key_here"
python fetch_scholar.py \
  --query "illegal unreported unregulated fishing" \
  --num-results 500 \
  --year-low 2015

# 2. Check what was fetched
python fetch_scholar.py --stats
# Output: Total papers: 500, Processed: 0, Unprocessed: 500

# 3. Download PDFs for papers with PDF links
python fetch_scholar.py --query "placeholder" --download-pdfs

# 4. Process through pipeline (batch of 25 at a time)
python process_papers.py --batch-size 25 --concurrency 5

# 5. Check progress
python process_papers.py --stats
# Output: Total papers: 500, Processed: 25, Unprocessed: 475

# 6. Continue processing
python process_papers.py --all --concurrency 5
```

## Data Storage

### File Organization

```
data/
├── scholar.db                          # SQLite tracking database
└── scholar/
    ├── v0.1_raw/                       # Raw paper JSON
    │   └── 2024/
    │       └── 11/
    │           └── 18.json             # Newline-delimited JSON
    └── pdfs/                           # Downloaded PDFs
        └── 2023_Illegal_Fishing_Networks_abc123.pdf
```

### Paper JSON Format

Each line in the daily JSONL file contains the full SerpAPI response for one paper:

```json
{
  "position": 0,
  "title": "Illegal fishing and fisheries crime",
  "result_id": "abc123xyz",
  "link": "https://example.com/paper",
  "snippet": "This paper examines...",
  "publication_info": {
    "summary": "J Smith, A Jones - Marine Policy, 2023 - Elsevier"
  },
  "resources": [
    {
      "title": "researchgate.net",
      "file_format": "PDF",
      "link": "https://www.researchgate.net/...pdf"
    }
  ],
  "inline_links": {
    "cited_by": {
      "total": 45,
      "cites_id": "123456789"
    },
    "versions": {
      "cluster_id": "987654321"
    }
  }
}
```

## Processing Pipeline Integration

When papers are sent to the pipeline:

1. **URL Selection**: Prefers PDF link, falls back to main link
2. **Metadata Attached**: Includes `result_id`, title, authors, year, citations
3. **Source Type**: Marked as `google_scholar` in the Source document
4. **Duplicate Handling**: API returns 409 if article already exists (treated as success)
5. **Async Processing**: Polls task endpoint every 5 seconds (5 minute timeout)

## Troubleshooting

### Reset Processing Status

If processing failed and you want to retry:

```sql
-- Reset all to unprocessed
sqlite3 data/scholar.db "UPDATE papers SET processed = 0, processed_at = NULL, processing_error = NULL"

-- Reset only failed papers
sqlite3 data/scholar.db "UPDATE papers SET processed = 0, processed_at = NULL WHERE processing_error IS NOT NULL"
```

### View Failed Papers

```sql
sqlite3 data/scholar.db "SELECT result_id, title, processing_error FROM papers WHERE processing_error IS NOT NULL"
```

### Check Paper Details

```sql
sqlite3 data/scholar.db "SELECT * FROM papers WHERE result_id = 'abc123xyz'"
```

## API Rate Limits

**SerpAPI:**
- Free tier: 100 searches/month
- Paid tiers: 5,000+ searches/month
- Rate limiting: 1 request/second implemented

**Google Scholar (via SerpAPI):**
- 10 results per page (max 20 with `num` parameter)
- Pagination supported via `start` parameter

## Advanced Usage

### Fetch Specific Authors

```bash
python fetch_scholar.py \
  --query "author:\"John Smith\" illegal fishing" \
  --num-results 50
```

### Fetch from Specific Journal

```bash
python fetch_scholar.py \
  --query "source:\"Marine Policy\" IUU fishing" \
  --num-results 100
```

### Custom User ID for Audit Logging

```bash
python process_papers.py \
  --batch-size 10 \
  --user-id "researcher_jane_doe"
```

## Comparison with NewsAPI Module

Both modules follow the same pattern:

| Feature | NewsAPI | ScholarAPI |
|---------|---------|------------|
| **Primary Key** | `uri` (EventRegistry ID) | `result_id` (SerpAPI ID) |
| **PDF Support** | Via URL extraction | Native via `resources` field |
| **Author Data** | In article text | Structured in `publication_info` |
| **Storage Format** | JSONL by date | JSONL by date |
| **Processing** | Async batch with semaphore | Async batch with semaphore |
| **Deduplication** | PRIMARY KEY constraint | PRIMARY KEY constraint |

## Dependencies

- **requests**: HTTP client for SerpAPI
- **aiohttp**: Async HTTP for pipeline API
- **sqlite3**: Built-in Python SQLite
- **asyncio**: Built-in async support

## Environment Variables

- `SERPAPI_KEY`: Your SerpAPI key (required for fetching)
- `API_AUTH_TOKEN`: Optional auth token for pipeline API

## Files

- `fetch_scholar.py`: Fetcher class and CLI for downloading papers
- `process_papers.py`: Batch processor for pipeline integration
- `example.json`: Sample SerpAPI response structure
- `README.md`: This file
