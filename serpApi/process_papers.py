"""
Process Google Scholar papers through the IUU incident analysis pipeline.

This module handles batch processing of papers fetched via SerpAPI,
sending them to the main API and tracking processing status.
"""

import asyncio
import aiohttp
import argparse
import os
from typing import Dict, Any, Tuple, Optional
from fetch_scholar import ScholarFetcher


async def process_paper(
    paper_data: Dict[str, Any],
    api_url: str,
    auth_token: Optional[str] = None,
    user_id: str = "scholar_processor"
) -> Tuple[bool, Optional[str]]:
    """
    Process a single paper through the pipeline via API.

    Args:
        paper_data: Paper metadata and content
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging

    Returns:
        Tuple of (success: bool, error_message: str or None)
    """
    result_id = paper_data["result_id"]
    title = paper_data["title"]

    # Prepare headers
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    # Determine which URL to use (prefer PDF, fallback to main link)
    url = paper_data.get("pdf_link") or paper_data.get("main_link")

    if not url:
        return (False, "No URL available (no PDF or main link)")

    # Prepare payload
    payload = {
        "url": url,
        "user_id": user_id,
        "source_type": "google_scholar",
        "metadata": {
            "result_id": result_id,
            "title": title,
            "authors": paper_data.get("authors", ""),
            "publication_year": paper_data.get("publication_year"),
            "cited_by_count": paper_data.get("cited_by_count", 0),
            "pdf_link": paper_data.get("pdf_link"),
            "pdf_source": paper_data.get("pdf_source")
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Submit to API (async task endpoint)
            async with session.post(
                f"{api_url}/api/incidents",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:

                # Handle different response codes
                if response.status == 409:
                    # Duplicate - already exists in database
                    return (True, None)  # Treat as success

                if response.status == 202:
                    # Async task created
                    task_data = await response.json()
                    task_id = task_data.get("task_id")

                    if not task_id:
                        return (False, "No task_id returned from API")

                    # Poll for task completion
                    max_polls = 60  # 5 minutes max (5 second intervals)
                    for poll_count in range(max_polls):
                        await asyncio.sleep(5)

                        async with session.get(
                            f"{api_url}/api/tasks/{task_id}",
                            headers=headers
                        ) as task_response:

                            if task_response.status != 200:
                                continue

                            task_status = await task_response.json()
                            status = task_status.get("status")

                            if status == "completed":
                                result = task_status.get("result", {})
                                if result.get("status") == "success":
                                    return (True, None)
                                else:
                                    return (False, result.get("message", "Unknown error"))

                            elif status == "failed":
                                error = task_status.get("error", "Task failed")
                                return (False, error)

                    return (False, "Task timed out after 5 minutes")

                elif response.status == 200 or response.status == 201:
                    # Synchronous success
                    result = await response.json()
                    if result.get("status") == "success":
                        return (True, None)
                    else:
                        return (False, result.get("message", "Unknown error"))

                else:
                    error_text = await response.text()
                    return (False, f"HTTP {response.status}: {error_text[:200]}")

    except asyncio.TimeoutError:
        return (False, "Request timeout")
    except aiohttp.ClientError as e:
        return (False, f"HTTP error: {str(e)}")
    except Exception as e:
        return (False, f"Unexpected error: {str(e)}")


async def process_paper_with_tracking(
    paper_data: Dict[str, Any],
    api_url: str,
    auth_token: Optional[str],
    user_id: str,
    db_path: str,
    index: int,
    total: int
) -> bool:
    """
    Wrapper to process paper and mark as processed in DB.

    Args:
        paper_data: Paper metadata
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        db_path: Path to SQLite database
        index: Current paper index (for logging)
        total: Total papers being processed

    Returns:
        True if processing succeeded
    """
    result_id = paper_data["result_id"]
    title = paper_data["title"]

    print(f"\n[{index}/{total}] Processing: {title}")
    print(f"  Result ID: {result_id}")
    print(f"  Authors: {paper_data.get('authors', 'Unknown')}")
    print(f"  Year: {paper_data.get('publication_year', 'Unknown')}")
    print(f"  PDF: {'Yes' if paper_data.get('pdf_link') else 'No'}")

    success, error_msg = await process_paper(
        paper_data, api_url, auth_token, user_id
    )

    # Mark as processed in database
    ScholarFetcher.mark_processed(
        result_id,
        success=success,
        error_msg=error_msg,
        db_path=db_path
    )

    if success:
        print(f"  ✓ Success")
    else:
        print(f"  ✗ Failed: {error_msg}")

    return success


async def process_with_semaphore(
    paper_data: Dict[str, Any],
    semaphore: asyncio.Semaphore,
    api_url: str,
    auth_token: Optional[str],
    user_id: str,
    db_path: str,
    index: int,
    total: int
) -> bool:
    """
    Process paper with concurrency control.

    Args:
        paper_data: Paper metadata
        semaphore: Asyncio semaphore for concurrency control
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        db_path: Path to SQLite database
        index: Current paper index
        total: Total papers being processed

    Returns:
        True if processing succeeded
    """
    async with semaphore:
        return await process_paper_with_tracking(
            paper_data, api_url, auth_token, user_id, db_path, index, total
        )


async def process_batch(
    batch_size: int = 10,
    concurrency: int = 3,
    api_url: str = "http://localhost:8000",
    auth_token: Optional[str] = None,
    user_id: str = "scholar_processor",
    db_path: str = "data/scholar.db"
):
    """
    Process a batch of unprocessed papers.

    Args:
        batch_size: Number of papers to process in this batch
        concurrency: Number of concurrent API requests
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        db_path: Path to SQLite database
    """
    # Get unprocessed papers
    papers = ScholarFetcher.get_unprocessed_papers(
        limit=batch_size,
        db_path=db_path
    )

    if not papers:
        print("No unprocessed papers found")
        return

    print(f"\nProcessing {len(papers)} papers with concurrency={concurrency}")
    print(f"API URL: {api_url}")

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(concurrency)

    # Process papers concurrently
    tasks = [
        process_with_semaphore(
            paper_data,
            semaphore,
            api_url,
            auth_token,
            user_id,
            db_path,
            i + 1,
            len(papers)
        )
        for i, paper_data in enumerate(papers)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Summary
    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)
    errors = sum(1 for r in results if isinstance(r, Exception))

    print(f"\n{'='*60}")
    print(f"Batch Complete:")
    print(f"  Successes: {successes}")
    print(f"  Failures: {failures}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")


async def process_all(
    concurrency: int = 3,
    api_url: str = "http://localhost:8000",
    auth_token: Optional[str] = None,
    user_id: str = "scholar_processor",
    db_path: str = "data/scholar.db"
):
    """
    Process all unprocessed papers.

    Args:
        concurrency: Number of concurrent API requests
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        db_path: Path to SQLite database
    """
    while True:
        # Get next batch
        papers = ScholarFetcher.get_unprocessed_papers(
            limit=50,  # Process in chunks of 50
            db_path=db_path
        )

        if not papers:
            print("\nAll papers processed!")
            break

        print(f"\n{'='*60}")
        print(f"Processing batch of {len(papers)} papers")
        print(f"{'='*60}")

        await process_batch(
            batch_size=len(papers),
            concurrency=concurrency,
            api_url=api_url,
            auth_token=auth_token,
            user_id=user_id,
            db_path=db_path
        )


def main():
    parser = argparse.ArgumentParser(
        description="Process Google Scholar papers through IUU incident pipeline"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of papers to process in this batch"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Number of concurrent API requests"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the API"
    )
    parser.add_argument(
        "--auth-token",
        help="Authentication token (or set API_AUTH_TOKEN env var)"
    )
    parser.add_argument(
        "--user-id",
        default="scholar_processor",
        help="User ID for audit logging"
    )
    parser.add_argument(
        "--db-path",
        default="data/scholar.db",
        help="Path to SQLite database"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all unprocessed papers"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show processing statistics"
    )

    args = parser.parse_args()

    # Get auth token
    auth_token = args.auth_token or os.environ.get("API_AUTH_TOKEN")

    if args.stats:
        # Show statistics
        stats = ScholarFetcher.get_processing_stats(args.db_path)
        print(f"\nProcessing Statistics:")
        print(f"  Total papers: {stats['total']}")
        print(f"  Processed: {stats['processed']}")
        print(f"  Unprocessed: {stats['unprocessed']}")
        print(f"  Errors: {stats['errors']}")

        if stats['total'] > 0:
            pct_processed = (stats['processed'] / stats['total']) * 100
            print(f"  Progress: {pct_processed:.1f}%")

    elif args.all:
        # Process all papers
        asyncio.run(process_all(
            concurrency=args.concurrency,
            api_url=args.api_url,
            auth_token=auth_token,
            user_id=args.user_id,
            db_path=args.db_path
        ))

    else:
        # Process batch
        asyncio.run(process_batch(
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            api_url=args.api_url,
            auth_token=auth_token,
            user_id=args.user_id,
            db_path=args.db_path
        ))


if __name__ == "__main__":
    main()
