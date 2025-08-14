import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import aiofiles


@dataclass
class SiteConfig:
    """Configuration for a specific news site"""

    name: str
    base_url: str
    search_url: str
    search_input_selector: str
    search_button_selector: str
    article_link_selectors: List[str]
    next_page_selector: Optional[str] = None
    results_per_page: int = 10
    max_pages: int = 5


class NewsNavigator:
    def __init__(self, headless: bool = True, timeout: int = 30000, delay: int = 2000):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.headless = headless
        self.timeout = timeout
        self.delay = delay

        # Predefined site configurations
        self.site_configs = {
            "cnn": SiteConfig(
                name="CNN",
                base_url="https://www.cnn.com",
                search_url="https://www.cnn.com/search",
                search_input_selector="input[name='q'], input[type='search'], .search-input",
                search_button_selector="button[type='submit'], .search-button, .search-submit",
                article_link_selectors=[
                    "a[href*='/article/']",
                    "a[href*='/news/']",
                    ".card-media a",
                    ".media__link",
                    "h3 a",
                ],
                next_page_selector=".pagination-arrow-right, .next-page",
            ),
            "bbc": SiteConfig(
                name="BBC News",
                base_url="https://www.bbc.com",
                search_url="https://www.bbc.com/search",
                search_input_selector="#search-input, input[name='q']",
                search_button_selector="#search-button, button[type='submit']",
                article_link_selectors=[
                    "a[href*='/news/']",
                    ".gs-title a",
                    "h3 a",
                    ".media__link",
                ],
            ),
            "reuters": SiteConfig(
                name="Reuters",
                base_url="https://www.reuters.com",
                search_url="https://www.reuters.com/site-search/",
                search_input_selector="input[name='blob'], input[type='search']",
                search_button_selector="button[type='submit'], .search-submit",
                article_link_selectors=[
                    "a[href*='/article/']",
                    ".story-title a",
                    "h3 a",
                    ".media-story-card__headline__eqhp9 a",
                ],
            ),
        }

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def initialize(self):
        """Initialize the browser and context."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)

        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

    async def search_site(
        self, site_key: str, search_terms: List[str], date_filter: Optional[str] = None
    ) -> List[str]:
        """
        Search a news site and return article URLs.

        Args:
            site_key: Key for predefined site config (e.g., 'cnn', 'bbc')
            search_terms: List of search terms to query
            date_filter: Optional date filter ('today', 'week', 'month')

        Returns:
            List of article URLs found
        """
        if site_key not in self.site_configs:
            raise ValueError(
                f"Site '{site_key}' not configured. Available: {list(self.site_configs.keys())}"
            )

        config = self.site_configs[site_key]
        all_article_urls = set()

        for search_term in search_terms:
            print(f"Searching {config.name} for: '{search_term}'")
            urls = await self._search_single_term(config, search_term, date_filter)
            all_article_urls.update(urls)

            # Add delay between search terms
            if len(search_terms) > 1:
                await asyncio.sleep(self.delay / 1000)

        return list(all_article_urls)

    async def _search_single_term(
        self, config: SiteConfig, search_term: str, date_filter: Optional[str] = None
    ) -> List[str]:
        """Search for a single term and return article URLs."""
        page = await self.context.new_page()
        article_urls = set()

        try:
            # Navigate to search page
            await page.goto(config.search_url, timeout=self.timeout)
            await page.wait_for_load_state("networkidle")

            # Handle cookie consent banners
            await self._handle_consent_banners(page)

            # Find and fill search input
            search_input = await page.wait_for_selector(
                config.search_input_selector, timeout=10000
            )
            await search_input.fill(search_term)

            # Submit search
            try:
                search_button = await page.wait_for_selector(
                    config.search_button_selector, timeout=5000
                )
                await search_button.click()
            except:
                # Try pressing Enter if button click fails
                await search_input.press("Enter")

            # Wait for search results
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)  # Additional wait for dynamic content

            # Extract article URLs from multiple pages
            for page_num in range(1, config.max_pages + 1):
                print(f"  Extracting from page {page_num}...")

                # Extract article URLs from current page
                page_urls = await self._extract_article_urls(page, config)
                article_urls.update(page_urls)

                print(f"    Found {len(page_urls)} articles on page {page_num}")

                # Try to navigate to next page
                if page_num < config.max_pages and config.next_page_selector:
                    next_button = await page.query_selector(config.next_page_selector)
                    if next_button and await next_button.is_visible():
                        await next_button.click()
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(2)
                    else:
                        print(f"    No more pages available")
                        break

        except Exception as e:
            print(f"Error searching {config.name}: {e}")
        finally:
            await page.close()

        return list(article_urls)

    async def _extract_article_urls(self, page: Page, config: SiteConfig) -> List[str]:
        """Extract article URLs from the current page."""
        article_urls = set()

        for selector in config.article_link_selectors:
            try:
                # Find all matching links
                links = await page.query_selector_all(selector)

                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        # Convert relative URLs to absolute
                        if href.startswith("/"):
                            full_url = urljoin(config.base_url, href)
                        elif href.startswith("http"):
                            full_url = href
                        else:
                            continue

                        # Filter for actual article URLs
                        if self._is_valid_article_url(full_url, config):
                            article_urls.add(full_url)

            except Exception as e:
                print(f"    Error with selector '{selector}': {e}")
                continue

        return list(article_urls)

    def _is_valid_article_url(self, url: str, config: SiteConfig) -> bool:
        """Check if URL appears to be a valid article URL."""
        # Basic URL validation
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return False
        except:
            return False

        # Filter out non-article URLs
        unwanted_patterns = [
            "/video/",
            "/live/",
            "/sport/",
            "/weather/",
            "/category/",
            "/tag/",
            "/author/",
            "/search/",
            "mailto:",
            "javascript:",
            "#",
            "?",
        ]

        url_lower = url.lower()
        for pattern in unwanted_patterns:
            if pattern in url_lower:
                return False

        # Must contain article indicators
        article_indicators = [
            "/article/",
            "/news/",
            "/story/",
            "/report/",
            "/politics/",
            "/business/",
            "/technology/",
            "/world/",
        ]

        return any(indicator in url_lower for indicator in article_indicators)

    async def _handle_consent_banners(self, page: Page):
        """Handle cookie consent and other banners."""
        consent_selectors = [
            "button:has-text('Accept')",
            "button:has-text('I Accept')",
            "button:has-text('OK')",
            "button:has-text('Continue')",
            ".accept-cookies",
            ".cookie-accept",
            "#accept-cookies",
        ]

        for selector in consent_selectors:
            try:
                button = await page.query_selector(selector)
                if button and await button.is_visible():
                    await button.click()
                    await asyncio.sleep(1)
                    break
            except:
                continue

    async def crawl_site_section(
        self, site_key: str, section_url: str, max_articles: int = 50
    ) -> List[str]:
        """
        Crawl a specific section of a news site (e.g., /politics, /technology).

        Args:
            site_key: Key for predefined site config
            section_url: URL of the section to crawl
            max_articles: Maximum number of articles to collect

        Returns:
            List of article URLs found
        """
        if site_key not in self.site_configs:
            raise ValueError(f"Site '{site_key}' not configured")

        config = self.site_configs[site_key]
        page = await self.context.new_page()
        article_urls = set()

        try:
            print(f"Crawling {config.name} section: {section_url}")
            await page.goto(section_url, timeout=self.timeout)
            await page.wait_for_load_state("networkidle")

            await self._handle_consent_banners(page)

            # Scroll to load more content (for infinite scroll sites)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

            # Extract article URLs
            urls = await self._extract_article_urls(page, config)
            article_urls.update(urls[:max_articles])

            print(f"Found {len(article_urls)} articles in section")

        except Exception as e:
            print(f"Error crawling section: {e}")
        finally:
            await page.close()

        return list(article_urls)

    def add_site_config(self, site_key: str, config: SiteConfig):
        """Add a custom site configuration."""
        self.site_configs[site_key] = config

    async def close(self):
        """Close the browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright"):
            await self.playwright.stop()


# Integration with the article scraper
class IntegratedNewsScraper:
    """Combines navigation and scraping functionality."""

    def __init__(self, headless: bool = True, delay: int = 2000):
        self.navigator = NewsNavigator(headless=headless, delay=delay)
        self.scraper = None  # Will import NewsArticleScraper

    async def __aenter__(self):
        await self.navigator.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.navigator.close()
        if self.scraper:
            await self.scraper.close()

    async def search_and_scrape(
        self, site_key: str, search_terms: List[str], max_articles: int = 20
    ) -> Tuple[List, List]:
        """
        Search a site and scrape the found articles.

        Returns:
            Tuple of (scraped_articles, errors)
        """
        # Find article URLs
        article_urls = await self.navigator.search_site(site_key, search_terms)

        if not article_urls:
            print("No articles found")
            return [], []

        # Limit the number of articles
        article_urls = article_urls[:max_articles]
        print(f"Scraping {len(article_urls)} articles...")

        # Import and use the scraper (assuming it's in the same directory)
        from playwrightTest import NewsArticleScraper

        async with NewsArticleScraper(headless=self.navigator.headless) as scraper:
            results, errors = await scraper.scrape_multiple_articles(
                article_urls, concurrency=3
            )

        return results, errors


# Usage example
async def main():
    """Example usage of the integrated news scraper."""

    search_terms = ["artificial intelligence", "climate change", "economic policy"]

    async with IntegratedNewsScraper(headless=True) as scraper:
        # Search and scrape CNN
        print("=== Searching CNN ===")
        cnn_articles, cnn_errors = await scraper.search_and_scrape(
            "cnn", search_terms, max_articles=10
        )

        print(f"CNN: Scraped {len(cnn_articles)} articles, {len(cnn_errors)} errors")

        # Search and scrape BBC
        print("\n=== Searching BBC ===")
        bbc_articles, bbc_errors = await scraper.search_and_scrape(
            "bbc", search_terms, max_articles=10
        )

        print(f"BBC: Scraped {len(bbc_articles)} articles, {len(bbc_errors)} errors")

        # Crawl a specific section
        print("\n=== Crawling Reuters Technology Section ===")
        tech_urls = await scraper.navigator.crawl_site_section(
            "reuters", "https://www.reuters.com/technology/", max_articles=15
        )

        # Scrape the section articles
        if tech_urls:
            from news_scraper import NewsArticleScraper

            async with NewsArticleScraper() as article_scraper:
                tech_articles, tech_errors = (
                    await article_scraper.scrape_multiple_articles(tech_urls[:10])
                )

            print(f"Reuters Tech: Scraped {len(tech_articles)} articles")

        # Combine all results
        all_articles = (
            cnn_articles + bbc_articles + (tech_articles if tech_urls else [])
        )

        if all_articles:
            # Save combined results
            json_data = [asdict(article) for article in all_articles]
            async with aiofiles.open(
                "all_scraped_articles.json", "w", encoding="utf-8"
            ) as f:
                await f.write(json.dumps(json_data, indent=2, ensure_ascii=False))

            print(f"\nTotal articles scraped: {len(all_articles)}")
            print("Results saved to 'all_scraped_articles.json'")


if __name__ == "__main__":
    asyncio.run(main())
