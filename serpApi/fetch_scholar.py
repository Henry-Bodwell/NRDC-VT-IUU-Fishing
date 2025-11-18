"""
Google Scholar paper fetcher using SerpAPI.

This module handles fetching papers from Google Scholar via SerpAPI,
saving them incrementally to disk, and tracking processing status in SQLite.
"""

import sqlite3
import json
import os
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
import itertools


class ScholarFetcher:
    """Fetches Google Scholar papers via SerpAPI with SQLite tracking."""

    def __init__(self, api_key: str, db_path: str = "data/scholar.db"):
        """
        Initialize ScholarFetcher.

        Args:
            api_key: SerpAPI key
            db_path: Path to SQLite database
        """
        self.api_key = api_key
        self.db_path = db_path
        self.base_url = "https://serpapi.com/search.json"

    def _init_database(self) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
        """Initialize database with schema."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        # Create papers table with focus on PDF and author data
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                result_id TEXT PRIMARY KEY,
                title TEXT,
                authors TEXT,
                publication_year INTEGER,
                publication_info TEXT,
                pdf_link TEXT,
                pdf_source TEXT,
                main_link TEXT,
                snippet TEXT,
                cited_by_count INTEGER,
                cluster_id TEXT,
                filepath TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed BOOLEAN DEFAULT 0,
                processed_at TIMESTAMP,
                processing_error TEXT
            )
        """
        )

        con.commit()
        return con, cur

    def _save_paper_to_file(self, paper: Dict[str, Any], date: datetime) -> str:
        """
        Save paper JSON to file organized by date.

        Args:
            paper: Paper data
            date: Download date

        Returns:
            Filepath where paper was saved
        """
        # Create directory structure: data/scholar/v0.1_raw/YYYY/MM/
        base_dir = Path("data/scholar/v0.1_raw")
        year_dir = base_dir / str(date.year)
        month_dir = year_dir / f"{date.month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)

        # Save to daily file (newline-delimited JSON)
        filename = f"{date.day:02d}.json"
        filepath = month_dir / filename

        with open(filepath, "a") as f:
            f.write(json.dumps(paper) + "\n")

        return str(filepath)

    def fetch_papers(
        self,
        query: str,
        num_results: int = 100,
        start: int = 0,
        year_low: Optional[int] = None,
        year_high: Optional[int] = None,
    ) -> int:
        """
        Fetch papers from Google Scholar via SerpAPI.

        Args:
            query: Search query
            num_results: Total number of results to fetch
            start: Starting offset (for pagination)
            year_low: Minimum publication year
            year_high: Maximum publication year

        Returns:
            Number of new papers fetched
        """
        con, cur = self._init_database()

        # Check existing papers to avoid re-fetching
        cur.execute("SELECT result_id FROM papers")
        existing_ids = set(itertools.chain.from_iterable(cur.fetchall()))

        papers_fetched = 0
        current_start = start

        print(f"Fetching up to {num_results} papers for query: '{query}'")
        print(f"Already have {len(existing_ids)} papers in database")

        while papers_fetched < num_results:
            # Build API request
            params = {
                "engine": "google_scholar",
                "q": query,
                "api_key": self.api_key,
                "start": current_start,
                "num": min(20, num_results - papers_fetched),  # Max 20 per request
            }

            # Add year filters if provided
            if year_low:
                params["as_ylo"] = year_low
            if year_high:
                params["as_yhi"] = year_high

            try:
                # Make API request
                response = requests.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()

                organic_results = data.get("organic_results", [])

                if not organic_results:
                    print(f"No more results found at offset {current_start}")
                    break

                # Process each paper
                download_time = datetime.now()
                batch_new_papers = 0

                for paper in organic_results:
                    result_id = paper.get("result_id")

                    # Skip if already have this paper
                    if result_id in existing_ids:
                        continue

                    # Save to file
                    filepath = self._save_paper_to_file(paper, download_time)

                    # Extract metadata
                    title = paper.get("title", "")
                    snippet = paper.get("snippet", "")
                    main_link = paper.get("link", "")

                    pub_info = paper.get("publication_info", {})
                    pub_summary = pub_info.get("summary", "")

                    # Extract structured author data
                    authors_list = pub_info.get("authors", [])
                    if authors_list:
                        # Join author names: "Author1, Author2, Author3"
                        authors = ", ".join([a.get("name", "") for a in authors_list])
                    else:
                        # Fallback to summary if no structured authors
                        authors = pub_summary

                    # Try to extract year from summary (format: "Authors - Title, YYYY - Source")
                    year = None
                    if pub_summary:
                        import re
                        year_match = re.search(r'\b(19|20)\d{2}\b', pub_summary)
                        if year_match:
                            year = int(year_match.group(0))

                    # Extract PDF info
                    pdf_link = None
                    pdf_source = None
                    resources = paper.get("resources", [])
                    for resource in resources:
                        if resource.get("file_format") == "PDF":
                            pdf_link = resource.get("link")
                            pdf_source = resource.get("title")
                            break

                    inline_links = paper.get("inline_links", {})
                    cited_by = inline_links.get("cited_by", {})
                    cited_by_count = cited_by.get("total", 0)

                    versions = inline_links.get("versions", {})
                    cluster_id = versions.get("cluster_id", "")

                    # Insert into database
                    cur.execute(
                        """
                        INSERT INTO papers (
                            result_id, title, authors, publication_year,
                            publication_info, pdf_link, pdf_source, main_link,
                            snippet, cited_by_count, cluster_id, filepath
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            result_id,
                            title,
                            authors,
                            year,
                            pub_summary,
                            pdf_link,
                            pdf_source,
                            main_link,
                            snippet,
                            cited_by_count,
                            cluster_id,
                            filepath,
                        ),
                    )

                    existing_ids.add(result_id)
                    batch_new_papers += 1
                    papers_fetched += 1

                con.commit()
                print(f"Fetched {batch_new_papers} new papers (offset {current_start})")

                # Check if we should continue
                if papers_fetched >= num_results:
                    break

                # Move to next page
                current_start += len(organic_results)

                # Rate limiting - be respectful to API
                time.sleep(1)

            except requests.exceptions.RequestException as e:
                print(f"Error fetching papers: {e}")
                con.close()
                raise
            except Exception as e:
                print(f"Unexpected error: {e}")
                con.close()
                raise

        con.close()
        print(f"Total new papers fetched: {papers_fetched}")
        return papers_fetched

    @staticmethod
    def get_unprocessed_papers(
        limit: Optional[int] = None, db_path: str = "data/scholar.db"
    ) -> List[Dict[str, Any]]:
        """
        Get papers that haven't been processed through the pipeline yet.

        Args:
            limit: Maximum number of papers to return
            db_path: Path to SQLite database

        Returns:
            List of paper dictionaries with metadata and content
        """
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        query = """
            SELECT result_id, title, authors, publication_year,
                   publication_info, pdf_link, pdf_source, main_link,
                   snippet, cited_by_count, cluster_id, filepath
            FROM papers
            WHERE processed = 0 OR processed IS NULL
        """

        if limit:
            query += f" LIMIT {limit}"

        cur.execute(query)
        rows = cur.fetchall()
        con.close()

        papers = []
        for row in rows:
            # Read full paper data from file
            paper_data = ScholarFetcher._read_paper_from_file(
                row["filepath"], row["result_id"]
            )

            if paper_data:
                papers.append(
                    {
                        "result_id": row["result_id"],
                        "title": row["title"],
                        "authors": row["authors"],
                        "publication_year": row["publication_year"],
                        "pdf_link": row["pdf_link"],
                        "pdf_source": row["pdf_source"],
                        "main_link": row["main_link"],
                        "snippet": row["snippet"],
                        "cited_by_count": row["cited_by_count"],
                        "filepath": row["filepath"],
                        "paper": paper_data,  # Full JSON from file
                    }
                )

        return papers

    @staticmethod
    def _read_paper_from_file(
        filepath: str, result_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Read paper JSON from file by result_id.

        Args:
            filepath: Path to JSONL file
            result_id: Paper result_id to find

        Returns:
            Paper dictionary or None if not found
        """
        if not os.path.exists(filepath):
            print(f"Warning: File not found: {filepath}")
            return None

        try:
            with open(filepath, "r") as f:
                for line in f:
                    paper = json.loads(line.strip())
                    if paper.get("result_id") == result_id:
                        return paper

            print(f"Warning: Paper {result_id} not found in {filepath}")
            return None

        except Exception as e:
            print(f"Error reading paper from {filepath}: {e}")
            return None

    @staticmethod
    def mark_processed(
        result_id: str,
        success: bool = True,
        error_msg: Optional[str] = None,
        db_path: str = "data/scholar.db",
    ):
        """
        Mark a paper as processed.

        Args:
            result_id: Paper result_id
            success: Whether processing succeeded
            error_msg: Error message if processing failed
            db_path: Path to SQLite database
        """
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        cur.execute(
            """
            UPDATE papers
            SET processed = ?,
                processed_at = CURRENT_TIMESTAMP,
                processing_error = ?
            WHERE result_id = ?
        """,
            (1 if success else 0, error_msg, result_id),
        )

        con.commit()
        con.close()

    @staticmethod
    def get_processing_stats(db_path: str = "data/scholar.db") -> Dict[str, int]:
        """
        Get statistics on paper processing.

        Args:
            db_path: Path to SQLite database

        Returns:
            Dictionary with total, processed, unprocessed, errors counts
        """
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) as processed,
                SUM(CASE WHEN processed = 0 OR processed IS NULL THEN 1 ELSE 0 END) as unprocessed,
                SUM(CASE WHEN processing_error IS NOT NULL THEN 1 ELSE 0 END) as errors
            FROM papers
        """
        )

        result = cur.fetchone()
        con.close()

        return {
            "total": result[0],
            "processed": result[1] or 0,
            "unprocessed": result[2] or 0,
            "errors": result[3] or 0,
        }

    def download_pdf(
        self, result_id: str, output_dir: str = "data/scholar/pdfs"
    ) -> Optional[str]:
        """
        Download PDF for a paper if available.

        Args:
            result_id: Paper result_id
            output_dir: Directory to save PDFs

        Returns:
            Path to downloaded PDF or None if unavailable
        """
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute(
            """
            SELECT pdf_link, title, authors, publication_year
            FROM papers
            WHERE result_id = ?
        """,
            (result_id,),
        )

        row = cur.fetchone()
        con.close()

        if not row or not row["pdf_link"]:
            return None

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # Generate filename from metadata
        title_slug = "".join(c if c.isalnum() else "_" for c in row["title"][:50])
        year = row["publication_year"] or "unknown"
        filename = f"{year}_{title_slug}_{result_id}.pdf"
        filepath = os.path.join(output_dir, filename)

        # Skip if already downloaded
        if os.path.exists(filepath):
            print(f"PDF already exists: {filepath}")
            return filepath

        # Download PDF
        try:
            print(f"Downloading PDF: {row['title']}")
            response = requests.get(row["pdf_link"], timeout=30)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                f.write(response.content)

            print(f"Saved PDF: {filepath}")
            return filepath

        except Exception as e:
            print(f"Error downloading PDF: {e}")
            return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch Google Scholar papers via SerpAPI"
    )
    parser.add_argument("--api-key", help="SerpAPI key (or set SERPAPI_KEY env var)")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument(
        "--num-results", type=int, default=100, help="Number of results to fetch"
    )
    parser.add_argument("--year-low", type=int, help="Minimum publication year")
    parser.add_argument("--year-high", type=int, help="Maximum publication year")
    parser.add_argument(
        "--db-path", default="data/scholar.db", help="SQLite database path"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show processing statistics"
    )
    parser.add_argument(
        "--download-pdfs",
        action="store_true",
        help="Download PDFs for all unprocessed papers",
    )

    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv()
    # Get API key
    api_key = args.api_key or os.environ.get("SERPAPI_KEY")
    if not api_key and not args.stats:
        print("Error: Must provide --api-key or set SERPAPI_KEY environment variable")
        exit(1)

    if args.stats:
        # Show statistics
        # Check if database exists
        if not os.path.exists(args.db_path):
            print(f"\nDatabase not found at {args.db_path}")
            print("Fetch papers first to create the database.")
        else:
            stats = ScholarFetcher.get_processing_stats(args.db_path)
            print(f"\nProcessing Statistics:")
            print(f"  Total papers: {stats['total']}")
            print(f"  Processed: {stats['processed']}")
            print(f"  Unprocessed: {stats['unprocessed']}")
            print(f"  Errors: {stats['errors']}")

    elif args.download_pdfs:
        # Download PDFs for unprocessed papers
        fetcher = ScholarFetcher(api_key, args.db_path)

        # Initialize database to ensure table exists
        fetcher._init_database()

        papers = ScholarFetcher.get_unprocessed_papers(db_path=args.db_path)

        if not papers:
            print("\nNo papers found in database. Fetch papers first before downloading PDFs.")
        else:
            print(f"\nDownloading PDFs for {len(papers)} unprocessed papers...")
            downloaded = 0

            for paper in papers:
                if paper["pdf_link"]:
                    result = fetcher.download_pdf(paper["result_id"])
                    if result:
                        downloaded += 1
                    time.sleep(1)  # Rate limiting

            print(f"\nDownloaded {downloaded} PDFs")

    else:
        # Fetch papers
        fetcher = ScholarFetcher(api_key, args.db_path)
        fetcher.fetch_papers(
            query=args.query,
            num_results=args.num_results,
            year_low=args.year_low,
            year_high=args.year_high,
        )
