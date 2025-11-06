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
import aiohttp
import os
from pathlib import Path

from fetch_newsapi import NewsapiFetcher


async def process_article(
    article_data, api_url, auth_token, user_id="newsapi_processor"
):
    """
    Process a single article through the pipeline via API.

    The API uses async task processing:
    1. POST /api/incidents -> returns task_id (202 Accepted)
    2. Poll GET /api/tasks/{task_id} until complete
    3. Extract results from task.result

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

    try:
        # Prepare authorization headers
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            # Step 1: Submit article for processing
            payload = {}  # user_id no longer needed - extracted from token

            # Prefer URL if available, otherwise use text
            if body:
                payload["text"] = body
            if title:
                payload["title"] = title
            if url:
                payload["url"] = url
            if authors_list:
                # Extract author names from list of dicts
                author_names = [
                    a.get("name", "") for a in authors_list if isinstance(a, dict)
                ]
                if author_names:
                    payload["author"] = ", ".join(author_names)
            if date:
                payload["publication_date"] = date
            if source_name:
                payload["publisher"] = source_name

            payload["source_type"] = "news"
            payload["status"] = "from_api"

            # Submit task
            async with session.post(
                f"{api_url}/api/incidents",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:

                if response.status == 202:  # Accepted
                    task_data = await response.json()
                    task_id = task_data.get("task_id")

                    if not task_id:
                        error_msg = "No task_id in response"
                        print(f"  x Failed: {error_msg}")
                        return (False, error_msg)

                    print(f"  > Task created: {task_id}, polling for completion...")

                elif response.status == 401:  # Unauthorized
                    print(f"  x Authentication failed: Invalid or expired token")
                    return (False, "Authentication failed - check your auth token")

                elif response.status == 403:  # Forbidden
                    print(f"  x Access forbidden: Insufficient permissions")
                    return (False, "Access forbidden - check user permissions")

                elif response.status == 409:  # Conflict - already exists
                    print(f"  x Article already exists in database (duplicate)")
                    return (True, None)

                else:
                    error_text = await response.text()
                    error_msg = f"HTTP {response.status}: {error_text[:100]}"
                    print(f"  x API Error: {error_msg}")
                    return (False, error_msg)

            # Step 2: Poll for task completion
            max_polls = 120  # 120 polls * 5s = 10 minutes max
            poll_interval = 5  # seconds

            for poll_count in range(max_polls):
                await asyncio.sleep(poll_interval)

                async with session.get(
                    f"{api_url}/api/tasks/{task_id}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:

                    if response.status != 200:
                        error_msg = (
                            f"Failed to fetch task status: HTTP {response.status}"
                        )
                        print(f"  x {error_msg}")
                        return (False, error_msg)

                    task_status = await response.json()
                    status = task_status.get("status")

                    if status == "completed":
                        # Extract results
                        result = task_status.get("result", {})
                        pipeline_status = result.get("status", "unknown")
                        incidents_count = len(result.get("incidents", []))
                        has_overview = bool(result.get("industry_overview"))

                        if pipeline_status == "success":
                            print(
                                f"    Success: {incidents_count} incidents, overview: {'yes' if has_overview else 'no'}"
                            )
                            return (True, None)
                        elif pipeline_status == "unrelated":
                            print(f"  x Article classified as unrelated to IUU fishing")
                            return (True, None)
                        else:
                            error_msg = f"Pipeline status: {pipeline_status}"
                            print(f"  x Completed with status: {error_msg}")
                            return (False, error_msg)

                    elif status == "failed":
                        error = task_status.get("error", "Unknown error")
                        print(f"  x Task failed: {error}")
                        return (False, error)

                    elif status in ["pending", "processing"]:
                        # Still processing, continue polling
                        progress = task_status.get("progress", {})
                        if poll_count % 6 == 0:  # Print update every 30s
                            print(f"    Still processing... ({status})")
                        continue

                    else:
                        error_msg = f"Unknown task status: {status}"
                        print(f"  x {error_msg}")
                        return (False, error_msg)

            # Timeout after max_polls
            error_msg = f"Task polling timeout after {max_polls * poll_interval}s"
            print(f"  x Timeout: {error_msg}")
            return (False, error_msg)

    except asyncio.TimeoutError:
        error_msg = "Request timeout"
        print(f"  x Timeout: {error_msg}")
        return (False, error_msg)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"  x Error: {error_msg}")
        return (False, error_msg)


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

    print(f"Authenticating with provided token...")

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
    print(f"Batch processing complete:")
    print(f"  Successful: {stats['success']}")
    print(f"  Failed: {stats['failed']}")

    # Print overall stats
    overall_stats = NewsapiFetcher.get_processing_stats(db_path=db_path)
    print(f"\nOverall database stats:")
    print(f"  Total articles: {overall_stats['total']}")
    print(f"  Processed: {overall_stats['processed']}")
    print(f"  Unprocessed: {overall_stats['unprocessed']}")
    print(f"  Errors: {overall_stats['errors']}")


async def show_stats(db_path="data/newsapi.db"):
    """Display processing statistics."""
    stats = NewsapiFetcher.get_processing_stats(db_path=db_path)

    print("NewsAPI Article Processing Statistics")
    print("=" * 60)
    print(f"Total articles downloaded: {stats['total']}")
    print(f"Processed successfully:    {stats['processed']}")
    print(f"Not yet processed:         {stats['unprocessed']}")
    print(f"Processing errors:         {stats['errors']}")

    if stats["total"] > 0:
        pct = (stats["processed"] / stats["total"]) * 100
        print(f"\nProgress: {pct:.1f}% complete")


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
