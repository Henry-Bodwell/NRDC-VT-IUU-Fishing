"""
JSON file storage for scraped content.

Stores scraped content as JSON files with optional indexing for search.
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
    Store scraped content as JSON files.

    Supports two modes:
    1. Single file: All content in one JSON array
    2. Individual files: Each item in a separate file
    """

    def __init__(
        self,
        output_dir: Path,
        mode: str = "single",
        filename: str = "scraped_data.json",
        pretty_print: bool = True,
    ):
        """
        Initialize JSON storage.

        Args:
            output_dir: Directory to store JSON files
            mode: Storage mode - "single" or "individual"
            filename: Filename for single file mode
            pretty_print: Whether to format JSON with indentation
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.mode = mode
        self.filename = filename
        self.pretty_print = pretty_print

        self.logger = logging.getLogger(self.__class__.__name__)

        # Index file for quick lookups
        self.index_file = self.output_dir / ".index.json"
        self.index: Dict[str, str] = self._load_index()

    def _load_index(self) -> Dict[str, str]:
        """Load the index file mapping URLs to file paths."""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Could not load index: {e}")
        return {}

    def _save_index(self) -> None:
        """Save the index file."""
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=2 if self.pretty_print else None)
        except Exception as e:
            self.logger.error(f"Could not save index: {e}")

    def _content_to_dict(self, content: ScrapedContent) -> Dict[str, Any]:
        """Convert ScrapedContent to dictionary."""
        data = asdict(content)
        # Convert datetime objects to ISO format strings
        if data.get("date"):
            data["date"] = data["date"].isoformat() if data["date"] else None
        if data.get("scraped_at"):
            data["scraped_at"] = (
                data["scraped_at"].isoformat() if data["scraped_at"] else None
            )
        return data

    def _dict_to_content(self, data: Dict[str, Any]) -> ScrapedContent:
        """Convert dictionary to ScrapedContent."""
        # Convert ISO format strings back to datetime
        if data.get("date"):
            data["date"] = (
                datetime.fromisoformat(data["date"]) if data["date"] else None
            )
        if data.get("scraped_at"):
            data["scraped_at"] = (
                datetime.fromisoformat(data["scraped_at"]) if data["scraped_at"] else None
            )
        return ScrapedContent(**data)

    def _generate_filename(self, content: ScrapedContent) -> str:
        """Generate a unique filename for individual mode."""
        # Use URL hash to create unique filename
        url_hash = hashlib.md5(content.url.encode()).hexdigest()[:12]
        # Sanitize title for filename
        safe_title = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_" for c in content.title
        )[:50]
        return f"{safe_title}_{url_hash}.json"

    async def save(self, content: ScrapedContent) -> bool:
        """Save a single scraped content item."""
        try:
            if self.mode == "individual":
                # Save to individual file
                filename = self._generate_filename(content)
                filepath = self.output_dir / filename

                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        self._content_to_dict(content),
                        f,
                        indent=2 if self.pretty_print else None,
                        ensure_ascii=False,
                    )

                # Update index
                self.index[content.url] = str(filepath)
                self._save_index()

                self.logger.info(f"Saved content to {filepath}")

            else:  # single file mode
                filepath = self.output_dir / self.filename

                # Load existing data
                existing_data = []
                if filepath.exists():
                    with open(filepath, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)

                # Check for duplicates by URL
                existing_urls = {item.get("url") for item in existing_data}
                if content.url in existing_urls:
                    self.logger.warning(
                        f"Content with URL {content.url} already exists, skipping"
                    )
                    return False

                # Append new content
                existing_data.append(self._content_to_dict(content))

                # Save all data
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        existing_data,
                        f,
                        indent=2 if self.pretty_print else None,
                        ensure_ascii=False,
                    )

                # Update index
                self.index[content.url] = str(filepath)
                self._save_index()

                self.logger.info(f"Saved content to {filepath}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to save content: {e}")
            return False

    async def save_batch(self, contents: List[ScrapedContent]) -> int:
        """Save multiple scraped content items."""
        saved_count = 0

        if self.mode == "individual":
            # Save each item individually
            for content in contents:
                if await self.save(content):
                    saved_count += 1

        else:  # single file mode
            filepath = self.output_dir / self.filename

            # Load existing data
            existing_data = []
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)

            existing_urls = {item.get("url") for item in existing_data}

            # Add new items (skip duplicates)
            for content in contents:
                if content.url not in existing_urls:
                    existing_data.append(self._content_to_dict(content))
                    self.index[content.url] = str(filepath)
                    saved_count += 1
                else:
                    self.logger.warning(
                        f"Content with URL {content.url} already exists, skipping"
                    )

            # Save all data
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        existing_data,
                        f,
                        indent=2 if self.pretty_print else None,
                        ensure_ascii=False,
                    )
                self._save_index()
                self.logger.info(f"Saved {saved_count} items to {filepath}")
            except Exception as e:
                self.logger.error(f"Failed to save batch: {e}")
                return 0

        return saved_count

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
                    if json_file.name == ".index.json":
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
                # Count JSON files (excluding index)
                return len([f for f in self.output_dir.glob("*.json") if f.name != ".index.json"])

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

    async def close(self) -> None:
        """Close any open connections or resources."""
        # JSON storage doesn't need cleanup
        pass

    def export_to_file(self, output_path: Path) -> bool:
        """
        Export all content to a single JSON file.

        Useful for consolidating individual files or creating backups.

        Args:
            output_path: Path to output file

        Returns:
            True if successful
        """
        try:
            all_data = []

            if self.mode == "individual":
                for json_file in self.output_dir.glob("*.json"):
                    if json_file.name == ".index.json":
                        continue

                    with open(json_file, "r", encoding="utf-8") as f:
                        all_data.append(json.load(f))

            else:  # single file mode
                filepath = self.output_dir / self.filename
                if filepath.exists():
                    with open(filepath, "r", encoding="utf-8") as f:
                        all_data = json.load(f)

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
