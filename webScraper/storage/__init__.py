"""
Storage module for webScraper.

Provides functionality to save scraped content to various formats:
- JSON files
- SQLite database
"""

from webScraper.storage.json_storage import JSONStorage
from webScraper.storage.sqlite_storage import SQLiteStorage
from webScraper.storage.base_storage import BaseStorage

__all__ = ["JSONStorage", "SQLiteStorage", "BaseStorage"]
