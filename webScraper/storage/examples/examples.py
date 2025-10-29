"""
Example usage of storage backends for webScraper.

Demonstrates how to save scraped content to JSON and SQLite.
"""

import asyncio
from pathlib import Path
from datetime import datetime

from webScraper.scrapers.base_scraper import ScrapedContent
from webScraper.storage.json_storage import JSONStorage
from webScraper.storage.sqlite_storage import SQLiteStorage


async def example_json_storage():
    """Example of using JSON storage."""
    print("\n" + "=" * 80)
    print("JSON Storage Example")
    print("=" * 80)

    # Create sample data
    content1 = ScrapedContent(
        url="https://example.com/article1",
        title="Illegal Fishing Incident in Pacific",
        content="Full article content here...",
        date=datetime(2024, 1, 15),
        author="John Doe",
        tags=["IUU", "Pacific", "enforcement"],
        metadata={"source": "oceana", "category": "illegal_fishing"},
    )

    content2 = ScrapedContent(
        url="https://example.com/article2",
        title="New Regulations on Fishing",
        content="Details about new regulations...",
        date=datetime(2024, 2, 20),
        author="Jane Smith",
        tags=["regulations", "policy"],
        metadata={"source": "doj", "category": "policy"},
    )

    # Initialize JSON storage (single file mode)
    output_dir = Path("webScraper/output/json_storage")
    json_storage = JSONStorage(
        output_dir=output_dir, mode="single", filename="scraped_articles.json"
    )

    # Save individual items
    print("\nSaving items...")
    await json_storage.save(content1)
    await json_storage.save(content2)

    # Get count
    count = await json_storage.count()
    print(f"Total items saved: {count}")

    # Retrieve by URL
    print("\nRetrieving by URL...")
    retrieved = await json_storage.get_by_url("https://example.com/article1")
    if retrieved:
        print(f"Retrieved: {retrieved.title}")

    # Search
    print("\nSearching for 'fishing'...")
    results = await json_storage.search(query="fishing", limit=5)
    print(f"Found {len(results)} results")
    for result in results:
        print(f"  - {result.title}")

    # Export to consolidated file
    print("\nExporting to consolidated file...")
    json_storage.export_to_file(output_dir / "consolidated_export.json")

    await json_storage.close()
    print("\nJSON storage example completed!")


async def example_json_storage_individual():
    """Example of using JSON storage with individual files."""
    print("\n" + "=" * 80)
    print("JSON Storage (Individual Files) Example")
    print("=" * 80)

    # Create sample data
    contents = [
        ScrapedContent(
            url=f"https://example.com/article{i}",
            title=f"Article {i}",
            content=f"Content for article {i}...",
            date=datetime(2024, 1, i),
            tags=["tag1", "tag2"] if i % 2 == 0 else ["tag3"],
        )
        for i in range(1, 6)
    ]

    # Initialize JSON storage (individual file mode)
    output_dir = Path("webScraper/output/json_individual")
    json_storage = JSONStorage(output_dir=output_dir, mode="individual")

    # Save batch
    print("\nSaving batch of items...")
    saved_count = await json_storage.save_batch(contents)
    print(f"Saved {saved_count} items")

    # Count
    count = await json_storage.count()
    print(f"Total items: {count}")

    await json_storage.close()
    print("\nIndividual files example completed!")


async def example_sqlite_storage():
    """Example of using SQLite storage."""
    print("\n" + "=" * 80)
    print("SQLite Storage Example")
    print("=" * 80)

    # Create sample data
    contents = [
        ScrapedContent(
            url="https://example.com/db-article1",
            title="Vessel Seized for Illegal Fishing",
            content="Details about the vessel seizure in territorial waters...",
            date=datetime(2024, 1, 10),
            author="Reporter A",
            tags=["seizure", "enforcement", "IUU"],
            metadata={"severity": "high", "location": "Pacific"},
        ),
        ScrapedContent(
            url="https://example.com/db-article2",
            title="Labor Abuse Investigation on Fishing Vessels",
            content="Investigation reveals labor violations...",
            date=datetime(2024, 1, 15),
            author="Reporter B",
            tags=["labor", "human_rights", "investigation"],
            metadata={"severity": "critical", "location": "Atlantic"},
        ),
        ScrapedContent(
            url="https://example.com/db-article3",
            title="New Technology for Fisheries Monitoring",
            content="Advanced satellite tracking systems deployed...",
            date=datetime(2024, 2, 1),
            author="Reporter A",
            tags=["technology", "monitoring", "innovation"],
            metadata={"category": "technology"},
        ),
    ]

    # Initialize SQLite storage
    db_path = Path("webScraper/output/scraped_data.db")
    sqlite_storage = SQLiteStorage(db_path=db_path, enable_fts=True)

    # Save batch
    print("\nSaving items to database...")
    saved_count = await sqlite_storage.save_batch(contents)
    print(f"Saved {saved_count} items")

    # Get count
    count = await sqlite_storage.count()
    print(f"Total items in database: {count}")

    # Retrieve by URL
    print("\nRetrieving by URL...")
    retrieved = await sqlite_storage.get_by_url("https://example.com/db-article1")
    if retrieved:
        print(f"Retrieved: {retrieved.title}")
        print(f"  Author: {retrieved.author}")
        print(f"  Tags: {retrieved.tags}")

    # Full-text search
    print("\nFull-text search for 'fishing'...")
    results = await sqlite_storage.search(query="fishing")
    print(f"Found {len(results)} results:")
    for result in results:
        print(f"  - {result.title} (by {result.author})")

    # Search by tags
    print("\nSearching by tag 'enforcement'...")
    results = await sqlite_storage.search(tags=["enforcement"])
    print(f"Found {len(results)} results:")
    for result in results:
        print(f"  - {result.title}")

    # Search by date range
    print("\nSearching by date range (January 2024)...")
    results = await sqlite_storage.search(
        start_date=datetime(2024, 1, 1), end_date=datetime(2024, 1, 31)
    )
    print(f"Found {len(results)} results:")
    for result in results:
        print(f"  - {result.title} ({result.date.date() if result.date else 'N/A'})")

    # Get statistics
    print("\nDatabase statistics:")
    stats = sqlite_storage.get_statistics()
    print(f"  Total items: {stats.get('total_items')}")
    print(f"  Date range: {stats.get('earliest_date')} to {stats.get('latest_date')}")
    print(f"  Database size: {stats.get('database_size_bytes', 0) / 1024:.2f} KB")
    print(f"  Top tags: {[t['tag'] for t in stats.get('top_tags', [])[:3]]}")

    # Export to JSON
    print("\nExporting database to JSON...")
    export_path = Path("webScraper/output/db_export.json")
    sqlite_storage.export_to_json(export_path)
    print(f"Exported to {export_path}")

    # Vacuum database
    print("\nOptimizing database...")
    sqlite_storage.vacuum()

    await sqlite_storage.close()
    print("\nSQLite storage example completed!")


async def example_combined_usage():
    """Example showing combined usage with actual scraper."""
    print("\n" + "=" * 80)
    print("Combined Scraper + Storage Example")
    print("=" * 80)

    from webScraper.scrapers.generic_scraper import GenericScraper

    # Note: This would work if you have a configured site
    # For demonstration, we'll simulate it
    print(
        "\nThis example shows how to integrate storage with your scraper workflow:"
    )
    print("""
    # After scraping
    scraper = GenericScraper(site_name="oceana")
    results = await scraper.scrape(query="illegal fishing", max_results=10)

    # Save to both JSON and SQLite
    json_storage = JSONStorage(output_dir=Path("output/json"))
    sqlite_storage = SQLiteStorage(db_path=Path("output/data.db"))

    # Save results
    await json_storage.save_batch(results)
    await sqlite_storage.save_batch(results)

    # Query and analyze
    recent_items = await sqlite_storage.search(
        start_date=datetime.now() - timedelta(days=30)
    )

    # Export for backup
    json_storage.export_to_file(Path("backup.json"))
    sqlite_storage.export_to_json(Path("db_backup.json"))
    """)


async def main():
    """Run all examples."""
    print("\n")
    print("=" * 80)
    print("WebScraper Storage Examples")
    print("=" * 80)

    # Run examples
    await example_json_storage()
    await example_json_storage_individual()
    await example_sqlite_storage()
    await example_combined_usage()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80)
    print(
        "\nCheck the 'webScraper/output' directory for generated files and databases."
    )


if __name__ == "__main__":
    asyncio.run(main())
