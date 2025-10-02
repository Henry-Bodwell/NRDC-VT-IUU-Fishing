"""
Example scraper implementation showing how to extend the BaseScraper.

This is a reference implementation that can be used as a template for
creating site-specific scrapers.
"""

from typing import List
from base_scraper import BaseScraper, SearchResult, ScrapedContent
from datetime import datetime


class ExampleScraper(BaseScraper):
    """
    Example scraper implementation.

    This serves as a template for creating new site-specific scrapers.
    Replace the selectors and logic with site-specific implementations.
    """

    def __init__(self, base_url: str, **kwargs):
        """
        Initialize the example scraper.

        Args:
            base_url: Base URL of the target website
            **kwargs: Additional arguments passed to BaseScraper
        """
        super().__init__(**kwargs)
        self.base_url = base_url

        # Site-specific configuration
        self.search_url = f"{base_url}/search"
        self.selectors = {
            "search_input": 'input[name="q"]',
            "search_button": 'button[type="submit"]',
            "result_links": "div.result a.result-link",
            "result_title": "h3.result-title",
            "result_snippet": "p.result-snippet",
            "next_page": "a.next-page",
            "detail_title": "h1.article-title",
            "detail_content": "div.article-content",
            "detail_date": "time.published-date",
            "detail_author": "span.author-name",
        }

    async def navigate_to_search(self) -> None:
        """Navigate to the search page."""
        self.logger.info(f"Navigating to {self.search_url}")
        await self.page.goto(self.search_url, wait_until="networkidle")
        self.logger.info("Successfully loaded search page")

    async def submit_query(self, query: str) -> None:
        """
        Submit a search query.

        Args:
            query: The search term
        """
        # Wait for search input to be visible
        await self.page.wait_for_selector(
            self.selectors["search_input"], state="visible"
        )

        # Fill in the search query
        await self.page.fill(self.selectors["search_input"], query)
        self.logger.info(f"Filled search query: {query}")

        # Click the search button
        await self.page.click(self.selectors["search_button"])

        # Wait for results to load
        await self.page.wait_for_selector(
            self.selectors["result_links"], state="visible", timeout=10000
        )
        self.logger.info("Search results loaded")

    async def extract_result_links(self) -> List[SearchResult]:
        """
        Extract result links from the current search results page.

        Returns:
            List of SearchResult objects
        """
        results = []

        # Get all result elements
        result_elements = await self.page.query_selector_all(
            self.selectors["result_links"]
        )

        self.logger.info(f"Found {len(result_elements)} result elements")

        for element in result_elements:
            try:
                # Extract URL
                url = await element.get_attribute("href")

                # Make URL absolute if it's relative
                if url and not url.startswith("http"):
                    url = f"{self.base_url}{url}"

                # Extract title (try from the element or parent)
                title = None
                title_element = await element.query_selector(
                    self.selectors["result_title"]
                )
                if title_element:
                    title = await title_element.inner_text()
                else:
                    title = await element.inner_text()

                # Extract snippet if available
                snippet = None
                parent = await element.evaluate_handle('el => el.closest("div.result")')
                if parent:
                    snippet_element = await parent.query_selector(
                        self.selectors["result_snippet"]
                    )
                    if snippet_element:
                        snippet = await snippet_element.inner_text()

                if url:
                    results.append(
                        SearchResult(
                            url=url,
                            title=title.strip() if title else None,
                            snippet=snippet.strip() if snippet else None,
                        )
                    )

            except Exception as e:
                self.logger.warning(f"Failed to extract result: {str(e)}")
                continue

        return results

    async def scrape_detail_page(self, result: SearchResult) -> ScrapedContent:
        """
        Scrape content from a detail page.

        Args:
            result: SearchResult object with the URL to scrape

        Returns:
            ScrapedContent object with extracted data
        """
        # Navigate to the detail page
        await self.page.goto(result.url, wait_until="networkidle")

        # Extract title
        title = result.title  # Use search result title as fallback
        try:
            title_element = await self.page.query_selector(
                self.selectors["detail_title"]
            )
            if title_element:
                title = await title_element.inner_text()
        except Exception as e:
            self.logger.warning(f"Could not extract title: {str(e)}")

        # Extract main content
        content = ""
        try:
            content_element = await self.page.query_selector(
                self.selectors["detail_content"]
            )
            if content_element:
                content = await content_element.inner_text()
        except Exception as e:
            self.logger.warning(f"Could not extract content: {str(e)}")

        # Extract date
        date = None
        try:
            date_element = await self.page.query_selector(self.selectors["detail_date"])
            if date_element:
                date_str = await date_element.get_attribute("datetime")
                if not date_str:
                    date_str = await date_element.inner_text()
                # Parse date (this is simplified - you may need more robust parsing)
                if date_str:
                    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception as e:
            self.logger.warning(f"Could not extract date: {str(e)}")

        # Extract author
        author = None
        try:
            author_element = await self.page.query_selector(
                self.selectors["detail_author"]
            )
            if author_element:
                author = await author_element.inner_text()
        except Exception as e:
            self.logger.warning(f"Could not extract author: {str(e)}")

        return ScrapedContent(
            url=result.url,
            title=title.strip() if title else "Untitled",
            content=content.strip(),
            date=date,
            author=author.strip() if author else None,
            metadata={"search_snippet": result.snippet},
        )

    async def handle_pagination(self) -> bool:
        """
        Handle pagination to next page.

        Returns:
            True if navigated to next page, False if no more pages
        """
        try:
            # Check if next page button exists
            next_button = await self.page.query_selector(self.selectors["next_page"])

            if not next_button:
                self.logger.info("No more pages available")
                return False

            # Check if button is disabled
            is_disabled = await next_button.get_attribute("disabled")
            if is_disabled:
                self.logger.info("Next page button is disabled")
                return False

            # Click next page
            self.logger.info("Navigating to next page...")
            await next_button.click()

            # Wait for new results to load
            await self.page.wait_for_load_state("networkidle")

            return True

        except Exception as e:
            self.logger.warning(f"Pagination failed: {str(e)}")
            return False

    async def pre_scrape_hook(self) -> None:
        """
        Pre-scrape hook for custom setup.

        Example: Handle cookie consent, login, etc.
        """
        # Example: Accept cookie consent if present
        try:
            cookie_button = await self.page.query_selector(
                "button.accept-cookies", timeout=3000
            )
            if cookie_button:
                await cookie_button.click()
                self.logger.info("Accepted cookie consent")
        except Exception:
            pass  # No cookie banner found


# Usage example
async def main():
    """Example usage of the scraper."""
    scraper = ExampleScraper(
        base_url="https://example.com",
        headless=False,  # Set to True for production
        max_retries=3,
        delay_range=(2, 4),
    )

    try:
        results = await scraper.scrape(
            query="example search query", max_results=10, scrape_details=True
        )

        print(f"\nScraped {len(results)} pages:")
        for result in results:
            print(f"\nTitle: {result.title}")
            print(f"URL: {result.url}")
            print(f"Date: {result.date}")
            print(f"Author: {result.author}")
            print(f"Content preview: {result.content[:200]}...")

    except Exception as e:
        print(f"Scraping failed: {str(e)}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
