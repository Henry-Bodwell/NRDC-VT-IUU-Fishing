"""
Base storage interface for scraped content.

Defines the abstract interface that all storage implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from webScraper.scrapers.base_scraper import ScrapedContent
from datetime import datetime


class BaseStorage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    async def save(self, content: ScrapedContent) -> bool:
        """
        Save a single scraped content item.

        Args:
            content: ScrapedContent object to save

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def save_batch(self, contents: List[ScrapedContent]) -> int:
        """
        Save multiple scraped content items.

        Args:
            contents: List of ScrapedContent objects to save

        Returns:
            Number of items successfully saved
        """
        pass

    @abstractmethod
    async def get_by_url(self, url: str) -> Optional[ScrapedContent]:
        """
        Retrieve content by URL.

        Args:
            url: URL of the content to retrieve

        Returns:
            ScrapedContent if found, None otherwise
        """
        pass

    @abstractmethod
    async def search(
        self,
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[ScrapedContent]:
        """
        Search for content based on various criteria.

        Args:
            query: Text search query
            start_date: Filter by date range (start)
            end_date: Filter by date range (end)
            tags: Filter by tags
            limit: Maximum number of results

        Returns:
            List of matching ScrapedContent objects
        """
        pass

    @abstractmethod
    async def count(self) -> int:
        """
        Get total count of stored items.

        Returns:
            Number of stored items
        """
        pass

    @abstractmethod
    def has_url(self, url: str) -> bool:
        """
        Check if a URL has already been scraped.

        Args:
            url: The URL to check

        Returns:
            True if the URL exists, False otherwise
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections or resources."""
        pass
