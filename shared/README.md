# Shared Pipeline Client Module

This module provides reusable components for submitting articles to the IUU incident extraction pipeline API. It eliminates duplicate code between the newsapi and webscraper upload scripts.

## Components

### `submit_article_to_pipeline()`

Core async function that handles the full pipeline workflow:
- Submits article to `/api/incidents` endpoint
- Polls `/api/tasks/{task_id}` until completion
- Handles authentication, errors, and timeouts
- Returns `(success: bool, error_msg: Optional[str])`

**Example:**
```python
from shared.pipeline_client import submit_article_to_pipeline

payload = {
    "text": "Article content...",
    "title": "Article title",
    "url": "https://example.com/article",
    "source_type": "news",
    "status": "from_api",
    "input_name": "newsapi"
}

success, error = await submit_article_to_pipeline(
    payload,
    api_url="http://localhost:8000",
    auth_token="your_jwt_token"
)
```

### `ProcessingTracker`

SQLite-based tracker for managing article processing status. Provides:
- Tracking which articles have been processed
- Marking articles as complete/failed with error messages
- Getting processing statistics
- Preventing duplicate processing

**Example:**
```python
from shared.pipeline_client import ProcessingTracker

# Initialize tracker
tracker = ProcessingTracker(
    db_path="data/articles.db",
    table_name="articles",
    key_field="url"  # or "uri" for newsapi
)

# Initialize database schema
tracker.init_db(additional_fields=[
    ("title", "TEXT"),
    ("content_hash", "TEXT")
])

# Import articles
tracker.import_keys(
    ["http://url1.com", "http://url2.com"],
    additional_data={
        "title": ["Title 1", "Title 2"],
        "content_hash": ["hash1", "hash2"]
    }
)

# Get unprocessed articles
unprocessed = tracker.get_unprocessed_keys(limit=10)

# Mark as processed
tracker.mark_processed("http://url1.com", success=True)
tracker.mark_processed("http://url2.com", success=False, error_msg="Timeout")

# Get stats
stats = tracker.get_stats()
# Returns: {"total": 2, "processed": 2, "unprocessed": 0, "errors": 1}
```

### `process_batch_with_concurrency()`

Generic batch processing function with concurrency control using semaphores.

**Example:**
```python
from shared.pipeline_client import process_batch_with_concurrency

async def my_processor(article, index):
    # Process one article
    success, error = await submit_article_to_pipeline(...)
    return (success, error)

stats = await process_batch_with_concurrency(
    articles=article_list,
    process_func=my_processor,
    concurrency=3,
    show_progress=True
)
# Returns: {"success": 8, "failed": 2}
```

### `print_processing_stats()`

Formatted output for processing statistics.

**Example:**
```python
from shared.pipeline_client import print_processing_stats

stats = {"total": 100, "processed": 75, "unprocessed": 25, "errors": 5}
print_processing_stats(stats, source_name="NewsAPI")
```

Output:
```
NewsAPI Processing Statistics
============================================================
Total articles imported:   100
Processed successfully:    75
Not yet processed:         25
Processing errors:         5

Progress: 75.0% complete
```

## Usage in Scripts

### NewsAPI Processor ([newsapi/process_articles.py](../newsapi/process_articles.py))

The newsapi script uses:
- `submit_article_to_pipeline()` for submitting articles
- `print_processing_stats()` for formatted stats output
- Keeps `NewsapiFetcher` class for database tracking (legacy compatibility)

### WebScraper Uploader ([webScraper/upload_scraped_data.py](../webScraper/upload_scraped_data.py))

The webscraper script uses:
- `submit_article_to_pipeline()` for submitting articles
- `ProcessingTracker` for database tracking
- `print_processing_stats()` for formatted stats output

## Benefits

1. **Code Reuse**: ~200 lines of duplicate code eliminated
2. **Consistency**: Both scripts use identical pipeline submission logic
3. **Maintainability**: Bug fixes and improvements in one place
4. **Testability**: Shared functions can be unit tested independently
5. **Flexibility**: `ProcessingTracker` can be used for any new data sources

## Design Decisions

- **Generic `ProcessingTracker`**: Configurable table name and key field allows reuse across different data sources
- **Separate from existing code**: Doesn't modify existing `NewsapiFetcher` class to maintain backward compatibility
- **Verbose flag**: `submit_article_to_pipeline()` can run silently for batch processing
- **Async-first**: All functions designed for asyncio for better performance
