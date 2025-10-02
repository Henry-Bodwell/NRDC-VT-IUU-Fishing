"""
Scrapers package for web scraping.

This package contains the base scraper and site-specific scraper implementations.
"""

from webScraper.scrapers.base_scraper import (
    BaseScraper,
    ScraperStatus,
    SearchResult,
    ScrapedContent,
)

from webScraper.scrapers.generic_scraper import GenericScraper, scrape_site

__all__ = [
    # Base scraper
    "BaseScraper",
    "ScraperStatus",
    "SearchResult",
    "ScrapedContent",
    # Generic scraper
    "GenericScraper",
    "scrape_site",
]
