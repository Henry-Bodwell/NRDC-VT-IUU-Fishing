"""
Shared client for submitting articles to the IUU incident extraction pipeline API.

This module provides reusable functions for:
- Submitting articles to the async processing pipeline
- Polling for task completion
- Handling authentication and errors
- Tracking processing with SQLite

Used by both newsapi and webscraper upload scripts.
"""

import asyncio
import aiohttp
import sqlite3
from typing import Dict, List, Optional, Tuple


async def submit_article_to_pipeline(
    article_payload: Dict,
    api_url: str,
    auth_token: str,
    max_polls: int = 120,
    poll_interval: int = 5,
    verbose: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Submit an article to the pipeline API and wait for completion.

    This function handles the full async workflow:
    1. POST /api/incidents -> returns task_id (202 Accepted)
    2. Poll GET /api/tasks/{task_id} until complete
    3. Return success/failure status

    Args:
        article_payload: Dict with fields for GenRequest (url, text, title, etc.)
        api_url: Base URL for the API (e.g., http://localhost:8000)
        auth_token: NextAuth JWT token for authentication
        max_polls: Maximum number of polling attempts (default: 120)
        poll_interval: Seconds between polls (default: 5)
        verbose: Print progress messages (default: True)

    Returns:
        Tuple of (success: bool, error_msg: str or None)
    """
    title = article_payload.get("title", "")[:100]

    if verbose:
        print(f"\nProcessing: {title}...")

    try:
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            # Step 1: Submit article for processing
            async with session.post(
                f"{api_url}/api/incidents",
                json=article_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:

                if response.status == 202:  # Accepted
                    task_data = await response.json()
                    task_id = task_data.get("task_id")

                    if not task_id:
                        error_msg = "No task_id in response"
                        if verbose:
                            print(f"  x Failed: {error_msg}")
                        return (False, error_msg)

                    if verbose:
                        print(f"  > Task created: {task_id}, polling for completion...")

                elif response.status == 401:  # Unauthorized
                    error_msg = "Authentication failed - check your auth token"
                    if verbose:
                        print(f"  x Authentication failed: Invalid or expired token")
                    return (False, error_msg)

                elif response.status == 403:  # Forbidden
                    error_msg = "Access forbidden - check user permissions"
                    if verbose:
                        print(f"  x Access forbidden: Insufficient permissions")
                    return (False, error_msg)

                elif response.status == 409:  # Conflict - already exists
                    if verbose:
                        print(f"  x Article already exists in database (duplicate)")
                    return (True, None)

                else:
                    error_text = await response.text()
                    error_msg = f"HTTP {response.status}: {error_text[:100]}"
                    if verbose:
                        print(f"  x API Error: {error_msg}")
                    return (False, error_msg)

            # Step 2: Poll for task completion
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
                        # Extract results
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
                                print(f"  x Article classified as unrelated to IUU fishing")
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
                        # Still processing, continue polling
                        if verbose and poll_count % 6 == 0:  # Print update every 30s
                            print(f"    Still processing... ({status})")
                        continue

                    else:
                        error_msg = f"Unknown task status: {status}"
                        if verbose:
                            print(f"  x {error_msg}")
                        return (False, error_msg)

            # Timeout after max_polls
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


class ProcessingTracker:
    """
    SQLite-based tracker for article processing status.

    Provides methods to:
    - Track which articles have been processed
    - Mark articles as complete/failed
    - Get processing statistics
    - Prevent duplicate processing
    """

    def __init__(self, db_path: str, table_name: str = "articles", key_field: str = "uri"):
        """
        Initialize processing tracker.

        Args:
            db_path: Path to SQLite database
            table_name: Name of the articles table (default: "articles")
            key_field: Primary key field name (default: "uri", can be "url")
        """
        self.db_path = db_path
        self.table_name = table_name
        self.key_field = key_field

    def init_db(self, additional_fields: Optional[List[Tuple[str, str]]] = None):
        """
        Initialize SQLite database with tracking schema.

        Args:
            additional_fields: List of (field_name, sql_type) tuples for extra fields
        """
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        # Build CREATE TABLE statement
        fields = [
            f"{self.key_field} TEXT PRIMARY KEY",
            "imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "processed BOOLEAN DEFAULT 0",
            "processed_at TIMESTAMP",
            "processing_error TEXT",
        ]

        if additional_fields:
            for field_name, field_type in additional_fields:
                fields.append(f"{field_name} {field_type}")

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                {', '.join(fields)}
            )
        """

        cur.execute(create_table_sql)
        con.commit()
        con.close()

    def mark_processed(self, key: str, success: bool = True, error_msg: Optional[str] = None):
        """
        Mark an article as processed.

        Args:
            key: Article identifier (URI or URL)
            success: Whether processing succeeded
            error_msg: Error message if processing failed
        """
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        cur.execute(
            f"""
            UPDATE {self.table_name}
            SET processed = ?,
                processed_at = CURRENT_TIMESTAMP,
                processing_error = ?
            WHERE {self.key_field} = ?
        """,
            (1 if success else 0, error_msg, key),
        )

        con.commit()
        con.close()

    def get_unprocessed_keys(self, limit: Optional[int] = None) -> List[str]:
        """
        Get list of unprocessed article keys.

        Args:
            limit: Maximum number of keys to return (None for all)

        Returns:
            List of article keys (URIs or URLs)
        """
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        query = f"SELECT {self.key_field} FROM {self.table_name} WHERE processed = 0 OR processed IS NULL"
        if limit:
            query += f" LIMIT {limit}"

        cur.execute(query)
        rows = cur.fetchall()
        con.close()

        return [row[self.key_field] for row in rows]

    def get_stats(self) -> Dict[str, int]:
        """
        Get processing statistics.

        Returns:
            Dict with total, processed, unprocessed, and errors counts
        """
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        cur.execute(
            f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) as processed,
                SUM(CASE WHEN processed = 0 OR processed IS NULL THEN 1 ELSE 0 END) as unprocessed,
                SUM(CASE WHEN processing_error IS NOT NULL THEN 1 ELSE 0 END) as errors
            FROM {self.table_name}
        """
        )

        row = cur.fetchone()
        con.close()

        return {
            "total": row[0] or 0,
            "processed": row[1] or 0,
            "unprocessed": row[2] or 0,
            "errors": row[3] or 0,
        }

    def import_keys(self, keys: List[str], additional_data: Optional[Dict[str, List]] = None) -> int:
        """
        Import article keys into tracking database.

        Args:
            keys: List of article keys to import
            additional_data: Dict mapping field names to lists of values (same length as keys)

        Returns:
            Number of new keys imported (excludes duplicates)
        """
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        imported = 0
        for i, key in enumerate(keys):
            try:
                # Build INSERT statement
                fields = [self.key_field]
                values = [key]

                if additional_data:
                    for field_name, field_values in additional_data.items():
                        fields.append(field_name)
                        values.append(field_values[i])

                placeholders = ", ".join(["?" for _ in fields])
                insert_sql = f"""
                    INSERT INTO {self.table_name} ({', '.join(fields)})
                    VALUES ({placeholders})
                """

                cur.execute(insert_sql, values)
                imported += 1
            except sqlite3.IntegrityError:
                # Already exists, skip
                pass

        con.commit()
        con.close()

        return imported


async def process_batch_with_concurrency(
    articles: List[Dict],
    process_func,
    concurrency: int = 3,
    show_progress: bool = True,
) -> Dict[str, int]:
    """
    Process a batch of articles with controlled concurrency.

    Args:
        articles: List of article data dicts
        process_func: Async function that processes one article and returns (success, error_msg)
        concurrency: Maximum number of concurrent requests
        show_progress: Print progress messages

    Returns:
        Dict with "success" and "failed" counts
    """
    semaphore = asyncio.Semaphore(concurrency)
    stats = {"success": 0, "failed": 0}

    async def process_with_semaphore(article_data, index):
        async with semaphore:
            if show_progress:
                print(f"\n[{index}/{len(articles)}]", end=" ")
            success, _ = await process_func(article_data, index)
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

    return stats


def print_processing_stats(stats: Dict[str, int], source_name: str = "Article"):
    """
    Print formatted processing statistics.

    Args:
        stats: Dict with total, processed, unprocessed, errors
        source_name: Name of the data source (e.g., "NewsAPI", "Scraper")
    """
    print(f"\n{source_name} Processing Statistics")
    print("=" * 60)
    print(f"Total articles imported:   {stats.get('total', 0)}")
    print(f"Processed successfully:    {stats.get('processed', 0)}")
    print(f"Not yet processed:         {stats.get('unprocessed', 0)}")
    print(f"Processing errors:         {stats.get('errors', 0)}")

    if stats.get("total", 0) > 0:
        pct = (stats.get("processed", 0) / stats["total"]) * 100
        print(f"\nProgress: {pct:.1f}% complete")
