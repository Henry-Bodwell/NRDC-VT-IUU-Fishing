"""
Process scraped articles through the IUU incident extraction pipeline.

This script reads scraped_data.json and sends articles through the main DSPy
analysis pipeline to create Sources and IncidentReports via HTTP API.

Uses SQLite database to track processing status and prevent duplicate uploads.

Authentication:
    Requires a valid NextAuth JWT token from the authentication system.
    Token can be provided via:
    - --auth-token CLI argument
    - AUTH_TOKEN environment variable
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add parent directory to path for shared module
sys.path.insert(0, str(Path(__file__).parent.parent))

from urllib.parse import urlparse

from shared.pipeline_client import (
    submit_article_to_pipeline,
    ProcessingTracker,
    print_processing_stats,
)
from webScraper.config.site_config import ConfigManager


class ScraperProcessor:
    """Helper class for managing scraper article processing."""

    def __init__(self, json_file: str, db_path: str = "scraped_data/scraper.db"):
        self.json_file = json_file
        self.tracker = ProcessingTracker(
            db_path, table_name="articles", key_field="url"
        )

    def init_db(self):
        """Initialize SQLite database for tracking processing status."""
        self.tracker.init_db(
            additional_fields=[
                ("content_hash", "TEXT"),
                ("title", "TEXT"),
            ]
        )

    def import_articles(self) -> int:
        """
        Import articles from scraped_data.json into tracking database.

        Returns:
            Number of new articles imported
        """
        self.init_db()

        # Load scraped data
        with open(self.json_file, "r", encoding="utf-8") as f:
            articles = json.load(f)

        # Extract keys and additional data
        urls = []
        content_hashes = []
        titles = []

        for article in articles:
            url = article.get("url")
            if not url:
                continue

            urls.append(url)
            content_hashes.append(article.get("content_hash"))
            titles.append(article.get("title", ""))

        # Import to database
        imported = self.tracker.import_keys(
            urls,
            additional_data={
                "content_hash": content_hashes,
                "title": titles,
            },
        )

        return imported

    def get_unprocessed_articles(self, limit=None):
        """
        Get articles that haven't been processed through the pipeline yet.

        Args:
            limit: Maximum number of articles to return (None for all)

        Returns:
            List of article dicts ready for processing
        """
        # Load all articles from JSON
        with open(self.json_file, "r", encoding="utf-8") as f:
            all_articles = json.load(f)

        # Create lookup by URL
        articles_by_url = {a.get("url"): a for a in all_articles if a.get("url")}

        # Get unprocessed URLs from database
        unprocessed_urls = self.tracker.get_unprocessed_keys(limit=limit)

        # Return full article data for unprocessed URLs
        return [
            articles_by_url[url] for url in unprocessed_urls if url in articles_by_url
        ]


def get_publisher_from_config(url: str, config_manager: ConfigManager) -> str:
    """
    Get publisher name from site config by matching URL to configured sites.

    Args:
        url: Article URL
        config_manager: ConfigManager instance

    Returns:
        Publisher name from site config metadata, or domain as fallback
    """
    parsed = urlparse(url)
    domain = parsed.netloc

    # Try to match the URL domain to a configured site
    for site_name in config_manager.list_sites():
        config = config_manager.get_config(site_name)
        if config and config.base_url:
            config_domain = urlparse(config.base_url).netloc
            if domain == config_domain or domain.endswith(f".{config_domain}") or config_domain.endswith(f".{domain}"):
                # Return the name from metadata, or description, or site_name as fallback
                return config.metadata.get("name") or config.metadata.get("description") or config.site_name

    # Fallback to domain if no config match
    return domain if domain else url


def map_category_to_source_type(category: str) -> str:
    """
    Map site metadata category to GenRequest source_type.

    Args:
        category: Category from site_metadata (e.g., "Government", "NGO", "News")

    Returns:
        source_type: One of "government", "news", "industry report", "ngo", "academic", "not specified"
    """
    category_mapping = {
        "government": "government",
        "ngo": "ngo",
        "news": "news",
        "industry_journal": "industry report",
        "academic": "academic",
    }

    # Normalize category to lowercase for matching
    category_lower = category.lower() if category else ""

    # Return mapped value or default
    return category_mapping.get(category_lower, "not specified")


async def process_article(
    article_data, api_url, auth_token, tracker: ProcessingTracker, index, total, config_manager: ConfigManager
):
    """
    Process a single article and update tracking database.

    Args:
        article_data: Dict with article fields from scraped_data.json
        api_url: Base URL for the API
        auth_token: NextAuth JWT token for authentication
        tracker: ProcessingTracker instance
        index: Current article index
        total: Total articles to process
        config_manager: ConfigManager for looking up site configs

    Returns:
        Tuple of (success: bool, error_msg: str or None)
    """
    # Build payload for GenRequest
    payload = {}

    # Map scraped data fields to GenRequest format
    if article_data.get("content"):
        payload["text"] = article_data["content"]
    if article_data.get("title"):
        payload["title"] = article_data["title"]
    if article_data.get("url"):
        payload["url"] = article_data["url"]
    if article_data.get("author"):
        payload["author"] = article_data["author"]
    if article_data.get("date"):
        payload["publication_date"] = article_data["date"]

    # Set the required fields
    payload["input_name"] = "scraped"
    payload["status"] = "extracted"

    # Get publisher name from site config, with fallback to metadata or domain
    site_metadata = article_data.get("metadata", {}).get("site_metadata", {})
    publisher_name = site_metadata.get("name")
    if not publisher_name:
        # Look up from site config based on URL
        publisher_name = get_publisher_from_config(article_data["url"], config_manager)
    payload["publisher"] = publisher_name

    # Map category from metadata to source_type
    category = site_metadata.get("category")
    payload["source_type"] = map_category_to_source_type(category)

    # Submit to pipeline
    success, error_msg = await submit_article_to_pipeline(
        payload, api_url, auth_token, verbose=True
    )

    # Update tracking database
    tracker.mark_processed(article_data["url"], success=success, error_msg=error_msg)

    return (success, error_msg)


async def process_batch(
    batch_size=10,
    concurrency=3,
    api_url="http://localhost:8000",
    auth_token=None,
    db_path="scraped_data/scraper.db",
    json_file="scraped_data/scraped_data.json",
):
    """
    Process a batch of unprocessed articles with controlled concurrency.

    Args:
        batch_size: Number of articles to process in this run
        concurrency: Maximum number of concurrent requests (default: 3)
        api_url: Base URL for the API
        auth_token: NextAuth JWT token for authentication (required)
        db_path: Path to scraper SQLite database
        json_file: Path to scraped_data.json
    """
    if not auth_token:
        raise ValueError(
            "Authentication token is required. Provide via --auth-token or AUTH_TOKEN environment variable."
        )

    print(f"Authenticating with provided token...")

    # Initialize processor and config manager
    processor = ScraperProcessor(json_file, db_path)
    config_manager = ConfigManager()

    # Normalize API URL (remove trailing slash)
    api_url = api_url.rstrip("/")

    # Get unprocessed articles
    print(f"Fetching up to {batch_size} unprocessed articles...")
    articles = processor.get_unprocessed_articles(limit=batch_size)

    if not articles:
        print("No unprocessed articles found!")
        return

    print(f"Found {len(articles)} unprocessed articles")
    print(f"Using API: {api_url}")
    print(f"Concurrency: {concurrency} concurrent requests")

    # Process articles with concurrency control
    semaphore = asyncio.Semaphore(concurrency)
    stats = {"success": 0, "failed": 0}

    async def process_with_semaphore(article_data, index):
        async with semaphore:
            print(f"\n[{index}/{len(articles)}]", end=" ")
            success, _ = await process_article(
                article_data,
                api_url,
                auth_token,
                processor.tracker,
                index,
                len(articles),
                config_manager,
            )
            return success

    # Create tasks for all articles
    tasks = [
        process_with_semaphore(article_data, i + 1)
        for i, article_data in enumerate(articles)
    ]

    # Process all tasks and gather results
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Count successes and failures
    for result in results:
        if isinstance(result, Exception):
            stats["failed"] += 1
        elif result:
            stats["success"] += 1
        else:
            stats["failed"] += 1

    # Print summary
    print("\n" + "=" * 60)
    print(f"Batch processing complete:")
    print(f"  Successful: {stats['success']}")
    print(f"  Failed: {stats['failed']}")

    # Print overall stats
    overall_stats = processor.tracker.get_stats()
    print(f"\nOverall database stats:")
    print(f"  Total articles: {overall_stats['total']}")
    print(f"  Processed: {overall_stats['processed']}")
    print(f"  Unprocessed: {overall_stats['unprocessed']}")
    print(f"  Errors: {overall_stats['errors']}")


async def show_stats(db_path="scraped_data/scraper.db"):
    """Display processing statistics."""
    tracker = ProcessingTracker(db_path, table_name="articles", key_field="url")
    stats = tracker.get_stats()
    print_processing_stats(stats, source_name="Scraper Article")


def main():
    parser = argparse.ArgumentParser(
        description="Process scraped articles through IUU incident pipeline via HTTP API",
        epilog="Authentication is required. Provide token via --auth-token or AUTH_TOKEN env variable.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("scraped_data/scraped_data.json"),
        help="Path to scraped data JSON file (default: scraped_data/scraped_data.json)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of articles to process (default: 10)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Maximum concurrent requests to API (default: 3, safe range: 1-10)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL for the API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="NextAuth JWT token for authentication (or use AUTH_TOKEN env var)",
    )
    parser.add_argument(
        "--db-path",
        default="scraped_data/scraper.db",
        help="Path to scraper SQLite database (default: scraped_data/scraper.db)",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="Import articles from JSON to tracking database and exit",
    )
    parser.add_argument(
        "--stats", action="store_true", help="Just show processing statistics and exit"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all unprocessed articles (ignores --batch-size)",
    )

    args = parser.parse_args()

    # Handle --import command
    if args.do_import:
        print(f"Importing articles from {args.file} to {args.db_path}...")
        processor = ScraperProcessor(str(args.file), args.db_path)
        imported = processor.import_articles()
        print(f"Imported {imported} new articles")
        stats = processor.tracker.get_stats()
        print(f"Total articles in database: {stats['total']}")
        return

    # Handle --stats command
    if args.stats:
        asyncio.run(show_stats(db_path=args.db_path))
        return

    # Process articles
    auth_token = args.auth_token or os.getenv("AUTH_TOKEN")

    if not auth_token:
        parser.error(
            "Authentication token is required. Provide via --auth-token or set AUTH_TOKEN environment variable."
        )

    batch_size = None if args.all else args.batch_size
    asyncio.run(
        process_batch(
            batch_size=batch_size,
            concurrency=args.concurrency,
            api_url=args.api_url,
            auth_token=auth_token,
            db_path=args.db_path,
            json_file=str(args.file),
        )
    )


if __name__ == "__main__":
    main()
