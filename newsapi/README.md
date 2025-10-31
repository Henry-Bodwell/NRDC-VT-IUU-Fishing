# NewsAPI Integration for IUU Fishing

Automated news article fetching and processing for the IUU incident tracking system using EventRegistry.

## Quick Start

```bash
# 1. Install dependencies
pip install eventregistry arrow aiohttp

# 2. Fetch articles (uses default complex query)
python fetch_newsapi.py \
  --api-key YOUR_EVENTREGISTRY_KEY \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --fetch-articles

# 3. Start your API server
uvicorn app.main:app --reload

# 4. Process articles through pipeline
python process_articles.py --batch-size 10 --concurrency 3
```

## Fetching Articles

### Default Complex Query (Recommended)

The default query searches for comprehensive IUU fishing coverage:
- Direct IUU fishing articles
- Seafood mislabeling
- Labor violations in seafood industry with enforcement actions

```bash
python fetch_newsapi.py \
  --api-key YOUR_KEY \
  --start-date 2024-01-01 \
  --fetch-articles
```

### Custom Concepts

Override with your own EventRegistry concept URIs:

```bash
python fetch_newsapi.py \
  --api-key YOUR_KEY \
  --start-date 2024-01-01 \
  --concepts \
    "http://en.wikipedia.org/wiki/Overfishing" \
    "http://en.wikipedia.org/wiki/Marine_conservation" \
  --fetch-articles
```

### Two-Phase Fetching (For Large Datasets)

**Phase 1: Get URIs (fast)**
```bash
python fetch_newsapi.py \
  --api-key YOUR_KEY \
  --start-date 2024-01-01
```
Creates: `data/newsapi/2024-01-01_iuu_fishing_TIMESTAMP_uris.json`

**Phase 2: Download articles**
```bash
python fetch_newsapi.py \
  --api-key YOUR_KEY \
  --start-date 2024-01-01 \
  --uri-file data/newsapi/2024-01-01_iuu_fishing_TIMESTAMP_uris.json \
  --fetch-articles
```

## Processing Articles

### Process Batch
```bash
# Process 10 articles with 3 concurrent requests (default)
python process_articles.py

# Process 50 articles with 5 concurrent
python process_articles.py --batch-size 50 --concurrency 5

# Process all unprocessed articles
python process_articles.py --all
```

### Check Status
```bash
python process_articles.py --stats
```

Output:
```
NewsAPI Article Processing Statistics
============================================================
Total articles downloaded: 1000
Processed successfully:    250
Not yet processed:         700
Processing errors:         50

Progress: 25.0% complete
```

## Default Query Structure

The default query finds articles matching:

```
(IUU Fishing) OR (Seafood Mislabeling) OR
(
  (Transshipment OR Sanctions OR Labor Violations OR Violence OR Wage Theft)
  AND
  (Ship OR Seafood OR Fish)
  AND
  (Arrest OR Investigation OR Indictment OR Seizure OR Fine)
)
```

This captures:
1. Direct IUU fishing mentions
2. Seafood fraud/mislabeling
3. Labor/sanctions issues in maritime/seafood context with enforcement

## Data Storage

### SQLite: `data/newsapi.db`
Tracks download and processing status:
- `uri`: EventRegistry article ID
- `filepath`: Path to JSON file
- `downloaded_at`: Download timestamp
- `processed`: 0=pending, 1=completed
- `processed_at`: Processing timestamp
- `processing_error`: Error message if failed

### JSON Files: `data/newsapi/v0.1_raw/YYYY/MM/DD.json`
Newline-delimited JSON with full article content

## Command Reference

### fetch_newsapi.py

```
--api-key          EventRegistry API key (required)
--start-date       Start date YYYY-MM-DD (required)
--end-date         End date YYYY-MM-DD (default: yesterday)
--concepts         List of concept URIs (overrides default query)
--outfile          Output filename prefix
--fetch-articles   Download full articles (not just URIs)
--uri-file         Load URIs from file (skip fetching)
```

### process_articles.py

```
--batch-size       Number of articles to process (default: 10)
--concurrency      Max concurrent requests (default: 3, safe: 1-10)
--api-url          API base URL (default: http://localhost:8000)
--user-id          User ID for audit logs (default: newsapi_processor)
--db-path          SQLite database path (default: data/newsapi.db)
--stats            Show statistics only
--all              Process all unprocessed articles
```

## Processing Flow

```
EventRegistry API
      ↓
fetch_newsapi.py (download)
      ↓
data/newsapi/v0.1_raw/YYYY/MM/DD.json
      ↓
process_articles.py (via HTTP API)
      ↓
POST /api/incidents → task_id (202 Accepted)
      ↓
Poll GET /api/tasks/{task_id} (every 5s, max 10min)
      ↓
MongoDB (Sources, IncidentReports, IndustryOverviews)
```

## Concurrency Details

The processing script uses:
- **Semaphore-based concurrency control**
- **Async task polling** (one poll loop per article)
- **Configurable limits** (default: 3 concurrent)

Example with `--concurrency 3` and 10 articles:
```
Time  | Active Tasks
------|------------------
0s    | [1] [2] [3]        ← First 3 submit
5s    | [1] [2] [3]        ← Polling
10s   | [1] [2] [3]        ← Still processing
20s   | [4] [5] [3]        ← 1&2 done, 4&5 start
30s   | [4] [6] [7]        ← 3&5 done, 6&7 start
```

**Safe concurrency levels:**
- 1-3: Conservative (default)
- 4-5: Moderate
- 6-10: Aggressive (watch OpenAI rate limits)

## Complete Workflow Example

```bash
# 1. Fetch articles for Q1 2024
python fetch_newsapi.py \
  --api-key $EVENTREGISTRY_KEY \
  --start-date 2024-01-01 \
  --end-date 2024-03-31 \
  --fetch-articles

# Output: Downloaded 500 articles to data/newsapi.db

# 2. Check status
python process_articles.py --stats
# Output: Total: 500, Processed: 0, Unprocessed: 500

# 3. Start API server (in another terminal)
uvicorn app.main:app --reload

# 4. Process in batches
python process_articles.py --batch-size 25 --concurrency 5

# 5. Monitor progress
python process_articles.py --stats
# Output: Total: 500, Processed: 25, Unprocessed: 475

# 6. Continue processing
python process_articles.py --batch-size 100 --concurrency 5
python process_articles.py --all  # Process remaining
```

## Troubleshooting

**No articles found?**
- Verify EventRegistry API key is valid
- Try broader date ranges
- Check default query concepts are accessible

**Processing errors?**
- Ensure FastAPI server is running
- Check MongoDB is connected
- Verify OpenAI API key is set
- Review logs for specific errors

**Duplicate warnings?**
- Normal - articles already in database are skipped (409 Conflict)
- Marked as successful processing

**Slow processing?**
- Each article takes 10-30s (LLM calls)
- Increase `--concurrency` (up to 10)
- Process in multiple sessions

**Re-process articles:**
```sql
-- Reset all to unprocessed
UPDATE articles SET processed = 0, processed_at = NULL, processing_error = NULL;

-- Reset only failed
UPDATE articles SET processed = 0, processed_at = NULL
WHERE processing_error IS NOT NULL;
```

## Output Files

**URI list:** `data/newsapi/2024-01-01_iuu_fishing_TIMESTAMP_uris.json`
```json
{
  "uris": ["123", "456", ...],
  "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
  "total_count": 1234,
  "query_type": "complex",
  "query": {...}
}
```

**Article files:** `data/newsapi/v0.1_raw/2024/01/15.json`
```
{"uri": "123", "title": "...", "body": "...", "url": "...", "date": "2024-01-15"}
{"uri": "456", "title": "...", "body": "...", "url": "...", "date": "2024-01-15"}
```

## Finding Concept URIs

Visit https://eventregistry.org/ to search for concepts and get their Wikipedia URIs.

Good IUU fishing concepts:
- Illegal fishing
- Overfishing
- Fishing violations
- Maritime crime
- Fisheries enforcement
- Transshipment
- Seafood fraud
