from webScraper.scrapers.sites.oceana_scraper import scrape_oceana

import asyncio


async def main():
    results = await scrape_oceana("illegal fishing", max_results=2, headless=False)
    print(results)


asyncio.run(main())
