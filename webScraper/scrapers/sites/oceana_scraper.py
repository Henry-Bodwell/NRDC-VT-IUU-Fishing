"""
Custom scraper for Oceana.org with hidden search bar and infinite scroll support.

This scraper extends GenericScraper to handle Oceana-specific features:
- Hidden search bar that appears when clicking search icon
- Infinite scroll pagination for press releases
"""

from typing import List, Optional
from webScraper.scrapers.generic_scraper import GenericScraper
from webScraper.scrapers.base_scraper import SearchResult


class OceanaScraper(GenericScraper):
    """Custom scraper for Oceana with hidden search bar and infinite scroll."""

    def __init__(self, **kwargs):
        """Initialize Oceana scraper with site config."""
        super().__init__(site_name="oceana", **kwargs)
        self._scroll_count = 0

    async def navigate_to_search(self) -> None:
        """Navigate to search page and handle initial popup."""
        # Navigate first
        await super().navigate_to_search()

        # Then handle popup
        await self._handle_popup()

    async def _handle_popup(self) -> None:
        """Dismiss initial popup if it appears."""
        # Try multiple strategies to close the popup

        # Strategy 1: Try configured close button from custom selectors
        popup_close_selector = self.config.selectors.custom.get("popup_close")
        if popup_close_selector:
            try:
                self.logger.info(
                    f"Looking for popup close button: {popup_close_selector}"
                )
                popup_close = await self.page.wait_for_selector(
                    popup_close_selector,
                    state="visible",
                    timeout=3000,
                )

                if popup_close:
                    self.logger.info("Closing initial popup...")
                    await popup_close.click()
                    await self.page.wait_for_timeout(1000)
                    self.logger.info("Popup closed successfully")
                    return
            except Exception as e:
                self.logger.info(f"Configured close button not found: {str(e)}")

        # Strategy 3: Try pressing ESC
        try:
            self.logger.info("Trying ESC key to close popup...")
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(1000)
        except Exception as e:
            self.logger.debug(f"ESC key failed: {str(e)}")

        # Strategy 4: Click outside popup (on overlay/backdrop)
        try:
            self.logger.info("Trying to click outside popup...")
            overlay = await self.page.query_selector(
                ".overlay, .modal-backdrop, .popup-overlay"
            )
            if overlay:
                await overlay.click(position={"x": 10, "y": 10})
                await self.page.wait_for_timeout(1000)
                self.logger.info("Clicked overlay to close popup")
                return
        except Exception as e:
            self.logger.debug(f"Overlay click failed: {str(e)}")

        self.logger.warning(
            "Could not close popup with any strategy, continuing anyway..."
        )

    async def submit_query(self, query: str) -> None:
        """
        Submit search query, handling hidden search bar.

        Args:
            query: The search term
        """
        # Click search icon to reveal search bar (from custom selectors)
        search_icon_selector = self.config.selectors.custom.get("search_icon")
        if search_icon_selector:
            try:
                self.logger.info(f"Looking for search icon: {search_icon_selector}")
                search_icon = await self.page.wait_for_selector(
                    search_icon_selector,
                    state="visible",
                    timeout=self.config.wait_for_timeout,
                )

                self.logger.info("Clicking search icon to reveal search bar...")
                await search_icon.click()
                await self.page.wait_for_timeout(1000)  # Wait for animation

                # Wait for search input to become visible
                self.logger.info(
                    f"Looking for search input: {self.config.selectors.search_input}"
                )
                await self.page.wait_for_selector(
                    self.config.selectors.search_input,
                    state="visible",
                    timeout=self.config.wait_for_timeout,
                )
                self.logger.info("Search bar is now visible")
            except Exception as e:
                self.logger.error(f"Failed to open search bar: {str(e)}")
                raise

        # Wait for search input to be visible
        await self.page.wait_for_selector(
            self.config.selectors.search_input,
            state="visible",
            timeout=self.config.wait_for_timeout,
        )

        # Fill in the search query
        await self.page.fill(self.config.selectors.search_input, query)
        self.logger.info(f"Filled search query: {query}")

        # Check if there's a search button, otherwise press Enter
        if (
            hasattr(self.config.selectors, "search_button")
            and self.config.selectors.search_button
        ):
            await self.page.click(self.config.selectors.search_button)
            self.logger.info("Clicked search button")
        else:
            # No button - press Enter instead
            await self.page.press(self.config.selectors.search_input, "Enter")
            self.logger.info("Pressed Enter to submit search")

        # Wait for results to load
        wait_selector = (
            self.config.wait_for_selector or self.config.selectors.result_links
        )
        await self.page.wait_for_selector(
            wait_selector, state="visible", timeout=self.config.wait_for_timeout
        )
        self.logger.info("Search results loaded")

    async def handle_pagination(self) -> bool:
        """
        Handle infinite scroll pagination.

        Returns:
            True if new content loaded, False if reached end
        """
        if not self.config.pagination.enabled:
            return False

        # Check if using infinite scroll
        if self.config.pagination.pagination_type != "infinite_scroll":
            # Fall back to parent's pagination handling
            return await super().handle_pagination()

        try:
            # Get scroll configuration
            scroll_pause = getattr(self.config.pagination, "scroll_pause_time", 2000)
            max_scrolls = getattr(self.config.pagination, "max_scrolls", 10)

            # Check max scrolls
            if self._scroll_count >= max_scrolls:
                self.logger.info(f"Reached max scrolls: {max_scrolls}")
                return False

            # Get current scroll height
            previous_height = await self.page.evaluate("document.body.scrollHeight")

            # Scroll to bottom
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.logger.info(
                f"Scrolled to bottom (attempt {self._scroll_count + 1}/{max_scrolls})"
            )

            # Wait for new content to load
            await self.page.wait_for_timeout(scroll_pause)

            # Check if new content loaded
            new_height = await self.page.evaluate("document.body.scrollHeight")

            if new_height == previous_height:
                self.logger.info("No new content loaded, reached end of results")
                return False

            self._scroll_count += 1
            self.logger.info(
                f"New content loaded (height: {previous_height} → {new_height})"
            )
            return True

        except Exception as e:
            self.logger.warning(f"Infinite scroll pagination failed: {str(e)}")
            return False


# Convenience function for scraping Oceana
async def scrape_oceana(
    query: str,
    max_results: Optional[int] = None,
    scrape_details: bool = True,
    headless: bool = True,
) -> List:
    """
    Convenience function to scrape Oceana.org.

    Args:
        query: Search query
        max_results: Maximum number of results
        scrape_details: Whether to scrape detail pages
        headless: Run browser in headless mode

    Returns:
        List of ScrapedContent objects
    """
    scraper = OceanaScraper(headless=headless)
    return await scraper.scrape(
        query=query, max_results=max_results, scrape_details=scrape_details
    )


# Usage example
async def main():
    """Example usage of the Oceana scraper."""

    results = await scrape_oceana(
        query="illegal fishing",
        max_results=20,
        scrape_details=True,
        headless=True,
    )

    print(f"\nScraped {len(results)} pages from Oceana:")
    for result in results[:3]:  # Show first 3
        print(f"\n{'='*80}")
        print(f"Title: {result.title}")
        print(f"URL: {result.url}")
        print(f"Date: {result.date}")
        if result.content:
            print(f"Content preview: {result.content[:200]}...")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
