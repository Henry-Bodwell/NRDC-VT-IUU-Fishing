"""
Generic scraper that works with YAML configuration files.

This scraper implements all abstract methods using configuration from
site-specific YAML files, making it possible to scrape many sites
without writing custom code.
"""

from typing import List, Optional
from datetime import datetime
from webScraper.scrapers.base_scraper import BaseScraper, SearchResult, ScrapedContent
from webScraper.config.site_config import SiteConfig, get_site_config
import re
from dateutil import parser as date_parser


class GenericScraper(BaseScraper):
    """
    Generic scraper driven by YAML configuration.

    This scraper can handle most standard websites using only configuration,
    without requiring custom code for each site.
    """

    def __init__(
        self,
        site_name: Optional[str] = None,
        site_config: Optional[SiteConfig] = None,
        **kwargs,
    ):
        """
        Initialize the generic scraper.

        Args:
            site_name: Name of the site (loads config from YAML)
            site_config: SiteConfig instance (alternative to site_name)
            **kwargs: Additional arguments passed to BaseScraper
        """
        # Load config if site_name provided
        if site_name and not site_config:
            site_config = get_site_config(site_name)
            if not site_config:
                raise ValueError(f"No configuration found for site: {site_name}")

        if not site_config:
            raise ValueError("Either site_name or site_config must be provided")

        # Initialize base with config
        super().__init__(
            site_config=site_config,
            delay_range=site_config.rate_limit.delay_range,
            **kwargs,
        )

        self.config = site_config
        self.logger.info(f"Initialized scraper for: {self.config.site_name}")

    async def _init_browser(self) -> None:
        """Initialize browser with site-specific settings."""
        await super()._init_browser()

        # Set custom headers if configured
        if self.config.headers:
            await self.context.set_extra_http_headers(self.config.headers)
            self.logger.debug(f"Set custom headers: {self.config.headers}")

        # Set cookies if configured
        if self.config.cookies:
            await self.context.add_cookies(self.config.cookies)
            self.logger.debug(f"Added {len(self.config.cookies)} cookies")

    async def navigate_to_search(self) -> None:
        """Navigate to the configured search page."""
        self.logger.info(f"Navigating to {self.config.search_url}")
        await self.page.goto(
            self.config.search_url,
            wait_until=(
                "networkidle" if self.config.javascript_required else "domcontentloaded"
            ),
        )
        self.logger.info("Successfully loaded search page")

    async def submit_query(self, query: str) -> None:
        """
        Submit a search query using configured selectors.

        Args:
            query: The search term
        """
        # Wait for search input to be visible
        await self.page.wait_for_selector(
            self.config.selectors.search_input,
            state="visible",
            timeout=self.config.wait_for_timeout,
        )

        # Fill in the search query
        await self.page.fill(self.config.selectors.search_input, query)
        self.logger.info(f"Filled search query: {query}")

        # Click the search button
        await self.page.click(self.config.selectors.search_button)

        # Wait for results to load
        wait_selector = (
            self.config.wait_for_selector or self.config.selectors.result_links
        )
        await self.page.wait_for_selector(
            wait_selector, state="visible", timeout=self.config.wait_for_timeout
        )
        self.logger.info("Search results loaded")

    async def extract_result_links(self) -> List[SearchResult]:
        """
        Extract result links using configured selectors.

        Returns:
            List of SearchResult objects
        """
        results = []

        # Get all result link elements
        result_elements = await self.page.query_selector_all(
            self.config.selectors.result_links
        )

        self.logger.info(f"Found {len(result_elements)} result elements")

        for element in result_elements:
            try:
                # Extract URL
                url = await element.get_attribute("href")

                # Make URL absolute if it's relative
                if url:
                    if not url.startswith("http"):
                        if url.startswith("/"):
                            url = f"{self.config.base_url}{url}"
                        else:
                            url = f"{self.config.base_url}/{url}"

                # Extract title
                title = None
                if self.config.selectors.result_title:
                    # Try to find title element relative to result
                    parent = await element.evaluate_handle(
                        'el => el.closest("div, article, li")'
                    )
                    if parent:
                        title_element = await parent.query_selector(
                            self.config.selectors.result_title
                        )
                        if title_element:
                            title = await title_element.inner_text()

                # Fallback to link text if no title found
                if not title:
                    title = await element.inner_text()

                # Extract snippet
                snippet = None
                if self.config.selectors.result_snippet:
                    parent = await element.evaluate_handle(
                        'el => el.closest("div, article, li")'
                    )
                    if parent:
                        snippet_element = await parent.query_selector(
                            self.config.selectors.result_snippet
                        )
                        if snippet_element:
                            snippet = await snippet_element.inner_text()

                # Extract custom metadata if configured
                metadata = {}
                for key, selector in self.config.selectors.custom.items():
                    try:
                        parent = await element.evaluate_handle(
                            'el => el.closest("div, article, li")'
                        )
                        if parent:
                            custom_element = await parent.query_selector(selector)
                            if custom_element:
                                metadata[key] = await custom_element.inner_text()
                    except Exception:
                        pass

                if url:
                    results.append(
                        SearchResult(
                            url=url,
                            title=title.strip() if title else None,
                            snippet=snippet.strip() if snippet else None,
                            metadata=metadata if metadata else None,
                        )
                    )

            except Exception as e:
                self.logger.warning(f"Failed to extract result: {str(e)}")
                continue

        return results

    async def scrape_detail_page(self, result: SearchResult) -> ScrapedContent:
        """
        Scrape content from a detail page using configured selectors.

        Args:
            result: SearchResult object with the URL to scrape

        Returns:
            ScrapedContent object with extracted data
        """
        # Navigate to the detail page
        await self.page.goto(
            result.url,
            wait_until=(
                "networkidle" if self.config.javascript_required else "domcontentloaded"
            ),
        )

        # Extract title
        title = result.title  # Use search result title as fallback
        if self.config.selectors.detail_title:
            try:
                title_element = await self.page.query_selector(
                    self.config.selectors.detail_title
                )
                if title_element:
                    title = await title_element.inner_text()
            except Exception as e:
                self.logger.warning(f"Could not extract title: {str(e)}")

        # Extract main content
        content = ""
        if self.config.selectors.detail_content:
            try:
                content_element = await self.page.query_selector(
                    self.config.selectors.detail_content
                )
                if content_element:
                    content = await content_element.inner_text()
            except Exception as e:
                self.logger.warning(f"Could not extract content: {str(e)}")

        # Extract date
        date = None
        if self.config.selectors.detail_date:
            try:
                date_element = await self.page.query_selector(
                    self.config.selectors.detail_date
                )
                if date_element:
                    # Try datetime attribute first
                    date_str = await date_element.get_attribute("datetime")
                    if not date_str:
                        date_str = await date_element.inner_text()

                    if date_str:
                        date = self._parse_date(date_str)
            except Exception as e:
                self.logger.warning(f"Could not extract date: {str(e)}")

        # Extract author
        author = None
        if self.config.selectors.detail_author:
            try:
                author_element = await self.page.query_selector(
                    self.config.selectors.detail_author
                )
                if author_element:
                    author = await author_element.inner_text()
            except Exception as e:
                self.logger.warning(f"Could not extract author: {str(e)}")

        # Extract tags
        tags = None
        if self.config.selectors.detail_tags:
            try:
                tag_elements = await self.page.query_selector_all(
                    self.config.selectors.detail_tags
                )
                if tag_elements:
                    tags = []
                    for tag_el in tag_elements:
                        tag_text = await tag_el.inner_text()
                        tags.append(tag_text.strip())
            except Exception as e:
                self.logger.warning(f"Could not extract tags: {str(e)}")

        # Extract custom metadata
        metadata = result.metadata or {}
        for key, selector in self.config.selectors.custom.items():
            try:
                custom_element = await self.page.query_selector(selector)
                if custom_element:
                    metadata[key] = await custom_element.inner_text()
            except Exception:
                pass

        # Add site metadata
        if self.config.metadata:
            metadata.update({"site_metadata": self.config.metadata})

        return ScrapedContent(
            url=result.url,
            title=title.strip() if title else "Untitled",
            content=content.strip(),
            date=date,
            author=author.strip() if author else None,
            tags=tags,
            metadata=metadata if metadata else None,
        )

    async def handle_pagination(self) -> bool:
        """
        Handle pagination using configuration.

        Returns:
            True if navigated to next page, False if no more pages
        """
        if not self.config.pagination.enabled:
            return False

        try:
            if self.config.pagination.pagination_type == "button":
                # Check if next page button exists
                next_button = await self.page.query_selector(
                    self.config.pagination.next_button
                )

                if not next_button:
                    self.logger.info("No next page button found")
                    return False

                # Check if button is disabled
                is_disabled = await next_button.get_attribute("disabled")
                aria_disabled = await next_button.get_attribute("aria-disabled")

                if is_disabled or aria_disabled == "true":
                    self.logger.info("Next page button is disabled")
                    return False

                # Click next page
                self.logger.info("Navigating to next page...")
                await next_button.click()

                # Wait for new results to load
                wait_selector = (
                    self.config.wait_for_selector or self.config.selectors.result_links
                )
                await self.page.wait_for_selector(
                    wait_selector, state="visible", timeout=self.config.wait_for_timeout
                )

                return True

            elif self.config.pagination.pagination_type == "url_pattern":
                # URL-based pagination (e.g., ?page=2)
                current_url = self.page.url

                # Extract current page number
                page_match = re.search(r"[?&]page=(\d+)", current_url)
                current_page = int(page_match.group(1)) if page_match else 1
                next_page = current_page + 1

                # Check max pages
                if (
                    self.config.pagination.max_pages
                    and next_page > self.config.pagination.max_pages
                ):
                    self.logger.info(
                        f"Reached max pages: {self.config.pagination.max_pages}"
                    )
                    return False

                # Build next URL
                if page_match:
                    next_url = current_url.replace(
                        f"page={current_page}", f"page={next_page}"
                    )
                else:
                    separator = "&" if "?" in current_url else "?"
                    next_url = f"{current_url}{separator}page={next_page}"

                self.logger.info(f"Navigating to page {next_page}: {next_url}")
                await self.page.goto(next_url, wait_until="networkidle")

                # Check if the new page has any results
                try:
                    result_elements = await self.page.query_selector_all(
                        self.config.selectors.result_links
                    )
                    if not result_elements:
                        self.logger.info("No results found on this page, stopping pagination")
                        return False
                except Exception as e:
                    self.logger.warning(f"Could not check for results: {e}")
                    return False

                return True

            else:
                self.logger.warning(
                    f"Unsupported pagination type: {self.config.pagination.pagination_type}"
                )
                return False

        except Exception as e:
            self.logger.warning(f"Pagination failed: {str(e)}")
            return False

    async def pre_scrape_hook(self) -> None:
        """
        Pre-scrape hook for authentication and setup.
        """
        # Handle authentication if required
        if self.config.authentication.required:
            await self._handle_authentication()

        # Give page time to fully load
        await self.page.wait_for_timeout(1000)

    async def _handle_authentication(self) -> None:
        """Handle authentication based on configuration."""
        auth_config = self.config.authentication

        if auth_config.auth_type == "form":
            self.logger.info("Performing form-based authentication...")

            # Get credentials from environment
            import os

            if auth_config.credentials_env_var:
                creds = os.getenv(auth_config.credentials_env_var)
                if creds:
                    username, password = creds.split(":", 1)
                else:
                    raise ValueError(
                        f"Credentials not found in env var: {auth_config.credentials_env_var}"
                    )
            else:
                raise ValueError("No credentials configured for authentication")

            # Navigate to login page
            await self.page.goto(auth_config.login_url)

            # Fill in credentials
            await self.page.fill(auth_config.username_field, username)
            await self.page.fill(auth_config.password_field, password)

            # Submit form
            await self.page.click(auth_config.submit_button)

            # Wait for navigation
            await self.page.wait_for_load_state("networkidle")

            self.logger.info("Authentication successful")

        elif auth_config.auth_type == "basic":
            # Basic auth is handled via browser context
            self.logger.info("Basic authentication configured")
            pass

        else:
            self.logger.warning(f"Unsupported auth type: {auth_config.auth_type}")

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into datetime object.

        Args:
            date_str: Date string in various formats

        Returns:
            datetime object or None if parsing fails
        """
        try:
            # Try ISO format first
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

        try:
            # Use dateutil parser for flexible parsing
            return date_parser.parse(date_str)
        except (ValueError, TypeError):
            self.logger.warning(f"Could not parse date: {date_str}")
            return None


# Convenience function for quick scraping
async def scrape_site(
    site_name: str,
    query: str,
    max_results: Optional[int] = None,
    scrape_details: bool = True,
    headless: bool = True,
) -> List[ScrapedContent]:
    """
    Convenience function to scrape a site by name.

    Args:
        site_name: Name of the configured site
        query: Search query
        max_results: Maximum number of results
        scrape_details: Whether to scrape detail pages
        headless: Run browser in headless mode

    Returns:
        List of ScrapedContent objects
    """
    scraper = GenericScraper(site_name=site_name, headless=headless)
    return await scraper.scrape(
        query=query, max_results=max_results, scrape_details=scrape_details
    )


# Usage example
async def main():
    """Example usage of the generic scraper."""

    # Scrape DOJ with configuration
    results = await scrape_site(
        site_name="noaa_fisheries",
        query="illegal fishing",
        max_results=10,
        scrape_details=True,
        headless=False,
    )

    print(f"\nScraped {len(results)} pages from Monga Bay:")
    for result in results[:3]:  # Show first 3
        print(f"\n{'='*80}")
        print(f"Title: {result.title}")
        print(f"URL: {result.url}")
        print(f"Date: {result.date}")
        print(f"Content preview: {result.content[:200]}...")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
