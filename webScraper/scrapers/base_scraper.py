"""
Base scraper module providing the foundation for all site-specific scrapers.

This module implements the Template Method pattern, defining the scraping workflow
while allowing site-specific implementations to override specific steps.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio
import logging
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from enum import Enum
from webScraper.config.site_config import SiteConfig


class ScraperStatus(Enum):
    """Enumeration of possible scraper statuses."""

    INITIALIZING = "initializing"
    NAVIGATING = "navigating"
    SEARCHING = "searching"
    EXTRACTING_LINKS = "extracting_links"
    SCRAPING_DETAILS = "scraping_details"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SearchResult:
    """Data class representing a search result link."""

    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ScrapedContent:
    """Data class representing scraped content from a detail page."""

    url: str
    title: str
    content: str
    date: Optional[datetime] = None
    author: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    scraped_at: datetime = None

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now()


class BaseScraper(ABC):
    """
    Abstract base class for all site-specific scrapers.

    Implements the Template Method pattern where the workflow is defined here,
    but specific steps are implemented by subclasses.
    """

    def __init__(
        self,
        site_config: Optional["SiteConfig"] = None,
        headless: bool = True,
        timeout: int = 30000,
        user_agent: Optional[str] = None,
        viewport: Dict[str, int] = None,
        max_retries: int = 3,
        delay_range: tuple = (1, 3),
    ):
        """
        Initialize the base scraper.

        Args:
            site_config: SiteConfig instance with site-specific settings
            headless: Run browser in headless mode
            timeout: Default timeout in milliseconds
            user_agent: Custom user agent string
            viewport: Browser viewport size {'width': 1280, 'height': 720}
            max_retries: Maximum number of retry attempts for failed operations
            delay_range: Tuple of (min, max) seconds for random delays
        """
        self.site_config = site_config

        # Use config values if available, otherwise use parameters or defaults
        if site_config:
            self.delay_range = site_config.rate_limit.delay_range
        else:
            self.delay_range = delay_range

        self.max_retries = max_retries
        self.headless = headless
        self.timeout = timeout
        self.user_agent = user_agent or self._get_default_user_agent()
        self.viewport = viewport or {"width": 1280, "height": 720}

        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.status = ScraperStatus.INITIALIZING

        self.logger = self._setup_logger()
        self.results: List[ScrapedContent] = []

    def _setup_logger(self) -> logging.Logger:
        """Setup logger for this scraper instance."""
        logger = logging.getLogger(self.__class__.__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def _get_default_user_agent(self) -> str:
        """Return a default user agent string."""
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    async def _init_browser(self) -> None:
        """Initialize Playwright browser and context."""
        self.logger.info("Initializing browser...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            user_agent=self.user_agent, viewport=self.viewport
        )
        self.context.set_default_timeout(self.timeout)
        self.page = await self.context.new_page()
        self.logger.info("Browser initialized successfully")

    async def _cleanup(self) -> None:
        """Cleanup browser resources."""
        self.logger.info("Cleaning up browser resources...")
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright"):
            await self.playwright.stop()
        self.logger.info("Cleanup completed")

    async def _random_delay(self) -> None:
        """Add a random delay to appear more human-like."""
        import random

        delay = random.uniform(self.delay_range[0], self.delay_range[1])
        self.logger.debug(f"Waiting {delay:.2f} seconds...")
        await asyncio.sleep(delay)

    async def _retry_operation(self, operation, *args, **kwargs):
        """
        Retry an async operation with exponential backoff.

        Args:
            operation: Async function to retry
            *args, **kwargs: Arguments to pass to the operation

        Returns:
            Result of the operation

        Raises:
            Exception: If all retries fail
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_exception = e
                wait_time = 2**attempt  # Exponential backoff
                self.logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries} failed: {str(e)}. "
                    f"Retrying in {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)

        self.logger.error(f"All {self.max_retries} attempts failed")
        raise last_exception

    # Abstract methods that must be implemented by subclasses

    @abstractmethod
    async def navigate_to_search(self) -> None:
        """
        Navigate to the search page.

        Must be implemented by subclasses to navigate to the site-specific
        search page.
        """
        pass

    @abstractmethod
    async def submit_query(self, query: str) -> None:
        """
        Submit a search query.

        Args:
            query: The search term or query string

        Must be implemented by subclasses to handle site-specific search
        form submission.
        """
        pass

    @abstractmethod
    async def extract_result_links(self) -> List[SearchResult]:
        """
        Extract result links from the search results page.

        Returns:
            List of SearchResult objects containing URLs and metadata

        Must be implemented by subclasses to parse site-specific search
        result structure.
        """
        pass

    @abstractmethod
    async def scrape_detail_page(self, result: SearchResult) -> ScrapedContent:
        """
        Scrape content from a detail page.

        Args:
            result: SearchResult object containing the URL to scrape

        Returns:
            ScrapedContent object with extracted data

        Must be implemented by subclasses to extract site-specific content
        from detail pages.
        """
        pass

    # Optional methods that can be overridden

    async def handle_pagination(self) -> bool:
        """
        Handle pagination if present.

        Returns:
            True if there's a next page and navigation was successful,
            False otherwise

        Can be overridden by subclasses that need pagination support.
        """
        return False

    async def pre_scrape_hook(self) -> None:
        """
        Hook called before scraping begins.

        Can be overridden for custom setup (e.g., login, accepting cookies).
        """
        pass

    async def post_scrape_hook(self) -> None:
        """
        Hook called after scraping completes.

        Can be overridden for custom cleanup or post-processing.
        """
        pass

    # Template method defining the workflow

    async def scrape(
        self, query: str, max_results: Optional[int] = None, scrape_details: bool = True
    ) -> List[ScrapedContent]:
        """
        Main scraping workflow (Template Method).

        This method orchestrates the entire scraping process:
        1. Initialize browser
        2. Navigate to search page
        3. Submit query
        4. Extract result links
        5. Optionally scrape detail pages
        6. Cleanup

        Args:
            query: Search query string
            max_results: Maximum number of results to scrape (None for all)
            scrape_details: Whether to scrape detail pages or just get links

        Returns:
            List of ScrapedContent objects
        """
        try:
            # Initialize
            await self._init_browser()
            self.status = ScraperStatus.INITIALIZING

            # Pre-scrape hook
            await self.pre_scrape_hook()

            # Navigate to search page
            self.status = ScraperStatus.NAVIGATING
            self.logger.info(f"Navigating to search page...")
            await self._retry_operation(self.navigate_to_search)
            await self._random_delay()

            # Submit query
            self.status = ScraperStatus.SEARCHING
            self.logger.info(f"Submitting query: '{query}'")
            await self._retry_operation(self.submit_query, query)
            await self._random_delay()

            # Extract links
            all_results: List[SearchResult] = []
            page_count = 0

            while True:
                self.status = ScraperStatus.EXTRACTING_LINKS
                self.logger.info(f"Extracting links from page {page_count + 1}...")

                page_results = await self._retry_operation(self.extract_result_links)
                all_results.extend(page_results)
                self.logger.info(f"Found {len(page_results)} results on this page")

                page_count += 1

                # Check if we should continue pagination
                if max_results and len(all_results) >= max_results:
                    all_results = all_results[:max_results]
                    self.logger.info(f"Reached maximum results limit: {max_results}")
                    break

                # Try to go to next page
                has_next_page = await self.handle_pagination()
                if not has_next_page:
                    break

                await self._random_delay()

            self.logger.info(f"Total results found: {len(all_results)}")

            # Scrape detail pages if requested
            if scrape_details:
                self.status = ScraperStatus.SCRAPING_DETAILS
                self.logger.info("Scraping detail pages...")

                for idx, result in enumerate(all_results, 1):
                    try:
                        self.logger.info(
                            f"Scraping detail page {idx}/{len(all_results)}: {result.url}"
                        )
                        content = await self._retry_operation(
                            self.scrape_detail_page, result
                        )
                        self.results.append(content)
                        await self._random_delay()
                    except Exception as e:
                        self.logger.error(f"Failed to scrape {result.url}: {str(e)}")
                        continue

            # Post-scrape hook
            await self.post_scrape_hook()

            self.status = ScraperStatus.COMPLETED
            self.logger.info(
                f"Scraping completed. Successfully scraped {len(self.results)} pages."
            )

            return self.results

        except Exception as e:
            self.status = ScraperStatus.FAILED
            self.logger.error(f"Scraping failed: {str(e)}", exc_info=True)
            raise

        finally:
            await self._cleanup()

    def get_results(self) -> List[ScrapedContent]:
        """Return the list of scraped results."""
        return self.results

    def get_status(self) -> ScraperStatus:
        """Return the current status of the scraper."""
        return self.status
