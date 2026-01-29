"""
Process Google Scholar papers through the IUU incident analysis pipeline.

This module handles batch processing of papers fetched via SerpAPI,
sending them to the main API and tracking processing status.
"""

import asyncio
import aiohttp
import argparse
import os
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from fetch_scholar import ScholarFetcher


def find_local_pdf(
    result_id: str, pdf_dir: str = "data/scholar/pdfs"
) -> Optional[Path]:
    """
    Find a local PDF file by result_id.

    PDF filenames end with the result_id before the extension.
    Example: "2024_Some_Title_abc123xyz.pdf" for result_id "abc123xyz"

    Args:
        result_id: The Google Scholar result_id
        pdf_dir: Directory containing PDFs

    Returns:
        Path to PDF file if found, None otherwise
    """
    pdf_path = Path(pdf_dir)
    if not pdf_path.exists():
        return None

    # Look for files ending with result_id.pdf
    pattern = f"*_{result_id}.pdf"
    matches = list(pdf_path.glob(pattern))

    if matches:
        return matches[0]  # Return first match

    return None


async def download_pdf(
    url: str, session: aiohttp.ClientSession, max_size_mb: int = 50
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Download PDF from URL.

    Args:
        url: URL to download from
        session: aiohttp session
        max_size_mb: Maximum file size in MB

    Returns:
        Tuple of (pdf_bytes: bytes or None, error_message: str or None)
    """
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=60)
        ) as response:
            if response.status != 200:
                return (None, f"Failed to download PDF: HTTP {response.status}")

            # Check content type
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                return (
                    None,
                    f"URL does not point to a PDF (Content-Type: {content_type})",
                )

            # Check content length
            content_length = response.headers.get("Content-Length")
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > max_size_mb:
                    return (
                        None,
                        f"PDF too large: {size_mb:.1f}MB (max {max_size_mb}MB)",
                    )

            # Download PDF
            pdf_bytes = await response.read()

            # Verify size after download
            size_mb = len(pdf_bytes) / (1024 * 1024)
            if size_mb > max_size_mb:
                return (None, f"PDF too large: {size_mb:.1f}MB (max {max_size_mb}MB)")

            if len(pdf_bytes) < 100:
                return (None, "PDF appears to be empty or corrupted")

            return (pdf_bytes, None)

    except asyncio.TimeoutError:
        return (None, "PDF download timeout")
    except aiohttp.ClientError as e:
        return (None, f"Download error: {str(e)}")
    except Exception as e:
        return (None, f"Unexpected download error: {str(e)}")


async def process_paper(
    paper_data: Dict[str, Any],
    api_url: str,
    auth_token: Optional[str] = None,
    user_id: str = "scholar_processor",
    pdf_dir: str = "data/scholar/pdfs",
) -> Tuple[bool, Optional[str]]:
    """
    Process a single paper through the pipeline via API by uploading PDF.

    Process flow:
    1. Get metadata from paper_data (from SQLite database)
    2. Try to find local PDF file by result_id
    3. If not found, download from pdf_link in metadata
    4. Upload PDF to API with metadata

    Args:
        paper_data: Paper metadata from SQLite (includes result_id, title, pdf_link, etc.)
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        pdf_dir: Directory containing local PDFs

    Returns:
        Tuple of (success: bool, error_message: str or None)
    """
    result_id = paper_data["result_id"]
    title = paper_data["title"]

    pdf_bytes = None
    pdf_source_description = ""

    # Step 1: Try to find local PDF
    local_pdf_path = find_local_pdf(result_id, pdf_dir)

    if local_pdf_path and local_pdf_path.exists():
        try:
            pdf_bytes = local_pdf_path.read_bytes()

            # Validate size
            size_mb = len(pdf_bytes) / (1024 * 1024)
            if size_mb > 50:
                return (False, f"Local PDF too large: {size_mb:.1f}MB (max 50MB)")

            pdf_source_description = f"local file: {local_pdf_path.name}"

        except Exception as e:
            # If local read fails, try downloading
            print(f"  ⚠ Warning: Failed to read local PDF: {e}")
            pdf_bytes = None

    # Step 2: If no local PDF, download from pdf_link
    if not pdf_bytes:
        pdf_url = paper_data.get("pdf_link")

        if not pdf_url:
            return (
                False,
                "No PDF available (no local file and no pdf_link in database)",
            )

        try:
            async with aiohttp.ClientSession() as session:
                pdf_bytes, download_error = await download_pdf(pdf_url, session)

                if download_error:
                    return (False, f"Download failed: {download_error}")

                if not pdf_bytes:
                    return (False, "Failed to download PDF")

                pdf_source_description = f"downloaded from URL"
        except Exception as e:
            return (False, f"Download error: {str(e)}")

    # At this point, we should have pdf_bytes
    if not pdf_bytes:
        return (False, "Failed to obtain PDF")

    print(f"  📄 PDF source: {pdf_source_description}")

    # Step 3: Upload PDF to API
    try:
        async with aiohttp.ClientSession() as session:

            # Prepare headers
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"

            # Create multipart form data
            form = aiohttp.FormData()
            form.add_field(
                "file",
                pdf_bytes,
                filename=f"{title}.pdf",
                content_type="application/pdf",
            )

            # Add metadata fields
            if title:
                form.add_field("title", title)

            if paper_data.get("authors"):
                # Extract just author names from authors field
                # Format is typically: "Authors - Journal, Year - Publisher"
                authors_info = paper_data["authors"]
                # Authors are the first part before the first " - "
                author_names = authors_info.split(" - ")[0].strip() if " - " in authors_info else authors_info
                form.add_field("author", author_names)

            if paper_data.get("publication_info"):
                # Extract publisher from publication_info
                # Format is typically: "Authors - Journal, Year - Publisher"
                pub_info = paper_data["publication_info"]
                # Publisher is usually the last part after the final " - "
                parts = pub_info.split(" - ")
                publisher = parts[-1].strip() if len(parts) > 1 else pub_info
                form.add_field("publisher", publisher)

            if paper_data.get("publication_year"):
                # Convert year to ISO datetime format (use January 1st of that year)
                from datetime import datetime
                year = paper_data["publication_year"]
                publication_date = datetime(year, 1, 1).isoformat() + "Z"
                form.add_field("publication_date", publication_date)

            # Mark as academic source from API
            form.add_field("source_type", "academic")
            form.add_field("status", "from_api")

            # Optional: Add the main link as URL if available
            if paper_data.get("main_link"):
                form.add_field("url", paper_data["main_link"])

            # Add input_name to identify this as from Google Scholar
            form.add_field("input_name", f"google_scholar_{result_id}")

            # Submit to API (async task endpoint)
            async with session.post(
                f"{api_url}/api/incidents",
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
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
                            f"{api_url}/api/tasks/{task_id}", headers=headers
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
                                    return (
                                        False,
                                        result.get("message", "Unknown error"),
                                    )

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
    pdf_dir: str,
    index: int,
    total: int,
) -> bool:
    """
    Wrapper to process paper and mark as processed in DB.

    Args:
        paper_data: Paper metadata
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        db_path: Path to SQLite database
        pdf_dir: Directory containing local PDFs
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
    print(f"  Publisher: {paper_data.get('publication_info', 'Unknown')}")
    print(f"  PDF link: {'Yes' if paper_data.get('pdf_link') else 'No'}")
    print(f"  Main link: {paper_data.get('main_link', 'N/A')}")

    success, error_msg = await process_paper(
        paper_data, api_url, auth_token, user_id, pdf_dir
    )

    # Mark as processed in database
    ScholarFetcher.mark_processed(
        result_id, success=success, error_msg=error_msg, db_path=db_path
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
    pdf_dir: str,
    index: int,
    total: int,
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
        pdf_dir: Directory containing local PDFs
        index: Current paper index
        total: Total papers being processed

    Returns:
        True if processing succeeded
    """
    async with semaphore:
        return await process_paper_with_tracking(
            paper_data, api_url, auth_token, user_id, db_path, pdf_dir, index, total
        )


async def process_batch(
    batch_size: int = 10,
    concurrency: int = 3,
    api_url: str = "http://localhost:8000",
    auth_token: Optional[str] = None,
    user_id: str = "scholar_processor",
    db_path: str = "data/scholar.db",
    pdf_dir: str = "data/scholar/pdfs",
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
        pdf_dir: Directory containing local PDFs
    """
    # Get unprocessed papers
    papers = ScholarFetcher.get_unprocessed_papers(limit=batch_size, db_path=db_path)

    if not papers:
        print("No unprocessed papers found")
        return

    print(f"\nProcessing {len(papers)} papers with concurrency={concurrency}")
    print(f"API URL: {api_url}")
    print(f"PDF directory: {pdf_dir}")

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
            pdf_dir,
            i + 1,
            len(papers),
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
    db_path: str = "data/scholar.db",
    pdf_dir: str = "data/scholar/pdfs",
):
    """
    Process all unprocessed papers.

    Args:
        concurrency: Number of concurrent API requests
        api_url: Base URL of the API
        auth_token: Optional authentication token
        user_id: User ID for audit logging
        db_path: Path to SQLite database
        pdf_dir: Directory containing local PDFs
    """
    while True:
        # Get next batch
        papers = ScholarFetcher.get_unprocessed_papers(
            limit=50, db_path=db_path  # Process in chunks of 50
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
            db_path=db_path,
            pdf_dir=pdf_dir,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Process Google Scholar papers through IUU incident pipeline"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of papers to process in this batch",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3, help="Number of concurrent API requests"
    )
    parser.add_argument(
        "--api-url", default="http://localhost:8000", help="Base URL of the API"
    )
    parser.add_argument(
        "--auth-token", help="Authentication token (or set API_AUTH_TOKEN env var)"
    )
    parser.add_argument(
        "--user-id", default="scholar_processor", help="User ID for audit logging"
    )
    parser.add_argument(
        "--db-path", default="data/scholar.db", help="Path to SQLite database"
    )
    parser.add_argument(
        "--pdf-dir",
        default="data/scholar/pdfs",
        help="Directory containing local PDFs",
    )
    parser.add_argument(
        "--all", action="store_true", help="Process all unprocessed papers"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show processing statistics"
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

        if stats["total"] > 0:
            pct_processed = (stats["processed"] / stats["total"]) * 100
            print(f"  Progress: {pct_processed:.1f}%")

    elif args.all:
        # Process all papers
        asyncio.run(
            process_all(
                concurrency=args.concurrency,
                api_url=args.api_url,
                auth_token=auth_token,
                user_id=args.user_id,
                db_path=args.db_path,
                pdf_dir=args.pdf_dir,
            )
        )

    else:
        # Process batch
        asyncio.run(
            process_batch(
                batch_size=args.batch_size,
                concurrency=args.concurrency,
                api_url=args.api_url,
                auth_token=auth_token,
                user_id=args.user_id,
                db_path=args.db_path,
                pdf_dir=args.pdf_dir,
            )
        )


if __name__ == "__main__":
    main()
