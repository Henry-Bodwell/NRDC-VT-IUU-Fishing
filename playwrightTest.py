import asyncio
import json
import unicodedata
from playwright.async_api import async_playwright


def normalize_unicode(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            await page.goto("https://www.undercurrentnews.com/?s=illegal")
            await page.wait_for_selector("div.ucn-search-articles")

            # Get all search result containers
            results = await page.query_selector_all("div.ucn-search-entry")
            links = []
            for result in results:
                # Region
                region_elem = await result.query_selector("span.ucn-tag-gray a")
                region = await region_elem.inner_text() if region_elem else "N/A"

                # Date
                date_elem = await result.query_selector("span.ucn-search-date")
                date = await date_elem.inner_text() if date_elem else "N/A"

                # Article link and title
                link_elem = await result.query_selector("a[rel='bookmark']")
                link = await link_elem.get_attribute("href") if link_elem else "N/A"
                title = await link_elem.inner_text() if link_elem else "N/A"

                # Excerpt
                excerpt_elem = await result.query_selector("p.ucn-search-excerpt")
                excerpt = await excerpt_elem.inner_text() if excerpt_elem else "N/A"

                sub = {
                    "title": normalize_unicode(title),
                    "link": link,
                    "excerpt": normalize_unicode(excerpt),
                    "date": date,
                    "region": region,
                }
                links.append(sub)

        except Exception as e:
            print("Error:", e)
        finally:
            with open("article_urls.json", "w") as f:
                json.dump(links, f, indent=2)
            await browser.close()


asyncio.run(main())
