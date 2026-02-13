"""
JSON file storage for scraped content.

Stores scraped content as JSON files with dual deduplication:
1. URL-based deduplication (fast first check)
2. Content hash deduplication (detects same article from different URLs)
"""

import json
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import asdict
import logging

from webScraper.storage.base_storage import BaseStorage
from webScraper.scrapers.base_scraper import ScrapedContent


class JSONStorage(BaseStorage):
    """
    Store scraped content as JSON files with dual deduplication.

    Supports two modes:
    1. Single file: All content in one JSON array
    2. Individual files: Each item in a separate file

    Deduplication:
    - Checks URL first (O(1) lookup)
    - Checks content hash if enabled (detects duplicate content with different URLs)
    - Compatible with main app's article_hash system
    """

    def __init__(
        self,
        output_dir: Path,
        mode: str = "single",
        filename: str = "scraped_data.json",
        pretty_print: bool = True,
        enable_content_hash: bool = True,
    ):
        """
        Initialize JSON storage.

        Args:
            output_dir: Directory to store JSON files
            mode: Storage mode - "single" or "individual"
            filename: Filename for single file mode
            pretty_print: Whether to format JSON with indentation
            enable_content_hash: Enable content hash deduplication (in addition to URL)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.mode = mode
        self.filename = filename
        self.pretty_print = pretty_print
        self.enable_content_hash = enable_content_hash

        self.logger = logging.getLogger(self.__class__.__name__)

        # Index files for quick lookups
        self.index_file = self.output_dir / ".index.json"
        self.hash_index_file = self.output_dir / ".hash_index.json"

        # Load indexes: URL -> filepath, content_hash -> URL
        self.index: Dict[str, str] = self._load_index(self.index_file)
        self.hash_index: Dict[str, str] = (
            self._load_index(self.hash_index_file) if enable_content_hash else {}
        )

    def _load_index(self, index_path: Path) -> Dict[str, str]:
        """Load an index file mapping keys to values."""
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Could not load index {index_path.name}: {e}")
        return {}

    def _save_indexes(self) -> None:
        """Save both URL and hash index files."""
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=2 if self.pretty_print else None)

            if self.enable_content_hash:
                with open(self.hash_index_file, "w", encoding="utf-8") as f:
                    json.dump(
                        self.hash_index, f, indent=2 if self.pretty_print else None
                    )
        except Exception as e:
            self.logger.error(f"Could not save indexes: {e}")

    def _content_to_dict(self, content: ScrapedContent) -> Dict[str, Any]:
        """Convert ScrapedContent to dictionary with content_hash field."""
        data = asdict(content)
        # Convert datetime objects to ISO format strings
        if data.get("date"):
            data["date"] = data["date"].isoformat() if data["date"] else None
        if data.get("scraped_at"):
            data["scraped_at"] = (
                data["scraped_at"].isoformat() if data["scraped_at"] else None
            )

        # Add content hash for compatibility with main app's article_hash
        if self.enable_content_hash:
            data["content_hash"] = content.get_content_hash()

        return data

    def _dict_to_content(self, data: Dict[str, Any]) -> ScrapedContent:
        """Convert dictionary to ScrapedContent."""
        # Remove content_hash field (not part of ScrapedContent dataclass)
        data_copy = data.copy()
        data_copy.pop("content_hash", None)

        # Convert ISO format strings back to datetime
        if data_copy.get("date"):
            data_copy["date"] = (
                datetime.fromisoformat(data_copy["date"]) if data_copy["date"] else None
            )
        if data_copy.get("scraped_at"):
            data_copy["scraped_at"] = (
                datetime.fromisoformat(data_copy["scraped_at"])
                if data_copy["scraped_at"]
                else None
            )
        return ScrapedContent(**data_copy)

    def _is_duplicate(self, content: ScrapedContent) -> tuple[bool, Optional[str]]:
        """
        Check if content is a duplicate using URL and/or content hash.

        Args:
            content: ScrapedContent to check

        Returns:
            Tuple of (is_duplicate, reason)
            reason can be "url", "content_hash", or None
        """
        # Check URL first (fast)
        if content.url in self.index:
            return (True, "url")

        # Check content hash if enabled
        if self.enable_content_hash:
            content_hash = content.get_content_hash()
            if content_hash in self.hash_index:
                return (True, "content_hash")

        return (False, None)

    def has_url(self, url: str) -> bool:
        """
        Check if a URL has already been scraped.

        Args:
            url: The URL to check

        Returns:
            True if the URL exists in the index, False otherwise
        """
        return url in self.index

    def _generate_filename(self, content: ScrapedContent) -> str:
        """Generate a unique filename for individual mode."""
        # Use content hash to create unique filename (more meaningful than URL hash)
        if self.enable_content_hash:
            content_hash = content.get_content_hash()[:12]
        else:
            content_hash = hashlib.md5(content.url.encode()).hexdigest()[:12]

        # Sanitize title for filename
        safe_title = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_" for c in content.title
        )[:50]
        return f"{safe_title}_{content_hash}.json"

    async def save(self, content: ScrapedContent) -> bool:
        """Save a single scraped content item with deduplication."""
        try:
            # Check for duplicates
            is_dup, dup_reason = self._is_duplicate(content)
            if is_dup:
                self.logger.warning(
                    f"Duplicate content detected ({dup_reason}): {content.url}"
                )
                return False

            content_dict = self._content_to_dict(content)
            content_hash = content_dict.get("content_hash", "")

            if self.mode == "individual":
                # Save to individual file
                filename = self._generate_filename(content)
                filepath = self.output_dir / filename

                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        content_dict,
                        f,
                        indent=2 if self.pretty_print else None,
                        ensure_ascii=False,
                    )

                # Update indexes
                self.index[content.url] = str(filepath)
                if self.enable_content_hash and content_hash:
                    self.hash_index[content_hash] = content.url
                self._save_indexes()

                self.logger.info(f"Saved content to {filepath}")

            else:  # single file mode
                filepath = self.output_dir / self.filename

                # Load existing data
                existing_data = []
                if filepath.exists():
                    with open(filepath, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)

                # Append new content
                existing_data.append(content_dict)

                # Save all data
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        existing_data,
                        f,
                        indent=2 if self.pretty_print else None,
                        ensure_ascii=False,
                    )

                # Update indexes
                self.index[content.url] = str(filepath)
                if self.enable_content_hash and content_hash:
                    self.hash_index[content_hash] = content.url
                self._save_indexes()

                self.logger.info(f"Saved content to {filepath}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to save content: {e}")
            return False

    async def save_batch(self, contents: List[ScrapedContent]) -> Dict[str, Any]:
        """
        Save multiple scraped content items with deduplication.

        Returns:
            Dictionary with statistics:
            - saved: Number of new items saved
            - duplicates_url: Number of duplicates by URL
            - duplicates_content: Number of duplicates by content hash
            - total: Total items processed
        """
        stats = {
            "saved": 0,
            "duplicates_url": 0,
            "duplicates_content": 0,
            "total": len(contents),
        }

        if self.mode == "individual":
            # Save each item individually
            for content in contents:
                is_dup, dup_reason = self._is_duplicate(content)
                if is_dup:
                    if dup_reason == "url":
                        stats["duplicates_url"] += 1
                    else:
                        stats["duplicates_content"] += 1
                elif await self.save(content):
                    stats["saved"] += 1

        else:  # single file mode - batch processing for efficiency
            filepath = self.output_dir / self.filename

            # Load existing data
            existing_data = []
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)

            # Process new items
            for content in contents:
                is_dup, dup_reason = self._is_duplicate(content)
                if is_dup:
                    if dup_reason == "url":
                        stats["duplicates_url"] += 1
                    else:
                        stats["duplicates_content"] += 1
                else:
                    content_dict = self._content_to_dict(content)
                    content_hash = content_dict.get("content_hash", "")

                    existing_data.append(content_dict)

                    # Update indexes
                    self.index[content.url] = str(filepath)
                    if self.enable_content_hash and content_hash:
                        self.hash_index[content_hash] = content.url

                    stats["saved"] += 1

            # Save all data
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        existing_data,
                        f,
                        indent=2 if self.pretty_print else None,
                        ensure_ascii=False,
                    )
                self._save_indexes()

                self.logger.info(
                    f"Batch save complete: {stats['saved']} saved, "
                    f"{stats['duplicates_url']} URL duplicates, "
                    f"{stats['duplicates_content']} content duplicates"
                )
            except Exception as e:
                self.logger.error(f"Failed to save batch: {e}")
                return stats

        return stats

    async def get_by_url(self, url: str) -> Optional[ScrapedContent]:
        """Retrieve content by URL."""
        try:
            filepath = self.index.get(url)
            if not filepath:
                return None

            filepath = Path(filepath)

            if self.mode == "individual":
                if not filepath.exists():
                    return None

                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return self._dict_to_content(data)

            else:  # single file mode
                if not filepath.exists():
                    return None

                with open(filepath, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
                    for item in all_data:
                        if item.get("url") == url:
                            return self._dict_to_content(item)

            return None

        except Exception as e:
            self.logger.error(f"Failed to retrieve content: {e}")
            return None

    async def get_by_content_hash(self, content_hash: str) -> Optional[ScrapedContent]:
        """
        Retrieve content by content hash.

        This allows finding content even if the URL differs (e.g., same article
        republished on different sites).

        Args:
            content_hash: SHA256 hash of the content

        Returns:
            ScrapedContent if found, None otherwise
        """
        try:
            # Get URL from hash index
            url = self.hash_index.get(content_hash)
            if not url:
                return None

            # Fetch by URL
            return await self.get_by_url(url)

        except Exception as e:
            self.logger.error(f"Failed to retrieve content by hash: {e}")
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
            if self.mode == "individual":
                # Search through all individual files
                for json_file in self.output_dir.glob("*.json"):
                    if json_file.name.startswith("."):  # Skip index files
                        continue

                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if self._matches_criteria(
                            data, query, start_date, end_date, tags
                        ):
                            results.append(self._dict_to_content(data))

                            if limit and len(results) >= limit:
                                break

            else:  # single file mode
                filepath = self.output_dir / self.filename
                if filepath.exists():
                    with open(filepath, "r", encoding="utf-8") as f:
                        all_data = json.load(f)
                        for item in all_data:
                            if self._matches_criteria(
                                item, query, start_date, end_date, tags
                            ):
                                results.append(self._dict_to_content(item))

                                if limit and len(results) >= limit:
                                    break

        except Exception as e:
            self.logger.error(f"Search failed: {e}")

        return results

    def _matches_criteria(
        self,
        data: Dict[str, Any],
        query: Optional[str],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        tags: Optional[List[str]],
    ) -> bool:
        """Check if data matches search criteria."""
        # Text query search
        if query:
            query_lower = query.lower()
            searchable_text = (
                f"{data.get('title', '')} {data.get('content', '')} "
                f"{data.get('author', '')}"
            ).lower()
            if query_lower not in searchable_text:
                return False

        # Date range filter
        if start_date or end_date:
            date_str = data.get("date")
            if date_str:
                try:
                    item_date = datetime.fromisoformat(date_str)
                    if start_date and item_date < start_date:
                        return False
                    if end_date and item_date > end_date:
                        return False
                except (ValueError, TypeError):
                    pass

        # Tags filter
        if tags:
            item_tags = data.get("tags", [])
            if not any(tag in item_tags for tag in tags):
                return False

        return True

    async def count(self) -> int:
        """Get total count of stored items."""
        try:
            if self.mode == "individual":
                # Count JSON files (excluding index files)
                return len(
                    [
                        f
                        for f in self.output_dir.glob("*.json")
                        if not f.name.startswith(".")
                    ]
                )

            else:  # single file mode
                filepath = self.output_dir / self.filename
                if filepath.exists():
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        return len(data)
                return 0

        except Exception as e:
            self.logger.error(f"Failed to count items: {e}")
            return 0

    async def get_statistics(self) -> Dict[str, int]:
        """
        Get storage statistics.

        Returns:
            Dictionary with counts of total items, unique URLs, and unique content
        """
        return {
            "total_items": await self.count(),
            "unique_urls": len(self.index),
            "unique_content_hashes": len(self.hash_index),
        }

    async def close(self) -> None:
        """Close any open connections or resources."""
        # JSON storage doesn't need cleanup
        pass

    def export_to_file(self, output_path: Path, include_hashes: bool = True) -> bool:
        """
        Export all content to a single JSON file.

        Useful for consolidating individual files or creating backups.

        Args:
            output_path: Path to output file
            include_hashes: Include content_hash field in export

        Returns:
            True if successful
        """
        try:
            all_data = []

            if self.mode == "individual":
                for json_file in self.output_dir.glob("*.json"):
                    if json_file.name.startswith("."):  # Skip index files
                        continue

                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if not include_hashes:
                            data.pop("content_hash", None)
                        all_data.append(data)

            else:  # single file mode
                filepath = self.output_dir / self.filename
                if filepath.exists():
                    with open(filepath, "r", encoding="utf-8") as f:
                        all_data = json.load(f)
                        if not include_hashes:
                            for item in all_data:
                                item.pop("content_hash", None)

            # Write consolidated data
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(
                    all_data,
                    f,
                    indent=2 if self.pretty_print else None,
                    ensure_ascii=False,
                )

            self.logger.info(f"Exported {len(all_data)} items to {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Export failed: {e}")
            return False
