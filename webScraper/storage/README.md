# WebScraper Storage Module

Flexible storage backends for scraped content with support for JSON files and SQLite databases.

## Features

- **Multiple Storage Backends**: JSON and SQLite
- **Async Support**: All operations are async-compatible
- **Full-Text Search**: SQLite backend includes FTS5 for fast text search
- **Deduplication**: Automatic URL-based deduplication
- **Metadata Support**: Store custom metadata with each item
- **Export/Import**: Easy data migration between formats
- **Indexing**: Efficient lookups and queries

## Quick Start

### JSON Storage

```python
from pathlib import Path
from webScraper.storage import JSONStorage

# Initialize
storage = JSONStorage(
    output_dir=Path("output/json"),
    mode="single",  # or "individual" for separate files
    filename="scraped_data.json"
)

# Save items
await storage.save(scraped_content)
await storage.save_batch(list_of_contents)

# Query
item = await storage.get_by_url("https://example.com/article")
results = await storage.search(query="fishing", limit=10)

# Export
storage.export_to_file(Path("backup.json"))
```

### SQLite Storage

```python
from pathlib import Path
from webScraper.storage import SQLiteStorage

# Initialize
storage = SQLiteStorage(
    db_path=Path("output/data.db"),
    enable_fts=True  # Enable full-text search
)

# Save items
await storage.save(scraped_content)
await storage.save_batch(list_of_contents)

# Search with full-text search
results = await storage.search(query="illegal fishing")

# Search by date range
from datetime import datetime
results = await storage.search(
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31)
)

# Search by tags
results = await storage.search(tags=["IUU", "enforcement"])

# Get statistics
stats = storage.get_statistics()
print(f"Total items: {stats['total_items']}")

# Export to JSON
storage.export_to_json(Path("db_export.json"))

# Optimize database
storage.vacuum()
```

## Integration with Scrapers

```python
from webScraper.scrapers.generic_scraper import GenericScraper
from webScraper.storage import JSONStorage, SQLiteStorage
from pathlib import Path

# Scrape content
scraper = GenericScraper(site_name="oceana")
results = await scraper.scrape(
    query="illegal fishing",
    max_results=20,
    scrape_details=True
)

# Save to both JSON and SQLite
json_storage = JSONStorage(output_dir=Path("output/json"))
sqlite_storage = SQLiteStorage(db_path=Path("output/data.db"))

await json_storage.save_batch(results)
await sqlite_storage.save_batch(results)

await json_storage.close()
await sqlite_storage.close()
```

## Storage Comparison

| Feature | JSON | SQLite |
|---------|------|--------|
| **Performance** | Fast for small datasets | Scales well with large datasets |
| **Full-text search** | Basic substring matching | Advanced FTS5 with ranking |
| **Query capabilities** | Limited | Rich SQL queries |
| **File size** | Larger (pretty-printed) | Compact and efficient |
| **Human-readable** | Yes | Requires tools |
| **Best for** | Backups, data exchange | Production use, analysis |

## API Reference

### BaseStorage (Abstract)

All storage backends implement these methods:

- `save(content: ScrapedContent) -> bool`: Save single item
- `save_batch(contents: List[ScrapedContent]) -> int`: Save multiple items
- `get_by_url(url: str) -> Optional[ScrapedContent]`: Retrieve by URL
- `search(query, start_date, end_date, tags, limit) -> List[ScrapedContent]`: Search
- `count() -> int`: Get total count
- `close() -> None`: Cleanup resources

### JSONStorage

#### Constructor
```python
JSONStorage(
    output_dir: Path,
    mode: str = "single",  # "single" or "individual"
    filename: str = "scraped_data.json",
    pretty_print: bool = True
)
```

#### Additional Methods
- `export_to_file(output_path: Path) -> bool`: Export all data to single file

#### Modes

**Single File Mode** (`mode="single"`):
- All content in one JSON file
- Easy to manage and transfer
- Good for small to medium datasets (<10,000 items)

**Individual Files Mode** (`mode="individual"`):
- Each item in separate file
- Better for very large datasets
- Easier to manage individual items
- Creates `.index.json` for fast lookups

### SQLiteStorage

#### Constructor
```python
SQLiteStorage(
    db_path: Path,
    enable_fts: bool = True  # Enable full-text search
)
```

#### Additional Methods
- `get_statistics() -> Dict[str, Any]`: Database statistics
- `export_to_json(output_path: Path) -> bool`: Export to JSON
- `vacuum() -> bool`: Optimize database

#### Database Schema

**scraped_content table**:
- `id`: Primary key
- `url`: Unique URL
- `url_hash`: SHA256 hash for efficient lookups
- `title`: Article title
- `content`: Full text content
- `date`: Publication date
- `author`: Author name
- `scraped_at`: Timestamp when scraped
- `metadata`: JSON metadata
- `created_at`, `updated_at`: Timestamps

**tags table**:
- `id`: Primary key
- `content_id`: Foreign key to scraped_content
- `tag`: Tag name

**scraped_content_fts** (if FTS enabled):
- Virtual table for full-text search on title, content, and author

## Examples

See `examples.py` for comprehensive usage examples:

```bash
python webScraper/storage/examples.py
```

## Performance Tips

### JSON Storage
1. Use `mode="single"` for datasets under 10,000 items
2. Use `mode="individual"` for larger datasets or when items update frequently
3. Set `pretty_print=False` for production to reduce file size
4. Use `export_to_file()` for backups

### SQLite Storage
1. Enable FTS5 for text search (`enable_fts=True`)
2. Use indexed fields (url, date, author) in queries
3. Run `vacuum()` periodically to optimize database
4. Use batch operations (`save_batch()`) for better performance
5. Query with `limit` to avoid loading large result sets

## Migration

### JSON to SQLite
```python
# Load from JSON
json_storage = JSONStorage(output_dir=Path("old_data"))
results = await json_storage.search(limit=None)  # Get all

# Save to SQLite
sqlite_storage = SQLiteStorage(db_path=Path("new_data.db"))
await sqlite_storage.save_batch(results)
```

### SQLite to JSON
```python
sqlite_storage = SQLiteStorage(db_path=Path("data.db"))
sqlite_storage.export_to_json(Path("export.json"))
```

## Error Handling

All storage operations handle errors gracefully:
- Failed saves return `False` or `0` (batch)
- Failed retrievals return `None` or empty list
- Errors are logged using Python's logging module

```python
import logging
logging.basicConfig(level=logging.INFO)

# Now storage operations will log errors
storage = SQLiteStorage(db_path=Path("data.db"))
```

## Thread Safety

- **JSONStorage**: Use separate instances per thread
- **SQLiteStorage**: Use connection pooling or separate instances for concurrent writes

## Best Practices

1. **Always close storage**: Use `await storage.close()` or context managers
2. **Batch operations**: Use `save_batch()` instead of multiple `save()` calls
3. **Deduplication**: URLs are automatically deduplicated
4. **Backups**: Regularly export to JSON for backups
5. **Monitoring**: Use `count()` and `get_statistics()` to monitor growth

## Troubleshooting

**JSON files too large?**
- Switch to `mode="individual"`
- Disable pretty printing
- Split by date/category

**SQLite slow queries?**
- Ensure FTS is enabled for text search
- Use indexed fields in WHERE clauses
- Run VACUUM to optimize

**Memory issues?**
- Use `limit` parameter in searches
- Process in batches
- Close connections when done

## License

Part of the IUU Fishing Project webScraper module.
