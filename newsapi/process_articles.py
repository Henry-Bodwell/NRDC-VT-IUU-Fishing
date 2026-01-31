"""
Process fetched news articles through the IUU incident extraction pipeline.

This script reads unprocessed articles from the newsapi database and sends them
through the main DSPy analysis pipeline to create Sources and IncidentReports via HTTP API.

Authentication:
    Requires a valid NextAuth JWT token from the authentication system.
    Token can be provided via:
    - --auth-token CLI argument
    - AUTH_TOKEN environment variable
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for shared module
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.pipeline_client import (
    submit_article_to_pipeline,
    print_processing_stats,
)
from fetch_newsapi import NewsapiFetcher


async def process_article(
    article_data, api_url, auth_token, user_id="newsapi_processor"
):
    """
    Process a single article through the pipeline via API.

    Args:
        article_data: Dict with 'uri', 'filepath', and 'article' fields
        api_url: Base URL for the API (e.g., http://localhost:8000)
        auth_token: NextAuth JWT token for authentication
        user_id: User ID for audit logging (deprecated - user ID is now extracted from token)

    Returns:
        Tuple of (success: bool, error_msg: str or None)
    """
    uri = article_data["uri"]
    article = article_data["article"]

    # Extract article URL and text
    url = article.get("url")
    title = article.get("title", "")
    body = article.get("body", "")
    authors_list = article.get("authors", [])
    date = article.get("date", "")
    source_name = article.get("source", {}).get("title", "")

    print(f"\nProcessing article {uri}: {title[:60]}...")

    # Build payload for GenRequest
    payload = {}

    # Prefer URL if available, otherwise use text
    if body:
        payload["text"] = body
    if title:
        payload["title"] = title
    if url:
        payload["url"] = url
    if authors_list:
        # Extract author names from list of dicts
        author_names = [a.get("name", "") for a in authors_list if isinstance(a, dict)]
        if author_names:
            payload["author"] = ", ".join(author_names)
    if date:
        payload["publication_date"] = date
    if source_name:
        payload["publisher"] = source_name

    payload["source_type"] = "news"
    payload["status"] = "from_api"
    payload["input_name"] = "newsapi"

    # Submit to pipeline using shared client
    return await submit_article_to_pipeline(payload, api_url, auth_token, verbose=True)


async def process_article_with_tracking(
    article_data, api_url, auth_token, user_id, db_path, index, total
):
    """Wrapper to process article and mark as processed in DB."""
    print(f"\n[{index}/{total}]", end=" ")

    success, error_msg = await process_article(
        article_data, api_url, auth_token, user_id
    )

    # Mark as processed
    NewsapiFetcher.mark_processed(
        article_data["uri"], success=success, error_msg=error_msg, db_path=db_path
    )

    return success


async def process_batch(
    batch_size=10,
    concurrency=3,
    api_url="http://localhost:8000",
    auth_token=None,
    user_id="newsapi_processor",
    db_path="data/newsapi.db",
):
    """
    Process a batch of unprocessed articles with controlled concurrency.

    Args:
        batch_size: Number of articles to process in this run
        concurrency: Maximum number of concurrent requests (default: 3)
        api_url: Base URL for the API
        auth_token: NextAuth JWT token for authentication (required)
        user_id: User ID for audit logging (deprecated - extracted from token)
        db_path: Path to newsapi SQLite database
    """

    if not auth_token:
        raise ValueError(
            "Authentication token is required. Provide via --auth-token or AUTH_TOKEN environment variable."
        )

    print("Authenticating with provided token...")

    # Get unprocessed articles
    print(f"Fetching up to {batch_size} unprocessed articles...")
    articles = NewsapiFetcher.get_unprocessed_articles(
        limit=batch_size, db_path=db_path
    )

    if not articles:
        print("No unprocessed articles found!")
        return

    print(f"Found {len(articles)} unprocessed articles")
    print(f"Using API: {api_url}")
    print(f"Concurrency: {concurrency} concurrent requests")

    # Process articles with concurrency limit using semaphore
    semaphore = asyncio.Semaphore(concurrency)
    stats = {"success": 0, "failed": 0}

    async def process_with_semaphore(article_data, index):
        async with semaphore:
            success = await process_article_with_tracking(
                article_data,
                api_url,
                auth_token,
                user_id,
                db_path,
                index,
                len(articles),
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
    print("Batch processing complete:")
    print(f"  Successful: {stats['success']}")
    print(f"  Failed: {stats['failed']}")

    # Print overall stats
    overall_stats = NewsapiFetcher.get_processing_stats(db_path=db_path)
    print("\nOverall database stats:")
    print(f"  Total articles: {overall_stats['total']}")
    print(f"  Processed: {overall_stats['processed']}")
    print(f"  Unprocessed: {overall_stats['unprocessed']}")
    print(f"  Errors: {overall_stats['errors']}")


async def show_stats(db_path="data/newsapi.db"):
    """Display processing statistics."""
    stats = NewsapiFetcher.get_processing_stats(db_path=db_path)
    print_processing_stats(stats, source_name="NewsAPI Article")


def main():
    parser = argparse.ArgumentParser(
        description="Process NewsAPI articles through IUU incident pipeline via HTTP API",
        epilog="Authentication is required. Provide token via --auth-token or AUTH_TOKEN env variable.",
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
        "--user-id",
        default="newsapi_processor",
        help="(Deprecated) User ID for audit logging - now extracted from auth token",
    )
    parser.add_argument(
        "--db-path",
        default="data/newsapi.db",
        help="Path to newsapi SQLite database (default: data/newsapi.db)",
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

    if args.stats:
        asyncio.run(show_stats(db_path=args.db_path))
    else:
        # Get auth token from CLI arg or environment variable
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
                user_id=args.user_id,
                db_path=args.db_path,
            )
        )


if __name__ == "__main__":
    main()
