"""
Website Article Scraper using Playwright
Searches websites for articles related to given keywords and stores URLs in JSON.
"""

import json
import asyncio
from datetime import datetime
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
import argparse


class BaseScraper:
    """Base scraper class with common functionality"""

    def __init__(self, base_url, name):
        self.base_url = base_url
        self.name = name

    async def search(self, page, keywords):
        """Override this method for site-specific search logic"""
        return []

    def extract_article_urls(self, page_content, base_url):
        """Basic fallback method to extract article URLs"""
        # This is a simple implementation - can be enhanced
        return []


class UndercurrentNewsScraper(BaseScraper):
    """Scraper for Undercurrent News"""

    def __init__(self):
        super().__init__("https://www.undercurrentnews.com", "Undercurrent News")

    async def search(self, page, keywords):
        search_query = " ".join(keywords)

        # Try multiple search approaches for Undercurrent News
        search_urls = [
            f"{self.base_url}/?s={search_query}",  # WordPress search
        ]

        for search_url in search_urls:
            try:
                print(f"Trying URL: {search_url}")
                await page.goto(search_url, wait_until="load", timeout=15000)
                await page.wait_for_timeout(15000)

                # If we're on homepage, look for recent articles
                if search_url == self.base_url:
                    article_selectors = [
                        "article h2 a, article h3 a",
                        ".entry-title a",
                        ".post-title a",
                        ".article-title a",
                        "h2 a[href*='/20']",  # Links with years (likely articles)
                        "h3 a[href*='/20']",
                    ]
                else:
                    # Search results page selectors
                    article_selectors = [
                        "article .entry-title a",
                        ".search-results article h2 a",
                        ".post .entry-title a",
                        ".search-result h2 a, .search-result h3 a",
                    ]

                urls = []
                for selector in article_selectors:
                    try:
                        article_links = await page.query_selector_all(selector)

                        for link in article_links:
                            href = await link.get_attribute("href")
                            title = await link.text_content()

                            if href and title and self._is_valid_article(href, title):
                                full_url = urljoin(self.base_url, href)
                                if full_url not in [item["url"] for item in urls]:
                                    urls.append(
                                        {
                                            "url": full_url,
                                            "title": title.strip(),
                                            "site": self.name,
                                        }
                                    )
                    except Exception as selector_error:
                        print(f"Selector '{selector}' failed: {selector_error}")
                        continue

                if urls:  # If we found articles, return them
                    print(f"Found {len(urls)} articles using {search_url}")
                    return urls

            except Exception as e:
                print(f"Error with URL {search_url}: {e}")
                continue

        return []

    def _is_valid_article(self, href, title):
        """Check if this is likely a real article"""
        skip_patterns = [
            "#",
            "javascript:",
            "mailto:",
            "/feed",
            "/category",
            "/tag",
            "/author",
        ]
        skip_titles = ["search", "archive", "home", "about", "contact", ""]

        return (
            not any(pattern in href.lower() for pattern in skip_patterns)
            and title.lower().strip() not in skip_titles
            and len(title.strip()) > 5
        )


class JusticeGovScraper(BaseScraper):
    """Scraper for Justice.gov"""

    def __init__(self):
        super().__init__("https://www.justice.gov", "Justice.gov")

    async def search(self, page, keywords):
        search_query = " ".join(keywords)
        # Use the correct search URL format for justice.gov
        search_url = f"https://search.justice.gov/search?query={search_query}&op=Search&affiliate=justice"

        try:
            await page.goto(search_url, wait_until="networkidle")
            await page.wait_for_timeout(3000)  # Wait for search results to load

            # More specific selectors for Justice.gov search results
            article_selectors = [
                ".result h3 a",
                ".search-result-item h3 a",
                ".gsc-result .gs-title a",
            ]

            urls = []
            for selector in article_selectors:
                article_links = await page.query_selector_all(selector)

                for link in article_links:
                    href = await link.get_attribute("href")
                    title = await link.text_content()

                    if href and title and self._is_valid_article(href, title):
                        # Ensure we have full URLs
                        if href.startswith("http"):
                            full_url = href
                        else:
                            full_url = urljoin(self.base_url, href)

                        if full_url not in [
                            item["url"] for item in urls
                        ]:  # Avoid duplicates
                            urls.append(
                                {
                                    "url": full_url,
                                    "title": title.strip(),
                                    "site": self.name,
                                }
                            )

            return urls
        except Exception as e:
            print(f"Error scraping {self.name}: {e}")
            return []

    def _is_valid_article(self, href, title):
        """Check if this is likely a real article"""
        skip_patterns = ["#", "javascript:", "mailto:", "/search"]
        skip_titles = ["search", "archive", "home", "about", "contact", ""]

        return (
            not any(pattern in href.lower() for pattern in skip_patterns)
            and title.lower().strip() not in skip_titles
            and len(title.strip()) > 10
            and "justice.gov" in href.lower()
        )


class GenericScraper(BaseScraper):
    """Generic fallback scraper for any website"""

    def __init__(self, base_url, name):
        super().__init__(base_url, name)

    async def search(self, page, keywords):
        """Generic search attempt - tries common search patterns"""
        search_query = " ".join(keywords)

        # Common search URL patterns to try
        search_patterns = [
            f"{self.base_url}/search?q={search_query}",
            f"{self.base_url}/search?query={search_query}",
            f"{self.base_url}/?s={search_query}",
        ]

        for search_url in search_patterns:
            try:
                await page.goto(search_url, wait_until="networkidle")

                # Generic selectors for article links
                selectors = [
                    "article a[href]",
                    ".article a[href]",
                    ".post a[href]",
                    "h1 a[href], h2 a[href], h3 a[href]",
                    ".entry-title a[href]",
                    ".title a[href]",
                ]

                urls = []
                for selector in selectors:
                    links = await page.query_selector_all(selector)
                    for link in links:
                        href = await link.get_attribute("href")
                        title = await link.text_content()
                        if href and self._is_article_link(href):
                            full_url = urljoin(self.base_url, href)
                            urls.append(
                                {
                                    "url": full_url,
                                    "title": title.strip() if title else "",
                                    "site": self.name,
                                }
                            )

                if urls:  # If we found articles, return them
                    return urls

            except Exception as e:
                print(f"Error trying search pattern {search_url}: {e}")
                continue

        return []

    def _is_article_link(self, href):
        """Basic heuristic to determine if a link might be an article"""
        # Skip navigation links, images, etc.
        skip_patterns = [
            "#",
            "javascript:",
            "mailto:",
            ".jpg",
            ".png",
            ".pdf",
            "/feed",
            "/category",
            "/tag",
            "/author",
            "/search",
            "/archive",
        ]
        return (
            not any(pattern in href.lower() for pattern in skip_patterns)
            and len(href) > 10
        )


class ArticleScraper:
    """Main scraper orchestrator"""

    def __init__(self):
        self.scrapers = {
            "www.undercurrentnews.com": UndercurrentNewsScraper(),
            "www.justice.gov": JusticeGovScraper(),
        }
        self.results = []

    def add_generic_scraper(self, url, name):
        """Add a generic scraper for a new site"""
        domain = urlparse(url).netloc.lower()
        self.scrapers[domain] = GenericScraper(url, name)

    async def scrape_site(self, site_url, keywords, name=None):
        """Scrape a single site for articles"""
        domain = urlparse(site_url).netloc.lower()
        # Use specific scraper if available, otherwise create generic one
        if domain in self.scrapers:
            scraper = self.scrapers[domain]
        else:
            scraper_name = name or domain
            scraper = GenericScraper(site_url, scraper_name)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = await context.new_page()

            try:
                print(f"Scraping {scraper.name}...")
                urls = await scraper.search(page, keywords)
                self.results.extend(urls)
                print(f"Found {len(urls)} articles on {scraper.name}")

                # Print first few results for debugging
                for i, url in enumerate(urls[:3]):
                    print(
                        f"  {i+1}. {url['title'][:60]}{'...' if len(url['title']) > 60 else ''}"
                    )

            except Exception as e:
                print(f"Error scraping {scraper.name}: {e}")
            finally:
                await browser.close()

    async def scrape_multiple_sites(self, sites, keywords):
        """Scrape multiple sites concurrently"""
        tasks = []
        for site in sites:
            if isinstance(site, dict):
                task = self.scrape_site(site["url"], keywords, site.get("name"))
            else:
                task = self.scrape_site(site, keywords)
            tasks.append(task)

        await asyncio.gather(*tasks)

    def save_results(self, filename="article_urls.json"):
        """Save results to JSON file"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_articles": len(self.results),
            "articles": self.results,
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Saved {len(self.results)} articles to {filename}")


async def main():
    parser = argparse.ArgumentParser(description="Scrape articles from websites")
    parser.add_argument("keywords", nargs="+", help="Keywords to search for")
    parser.add_argument("--sites", nargs="*", help="Additional sites to scrape")
    parser.add_argument(
        "--output", "-o", default="article_urls.json", help="Output JSON file"
    )

    args = parser.parse_args()

    scraper = ArticleScraper()

    # Default sites to scrape
    default_sites = [
        {"url": "https://www.undercurrentnews.com", "name": "Undercurrent News"},
        {"url": "https://www.justice.gov", "name": "Justice.gov"},
    ]

    # Add any additional sites
    sites = default_sites
    if args.sites:
        for site in args.sites:
            sites.append({"url": site, "name": urlparse(site).netloc})

    print(f"Searching for keywords: {', '.join(args.keywords)}")
    print(f"Sites to search: {[s['name'] for s in sites]}")

    await scraper.scrape_multiple_sites(sites, args.keywords)
    scraper.save_results(args.output)


if __name__ == "__main__":
    asyncio.run(main())
