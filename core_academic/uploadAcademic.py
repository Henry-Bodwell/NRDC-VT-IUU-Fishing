"""
Process academic papers through the IUU incident extraction pipeline.

For each record in the academic SQLite database:
- If fullText is populated, submit it as a text payload (JSON).
- Otherwise, download the PDF from downloadUrl and submit it as multipart form-data.

Metadata attached to every submission: title, authors, publishedDate, and the
first available full-text URL (sourceFulltextUrls[0] or downloadUrl).

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
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp

# Add parent directory to path for shared module
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.pipeline_client import (
    ProcessingTracker,
    print_processing_stats,
    submit_article_to_pipeline,
)

DEFAULT_DB_PATH = "core_academic/academic.db"
DEFAULT_TRACKER_DB_PATH = "core_academic/academic_upload.db"
DOWNLOAD_TIMEOUT = 60  # seconds for PDF download


class AcademicProcessor:
    """Helper class for managing academic paper processing."""

    def __init__(
        self,
        academic_db_path: str = DEFAULT_DB_PATH,
        tracker_db_path: str = DEFAULT_TRACKER_DB_PATH,
    ):
        self.academic_db_path = academic_db_path
        self.tracker = ProcessingTracker(
            tracker_db_path, table_name="academic", key_field="record_id"
        )

    def init_tracker_db(self):
        """Initialize SQLite tracking database."""
        self.tracker.init_db(
            additional_fields=[
                ("title", "TEXT"),
                ("has_full_text", "INTEGER"),
            ]
        )

    def _open_academic_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.academic_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def import_records(self) -> int:
        """
        Import records from academic.db into tracking database.

        Returns:
            Number of new records imported
        """
        self.init_tracker_db()

        conn = self._open_academic_db()
        rows = conn.execute("SELECT id, title, fullText FROM academic").fetchall()
        conn.close()

        record_ids = []
        titles = []
        has_full_texts = []

        for row in rows:
            record_ids.append(str(row["id"]))
            titles.append(row["title"] or "")
            has_full_texts.append(1 if row["fullText"] else 0)

        imported = self.tracker.import_keys(
            record_ids,
            additional_data={
                "title": titles,
                "has_full_text": has_full_texts,
            },
        )

        return imported

    def get_unprocessed_records(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get academic records that have not yet been processed.

        Args:
            limit: Maximum number of records to return (None for all)

        Returns:
            List of record dicts ready for processing
        """
        unprocessed_ids = self.tracker.get_unprocessed_keys(limit=limit)
        if not unprocessed_ids:
            return []

        conn = self._open_academic_db()
        placeholders = ", ".join("?" for _ in unprocessed_ids)
        rows = conn.execute(
            f"SELECT * FROM academic WHERE id IN ({placeholders})",
            [int(rid) for rid in unprocessed_ids],
        ).fetchall()
        conn.close()

        records = []
        for row in rows:
            d = dict(row)
            d["authors"] = json.loads(d["authors"]) if d["authors"] else []
            d["sourceFulltextUrls"] = (
                json.loads(d["sourceFulltextUrls"]) if d["sourceFulltextUrls"] else []
            )
            records.append(d)
        return records


def build_metadata(record: Dict) -> Dict:
    """
    Build shared metadata fields from an academic record.

    Returns a dict of fields suitable for inclusion in either a JSON payload
    or multipart form-data metadata fields.
    """
    meta: Dict = {
        "source_type": "academic",
        "status": "extracted",
        "input_name": "core_academic",
    }

    if record.get("title"):
        meta["title"] = record["title"]

    authors = record.get("authors") or []
    if authors:
        meta["author"] = ", ".join(str(a) for a in authors if a)

    if record.get("publishedDate"):
        meta["publication_date"] = record["publishedDate"]

    # Prefer sourceFulltextUrls[0], fall back to downloadUrl
    source_urls = record.get("sourceFulltextUrls") or []
    url = source_urls[0] if source_urls else record.get("downloadUrl")
    if url:
        meta["url"] = url

    return meta


async def submit_pdf_to_pipeline(
    pdf_bytes: bytes,
    filename: str,
    metadata: Dict,
    api_url: str,
    auth_token: str,
    max_polls: int = 120,
    poll_interval: int = 5,
    verbose: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Submit a PDF file to the pipeline API as multipart/form-data and poll until complete.

    Returns:
        Tuple of (success: bool, error_msg: str or None)
    """
    title = metadata.get("title", filename)[:100]

    if verbose:
        print(f"\nProcessing (PDF): {title}...")

    try:
        headers = {"Authorization": f"Bearer {auth_token}"}

        async with aiohttp.ClientSession(headers=headers) as session:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                pdf_bytes,
                filename=filename,
                content_type="application/pdf",
            )
            for key, value in metadata.items():
                form.add_field(key, str(value))

            async with session.post(
                f"{api_url}/api/incidents",
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status == 202:
                    task_data = await response.json()
                    task_id = task_data.get("task_id")
                    if not task_id:
                        error_msg = "No task_id in response"
                        if verbose:
                            print(f"  x Failed: {error_msg}")
                        return (False, error_msg)
                    if verbose:
                        print(f"  > Task created: {task_id}, polling for completion...")

                elif response.status == 401:
                    error_msg = "Authentication failed - check your auth token"
                    if verbose:
                        print("  x Authentication failed: Invalid or expired token")
                    return (False, error_msg)

                elif response.status == 403:
                    error_msg = "Access forbidden - check user permissions"
                    if verbose:
                        print("  x Access forbidden: Insufficient permissions")
                    return (False, error_msg)

                elif response.status == 409:
                    if verbose:
                        print("  x PDF already exists in database (duplicate)")
                    return (True, None)

                else:
                    error_text = await response.text()
                    error_msg = f"HTTP {response.status}: {error_text[:100]}"
                    if verbose:
                        print(f"  x API Error: {error_msg}")
                    return (False, error_msg)

            # Poll for task completion
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
                        if verbose:
                            print(f"  x {error_msg}")
                        return (False, error_msg)

                    task_status = await response.json()
                    status = task_status.get("status")

                    if status == "completed":
                        result = task_status.get("result", {})
                        pipeline_status = result.get("status", "unknown")
                        incidents_count = len(result.get("incidents", []))
                        has_overview = bool(result.get("industry_overview"))

                        if pipeline_status == "success":
                            if verbose:
                                print(
                                    f"    Success: {incidents_count} incidents, overview: {'yes' if has_overview else 'no'}"
                                )
                            return (True, None)
                        elif pipeline_status == "unrelated":
                            if verbose:
                                print(
                                    "  x Article classified as unrelated to IUU fishing"
                                )
                            return (True, None)
                        else:
                            error_msg = f"Pipeline status: {pipeline_status}"
                            if verbose:
                                print(f"  x Completed with status: {error_msg}")
                            return (False, error_msg)

                    elif status == "failed":
                        error = task_status.get("error", "Unknown error")
                        if verbose:
                            print(f"  x Task failed: {error}")
                        return (False, error)

                    elif status in ["pending", "processing"]:
                        if verbose and poll_count % 6 == 0:
                            print(f"    Still processing... ({status})")
                        continue

                    else:
                        error_msg = f"Unknown task status: {status}"
                        if verbose:
                            print(f"  x {error_msg}")
                        return (False, error_msg)

            error_msg = f"Task polling timeout after {max_polls * poll_interval}s"
            if verbose:
                print(f"  x Timeout: {error_msg}")
            return (False, error_msg)

    except asyncio.TimeoutError:
        error_msg = "Request timeout"
        if verbose:
            print(f"  x Timeout: {error_msg}")
        return (False, error_msg)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        if verbose:
            print(f"  x Error: {error_msg}")
        return (False, error_msg)


async def process_record(
    record: Dict,
    api_url: str,
    auth_token: str,
    tracker: ProcessingTracker,
) -> Tuple[bool, Optional[str]]:
    """
    Process a single academic record and update tracking database.

    Uses fullText if available; otherwise downloads and uploads the PDF.

    Returns:
        Tuple of (success: bool, error_msg: str or None)
    """
    record_id = str(record["id"])
    metadata = build_metadata(record)

    if record.get("fullText"):
        payload = dict(metadata)
        payload["text"] = record["fullText"]
        success, error_msg = await submit_article_to_pipeline(
            payload, api_url, auth_token, verbose=True
        )
    else:
        download_url = record.get("downloadUrl")
        if not download_url:
            error_msg = "No fullText and no downloadUrl - skipping"
            print(f"  ! {error_msg}")
            tracker.mark_processed(record_id, success=False, error_msg=error_msg)
            return (False, error_msg)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    download_url,
                    timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        error_msg = f"PDF download failed: HTTP {resp.status}"
                        print(f"  x {error_msg}")
                        tracker.mark_processed(
                            record_id, success=False, error_msg=error_msg
                        )
                        return (False, error_msg)
                    pdf_bytes = await resp.read()
        except Exception as e:
            error_msg = f"PDF download error: {type(e).__name__}: {str(e)}"
            print(f"  x {error_msg}")
            tracker.mark_processed(record_id, success=False, error_msg=error_msg)
            return (False, error_msg)

        filename = download_url.rstrip("/").split("/")[-1]
        if not filename.lower().endswith(".pdf"):
            filename = f"academic_{record_id}.pdf"

        success, error_msg = await submit_pdf_to_pipeline(
            pdf_bytes, filename, metadata, api_url, auth_token, verbose=True
        )

    tracker.mark_processed(record_id, success=success, error_msg=error_msg)
    return (success, error_msg)


async def process_batch(
    batch_size: Optional[int] = 10,
    concurrency: int = 3,
    api_url: str = "http://localhost:8000",
    auth_token: Optional[str] = None,
    academic_db_path: str = DEFAULT_DB_PATH,
    tracker_db_path: str = DEFAULT_TRACKER_DB_PATH,
):
    """
    Process a batch of unprocessed academic records with controlled concurrency.

    Args:
        batch_size: Number of records to process in this run (None for all)
        concurrency: Maximum concurrent requests (default: 3)
        api_url: Base URL for the API
        auth_token: NextAuth JWT token for authentication (required)
        academic_db_path: Path to the academic SQLite database
        tracker_db_path: Path to the upload-tracking SQLite database
    """
    if not auth_token:
        raise ValueError(
            "Authentication token is required. Provide via --auth-token or AUTH_TOKEN environment variable."
        )

    print("Authenticating with provided token...")

    processor = AcademicProcessor(academic_db_path, tracker_db_path)
    api_url = api_url.rstrip("/")

    limit_display = str(batch_size) if batch_size else "all"
    print(f"Fetching up to {limit_display} unprocessed academic records...")
    records = processor.get_unprocessed_records(limit=batch_size)

    if not records:
        print("No unprocessed academic records found!")
        return

    print(f"Found {len(records)} unprocessed records")
    print(f"Using API: {api_url}")
    print(f"Concurrency: {concurrency} concurrent requests")

    semaphore = asyncio.Semaphore(concurrency)
    stats = {"success": 0, "failed": 0}

    async def process_with_semaphore(record: Dict, index: int) -> bool:
        async with semaphore:
            print(f"\n[{index}/{len(records)}]", end=" ")
            success, _ = await process_record(
                record, api_url, auth_token, processor.tracker
            )
            return success

    tasks = [process_with_semaphore(record, i + 1) for i, record in enumerate(records)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            stats["failed"] += 1
        elif result:
            stats["success"] += 1
        else:
            stats["failed"] += 1

    print("\n" + "=" * 60)
    print("Batch processing complete:")
    print(f"  Successful: {stats['success']}")
    print(f"  Failed: {stats['failed']}")

    overall_stats = processor.tracker.get_stats()
    print("\nOverall database stats:")
    print(f"  Total records: {overall_stats['total']}")
    print(f"  Processed: {overall_stats['processed']}")
    print(f"  Unprocessed: {overall_stats['unprocessed']}")
    print(f"  Errors: {overall_stats['errors']}")


async def show_stats(tracker_db_path: str = DEFAULT_TRACKER_DB_PATH):
    """Display processing statistics."""
    tracker = ProcessingTracker(
        tracker_db_path, table_name="academic", key_field="record_id"
    )
    stats = tracker.get_stats()
    print_processing_stats(stats, source_name="Academic Paper")


def main():
    parser = argparse.ArgumentParser(
        description="Process academic papers through IUU incident pipeline via HTTP API",
        epilog="Authentication is required. Provide token via --auth-token or AUTH_TOKEN env variable.",
    )
    parser.add_argument(
        "--academic-db",
        default=DEFAULT_DB_PATH,
        help=f"Path to academic SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--tracker-db",
        default=DEFAULT_TRACKER_DB_PATH,
        help=f"Path to upload tracking database (default: {DEFAULT_TRACKER_DB_PATH})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of records to process (default: 10)",
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
        "--import",
        dest="do_import",
        action="store_true",
        help="Import records from academic.db to tracking database and exit",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show processing statistics and exit",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all unprocessed records (ignores --batch-size)",
    )

    args = parser.parse_args()

    if args.do_import:
        print(f"Importing records from {args.academic_db} to {args.tracker_db}...")
        processor = AcademicProcessor(args.academic_db, args.tracker_db)
        imported = processor.import_records()
        print(f"Imported {imported} new records")
        stats = processor.tracker.get_stats()
        print(f"Total records in tracking database: {stats['total']}")
        return

    if args.stats:
        asyncio.run(show_stats(tracker_db_path=args.tracker_db))
        return

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
            academic_db_path=args.academic_db,
            tracker_db_path=args.tracker_db,
        )
    )


if __name__ == "__main__":
    main()
