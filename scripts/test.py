from webScraper.scrapers.generic_scraper import GenericScraper

import asyncio


async def main():
    scraper = GenericScraper("doj_gov", headless=False)
    results = await scraper.scrape("illegal fishing", max_results=15)
    print(results)


asyncio.run(main())
