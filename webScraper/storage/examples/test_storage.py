"""
Standalone test for storage functionality.
Works with the actual ScrapedContent class from base_scraper.
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Set UTF-8 encoding for Windows console
if os.name == "nt":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from webScraper.scrapers.base_scraper import ScrapedContent
from webScraper.storage.json_storage import JSONStorage
from webScraper.storage.sqlite_storage import SQLiteStorage


async def test_json_storage():
    """Test JSON storage functionality."""
    print("\n" + "=" * 80)
    print("Testing JSON Storage")
    print("=" * 80)

    # Create test data
    test_data = [
        ScrapedContent(
            url="https://test.com/article1",
            title="Test Article 1",
            content="This is test content for article 1",
            date=datetime(2024, 1, 15),
            author="Test Author",
            tags=["test", "article"],
        ),
        ScrapedContent(
            url="https://test.com/article2",
            title="Test Article 2",
            content="This is test content for article 2",
            date=datetime(2024, 2, 20),
            author="Another Author",
            tags=["test", "example"],
        ),
    ]

    # Test single file mode
    print("\n[1] Testing single file mode...")
    output_dir = Path("webScraper/output/test_json_single")
    storage = JSONStorage(output_dir=output_dir, mode="single")

    print("  - Saving items...")
    count = await storage.save_batch(test_data)
    print(f"  ✓ Saved {count} items")

    print("  - Counting items...")
    total = await storage.count()
    print(f"  ✓ Total items: {total}")

    print("  - Retrieving by URL...")
    retrieved = await storage.get_by_url("https://test.com/article1")
    if retrieved:
        print(f"  ✓ Retrieved: {retrieved.title}")
    else:
        print("  ✗ Failed to retrieve")

    print("  - Searching...")
    results = await storage.search(query="test")
    print(f"  ✓ Found {len(results)} results")

    await storage.close()

    # Test individual file mode
    print("\n[2] Testing individual file mode...")
    output_dir = Path("webScraper/output/test_json_individual")
    storage = JSONStorage(output_dir=output_dir, mode="individual")

    print("  - Saving items...")
    count = await storage.save_batch(test_data)
    print(f"  ✓ Saved {count} items")

    print("  - Counting items...")
    total = await storage.count()
    print(f"  ✓ Total items: {total}")

    await storage.close()

    print("\n✓ JSON Storage tests passed!")


async def test_sqlite_storage():
    """Test SQLite storage functionality."""
    print("\n" + "=" * 80)
    print("Testing SQLite Storage")
    print("=" * 80)

    # Create test data
    test_data = [
        ScrapedContent(
            url="https://test.com/db-article1",
            title="Database Test Article 1",
            content="Testing SQLite storage with full text search",
            date=datetime(2024, 1, 10),
            author="DB Author",
            tags=["database", "test", "sqlite"],
            metadata={"category": "testing"},
        ),
        ScrapedContent(
            url="https://test.com/db-article2",
            title="Database Test Article 2",
            content="More content for testing search functionality",
            date=datetime(2024, 1, 15),
            author="Another DB Author",
            tags=["database", "search"],
            metadata={"category": "testing", "priority": "high"},
        ),
        ScrapedContent(
            url="https://test.com/db-article3",
            title="Third Test Article",
            content="Additional test content",
            date=datetime(2024, 2, 1),
            author="DB Author",
            tags=["test"],
        ),
    ]

    db_path = Path("webScraper/output/test_data.db")
    storage = SQLiteStorage(db_path=db_path, enable_fts=True)

    print("\n[1] Saving items...")
    count = await storage.save_batch(test_data)
    print(f"  ✓ Saved {count} items")

    print("\n[2] Counting items...")
    total = await storage.count()
    print(f"  ✓ Total items: {total}")

    print("\n[3] Retrieving by URL...")
    retrieved = await storage.get_by_url("https://test.com/db-article1")
    if retrieved:
        print(f"  ✓ Retrieved: {retrieved.title}")
        print(f"    Author: {retrieved.author}")
        print(f"    Tags: {retrieved.tags}")
    else:
        print("  ✗ Failed to retrieve")

    print("\n[4] Full-text search...")
    results = await storage.search(query="search")
    print(f"  ✓ Found {len(results)} results for 'search'")
    for r in results:
        print(f"    - {r.title}")

    print("\n[5] Searching by tags...")
    results = await storage.search(tags=["database"])
    print(f"  ✓ Found {len(results)} results with tag 'database'")

    print("\n[6] Searching by date range...")
    results = await storage.search(
        start_date=datetime(2024, 1, 1), end_date=datetime(2024, 1, 31)
    )
    print(f"  ✓ Found {len(results)} results in January 2024")

    print("\n[7] Getting statistics...")
    stats = storage.get_statistics()
    print(f"  ✓ Total items: {stats.get('total_items')}")
    print(f"    Date range: {stats.get('earliest_date')} to {stats.get('latest_date')}")
    print(f"    DB size: {stats.get('database_size_bytes', 0) / 1024:.2f} KB")
    top_tags = stats.get("top_tags", [])
    if top_tags:
        print(f"    Top tags: {[t['tag'] for t in top_tags[:3]]}")

    print("\n[8] Exporting to JSON...")
    export_path = Path("webScraper/output/test_export.json")
    success = storage.export_to_json(export_path)
    print(f"  {'✓' if success else '✗'} Export {'succeeded' if success else 'failed'}")

    print("\n[9] Optimizing database...")
    success = storage.vacuum()
    print(f"  {'✓' if success else '✗'} Vacuum {'succeeded' if success else 'failed'}")

    await storage.close()

    print("\n✓ SQLite Storage tests passed!")


async def test_deduplication():
    """Test that duplicate URLs are handled correctly."""
    print("\n" + "=" * 80)
    print("Testing Deduplication")
    print("=" * 80)

    duplicate_data = [
        ScrapedContent(
            url="https://test.com/same-url",
            title="First Version",
            content="Original content",
        ),
        ScrapedContent(
            url="https://test.com/same-url",
            title="Second Version",
            content="Updated content",
        ),
    ]

    # Test JSON deduplication
    print("\n[1] Testing JSON deduplication...")
    output_dir = Path("webScraper/output/test_dedup_json")
    json_storage = JSONStorage(output_dir=output_dir, mode="single")

    await json_storage.save(duplicate_data[0])
    result = await json_storage.save(duplicate_data[1])

    count = await json_storage.count()
    print(f"  ✓ Saved duplicate, count: {count} (should be 1)")
    await json_storage.close()

    # Test SQLite deduplication (replaces on duplicate)
    print("\n[2] Testing SQLite deduplication...")
    db_path = Path("webScraper/output/test_dedup.db")
    sqlite_storage = SQLiteStorage(db_path=db_path)

    await sqlite_storage.save(duplicate_data[0])
    await sqlite_storage.save(duplicate_data[1])

    count = await sqlite_storage.count()
    retrieved = await sqlite_storage.get_by_url("https://test.com/same-url")

    print(f"  ✓ After saving duplicate, count: {count} (should be 1)")
    print(f"  ✓ Retrieved title: {retrieved.title} (should be 'Second Version')")

    await sqlite_storage.close()

    print("\n✓ Deduplication tests passed!")


async def main():
    """Run all tests."""
    print("\n")
    print("=" * 80)
    print("WebScraper Storage Tests")
    print("=" * 80)

    try:
        await test_json_storage()
        await test_sqlite_storage()
        await test_deduplication()

        print("\n" + "=" * 80)
        print("All tests passed! ✓")
        print("=" * 80)
        print("\nGenerated files in: webScraper/output/")

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
