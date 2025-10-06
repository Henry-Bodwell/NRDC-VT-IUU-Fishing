from webScraper import scrape_site
import asyncio

results = asyncio.run(
    scrape_site("doj_gov", "illegal fishing", max_results=10, headless=True)
)
print(results)
