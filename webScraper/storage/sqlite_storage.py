"""
SQLite database storage for scraped content.

Provides persistent storage with indexing and efficient querying capabilities.
"""

import sqlite3
import json
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import asdict
import logging

from webScraper.storage.base_storage import BaseStorage
from webScraper.scrapers.base_scraper import ScrapedContent


class SQLiteStorage(BaseStorage):
    """
    Store scraped content in a SQLite database.

    Schema:
    - scraped_content: Main table with all content
    - tags: Separate table for tags (many-to-many relationship)
    - Full-text search enabled on title and content
    """

    def __init__(self, db_path: Path, enable_fts: bool = True):
        """
        Initialize SQLite storage.

        Args:
            db_path: Path to SQLite database file
            enable_fts: Enable full-text search (FTS5)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.enable_fts = enable_fts
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize database
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        cursor = self.conn.cursor()

        # Main content table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scraped_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                url_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                date TEXT,
                author TEXT,
                scraped_at TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Tags table (many-to-many)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                FOREIGN KEY (content_id) REFERENCES scraped_content(id) ON DELETE CASCADE,
                UNIQUE(content_id, tag)
            )
        """
        )

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_url_hash ON scraped_content(url_hash)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON scraped_content(date)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_author ON scraped_content(author)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_scraped_at ON scraped_content(scraped_at)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)")

        # Full-text search virtual table
        if self.enable_fts:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS scraped_content_fts
                USING fts5(
                    title,
                    content,
                    author,
                    content='scraped_content',
                    content_rowid='id'
                )
            """
            )

            # Triggers to keep FTS table in sync
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS scraped_content_ai
                AFTER INSERT ON scraped_content BEGIN
                    INSERT INTO scraped_content_fts(rowid, title, content, author)
                    VALUES (new.id, new.title, new.content, new.author);
                END
            """
            )

            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS scraped_content_ad
                AFTER DELETE ON scraped_content BEGIN
                    DELETE FROM scraped_content_fts WHERE rowid = old.id;
                END
            """
            )

            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS scraped_content_au
                AFTER UPDATE ON scraped_content BEGIN
                    UPDATE scraped_content_fts
                    SET title = new.title, content = new.content, author = new.author
                    WHERE rowid = new.id;
                END
            """
            )

        self.conn.commit()
        self.logger.info(f"Database initialized at {self.db_path}")

    def _content_to_row(self, content: ScrapedContent) -> Dict[str, Any]:
        """Convert ScrapedContent to database row."""
        url_hash = hashlib.sha256(content.url.encode()).hexdigest()

        return {
            "url": content.url,
            "url_hash": url_hash,
            "title": content.title,
            "content": content.content,
            "date": content.date.isoformat() if content.date else None,
            "author": content.author,
            "scraped_at": (
                content.scraped_at.isoformat()
                if content.scraped_at
                else datetime.now().isoformat()
            ),
            "metadata": json.dumps(content.metadata) if content.metadata else None,
        }

    def _row_to_content(self, row: sqlite3.Row) -> ScrapedContent:
        """Convert database row to ScrapedContent."""
        # Get tags for this content
        cursor = self.conn.cursor()
        cursor.execute("SELECT tag FROM tags WHERE content_id = ?", (row["id"],))
        tags = [tag_row["tag"] for tag_row in cursor.fetchall()]

        return ScrapedContent(
            url=row["url"],
            title=row["title"],
            content=row["content"],
            date=datetime.fromisoformat(row["date"]) if row["date"] else None,
            author=row["author"],
            tags=tags if tags else None,
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            scraped_at=(
                datetime.fromisoformat(row["scraped_at"]) if row["scraped_at"] else None
            ),
        )

    async def save(self, content: ScrapedContent) -> bool:
        """Save a single scraped content item."""
        try:
            cursor = self.conn.cursor()
            row_data = self._content_to_row(content)

            # Insert or replace content
            cursor.execute(
                """
                INSERT OR REPLACE INTO scraped_content
                (url, url_hash, title, content, date, author, scraped_at, metadata)
                VALUES (:url, :url_hash, :title, :content, :date, :author, :scraped_at, :metadata)
            """,
                row_data,
            )

            content_id = cursor.lastrowid

            # Insert tags
            if content.tags:
                cursor.execute("DELETE FROM tags WHERE content_id = ?", (content_id,))
                for tag in content.tags:
                    cursor.execute(
                        "INSERT OR IGNORE INTO tags (content_id, tag) VALUES (?, ?)",
                        (content_id, tag),
                    )

            self.conn.commit()
            self.logger.info(f"Saved content: {content.url}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save content: {e}")
            self.conn.rollback()
            return False

    async def save_batch(self, contents: List[ScrapedContent]) -> int:
        """Save multiple scraped content items."""
        saved_count = 0

        try:
            cursor = self.conn.cursor()

            for content in contents:
                try:
                    row_data = self._content_to_row(content)

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO scraped_content
                        (url, url_hash, title, content, date, author, scraped_at, metadata)
                        VALUES (:url, :url_hash, :title, :content, :date, :author, :scraped_at, :metadata)
                    """,
                        row_data,
                    )

                    content_id = cursor.lastrowid

                    # Insert tags
                    if content.tags:
                        cursor.execute(
                            "DELETE FROM tags WHERE content_id = ?", (content_id,)
                        )
                        for tag in content.tags:
                            cursor.execute(
                                "INSERT OR IGNORE INTO tags (content_id, tag) VALUES (?, ?)",
                                (content_id, tag),
                            )

                    saved_count += 1

                except Exception as e:
                    self.logger.warning(f"Failed to save item {content.url}: {e}")
                    continue

            self.conn.commit()
            self.logger.info(f"Saved {saved_count}/{len(contents)} items")
            return saved_count

        except Exception as e:
            self.logger.error(f"Batch save failed: {e}")
            self.conn.rollback()
            return saved_count

    async def get_by_url(self, url: str) -> Optional[ScrapedContent]:
        """Retrieve content by URL."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM scraped_content WHERE url = ?",
                (url,),
            )
            row = cursor.fetchone()

            if row:
                return self._row_to_content(row)
            return None

        except Exception as e:
            self.logger.error(f"Failed to retrieve content: {e}")
            return None

    async def search(
        self,
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[ScrapedContent]:
        """Search for content based on various criteria."""
        results = []

        try:
            cursor = self.conn.cursor()

            # Build query
            if query and self.enable_fts:
                # Use full-text search
                sql = """
                    SELECT sc.* FROM scraped_content sc
                    JOIN scraped_content_fts fts ON sc.id = fts.rowid
                    WHERE scraped_content_fts MATCH ?
                """
                params = [query]
            else:
                # Regular search
                sql = "SELECT * FROM scraped_content WHERE 1=1"
                params = []

                if query:
                    sql += " AND (title LIKE ? OR content LIKE ? OR author LIKE ?)"
                    search_term = f"%{query}%"
                    params.extend([search_term, search_term, search_term])

            # Add date filters
            if start_date:
                sql += " AND date >= ?"
                params.append(start_date.isoformat())

            if end_date:
                sql += " AND date <= ?"
                params.append(end_date.isoformat())

            # Add tag filter
            if tags:
                placeholders = ",".join("?" * len(tags))
                sql += f"""
                    AND id IN (
                        SELECT content_id FROM tags
                        WHERE tag IN ({placeholders})
                    )
                """
                params.extend(tags)

            # Add limit
            if limit:
                sql += " LIMIT ?"
                params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            for row in rows:
                results.append(self._row_to_content(row))

        except Exception as e:
            self.logger.error(f"Search failed: {e}")

        return results

    async def count(self) -> int:
        """Get total count of stored items."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM scraped_content")
            row = cursor.fetchone()
            return row["count"] if row else 0

        except Exception as e:
            self.logger.error(f"Failed to count items: {e}")
            return 0

    def has_url(self, url: str) -> bool:
        """
        Check if a URL has already been scraped.

        Args:
            url: The URL to check

        Returns:
            True if the URL exists in the database, False otherwise
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT 1 FROM scraped_content WHERE url = ? LIMIT 1",
                (url,),
            )
            return cursor.fetchone() is not None
        except Exception as e:
            self.logger.error(f"Failed to check URL: {e}")
            return False

    async def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.logger.info("Database connection closed")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with various statistics
        """
        try:
            cursor = self.conn.cursor()

            # Total count
            cursor.execute("SELECT COUNT(*) as count FROM scraped_content")
            total_count = cursor.fetchone()["count"]

            # Date range
            cursor.execute(
                "SELECT MIN(date) as min_date, MAX(date) as max_date FROM scraped_content"
            )
            date_range = cursor.fetchone()

            # Top authors
            cursor.execute(
                """
                SELECT author, COUNT(*) as count
                FROM scraped_content
                WHERE author IS NOT NULL
                GROUP BY author
                ORDER BY count DESC
                LIMIT 10
            """
            )
            top_authors = [
                {"author": row["author"], "count": row["count"]}
                for row in cursor.fetchall()
            ]

            # Top tags
            cursor.execute(
                """
                SELECT tag, COUNT(*) as count
                FROM tags
                GROUP BY tag
                ORDER BY count DESC
                LIMIT 10
            """
            )
            top_tags = [
                {"tag": row["tag"], "count": row["count"]} for row in cursor.fetchall()
            ]

            # Database size
            cursor.execute(
                "SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()"
            )
            db_size = cursor.fetchone()["size"]

            return {
                "total_items": total_count,
                "earliest_date": date_range["min_date"],
                "latest_date": date_range["max_date"],
                "top_authors": top_authors,
                "top_tags": top_tags,
                "database_size_bytes": db_size,
                "database_path": str(self.db_path),
            }

        except Exception as e:
            self.logger.error(f"Failed to get statistics: {e}")
            return {}

    def export_to_json(self, output_path: Path) -> bool:
        """
        Export entire database to JSON file.

        Args:
            output_path: Path to output JSON file

        Returns:
            True if successful
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM scraped_content")
            rows = cursor.fetchall()

            data = []
            for row in rows:
                content = self._row_to_content(row)
                content_dict = asdict(content)
                # Convert datetime to ISO format
                if content_dict.get("date"):
                    content_dict["date"] = (
                        content_dict["date"].isoformat()
                        if content_dict["date"]
                        else None
                    )
                if content_dict.get("scraped_at"):
                    content_dict["scraped_at"] = (
                        content_dict["scraped_at"].isoformat()
                        if content_dict["scraped_at"]
                        else None
                    )
                data.append(content_dict)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Exported {len(data)} items to {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Export failed: {e}")
            return False

    def vacuum(self) -> bool:
        """
        Optimize database by running VACUUM.

        Reclaims unused space and optimizes the database file.

        Returns:
            True if successful
        """
        try:
            self.conn.execute("VACUUM")
            self.logger.info("Database vacuumed successfully")
            return True
        except Exception as e:
            self.logger.error(f"Vacuum failed: {e}")
            return False
