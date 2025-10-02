"""
Web Scraper - Multi-purpose web scraping tool.

A flexible, configuration-driven web scraping framework built with Playwright and Python.

Quick Start:
    from scrapers import scrape_site
    import asyncio

    results = asyncio.run(scrape_site('doj_gov', 'illegal fishing', max_results=10))

For more information, see the documentation in the README files.
"""

__version__ = "0.2.0"  # Phase 2 complete
__author__ = "Henry Bodwell"
__license__ = "MIT"

# Optional: Expose most commonly used functions at package root
from webScraper.scrapers import scrape_site, GenericScraper, BaseScraper
from webScraper.config import get_site_config, get_config_manager

__all__ = [
    "scrape_site",
    "GenericScraper",
    "BaseScraper",
    "get_site_config",
    "get_config_manager",
]
