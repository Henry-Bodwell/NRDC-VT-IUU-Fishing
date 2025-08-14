import asyncio
import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import aiofiles


@dataclass
class ArticleData:
    url: str
    title: str
    description: str
    author: str
    publish_date: str
    content: str
    word_count: int
    extracted_at: str


class NewsArticleScraper:
    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        user_agent: str = None,
        delay: int = 1000,
    ):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.headless = headless
        self.timeout = timeout
        self.delay = delay
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

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
            user_agent=self.user_agent, viewport={"width": 1920, "height": 1080}
        )

    async def scrape_article(self, url: str) -> ArticleData:
        """Scrape a single news article."""
        if not self.browser:
            await self.initialize()

        page = await self.context.new_page()

        try:
            # Navigate to the article
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)

            # Wait for content to load
            await page.wait_for_timeout(2000)

            # Extract article data using JavaScript evaluation
            article_data = await page.evaluate(
                """
                () => {
                    // Strategy 1: Look for JSON-LD structured data
                    const jsonLdScript = document.querySelector('script[type="application/ld+json"]');
                    let jsonLdData = null;
                    
                    if (jsonLdScript) {
                        try {
                            const jsonData = JSON.parse(jsonLdScript.textContent);
                            if (jsonData['@type'] === 'NewsArticle' || jsonData['@type'] === 'Article') {
                                jsonLdData = jsonData;
                            } else if (Array.isArray(jsonData)) {
                                jsonLdData = jsonData.find(item => 
                                    item['@type'] === 'NewsArticle' || item['@type'] === 'Article'
                                );
                            }
                        } catch (e) {
                            console.warn('Failed to parse JSON-LD:', e.message);
                        }
                    }

                    // Strategy 2: Look for Open Graph and meta tags
                    const getMetaContent = (name) => {
                        const meta = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
                        return meta ? meta.getAttribute('content') : null;
                    };

                    // Strategy 3: Common article selectors
                    const articleSelectors = [
                        'article',
                        '[role="main"] article',
                        '.article-content',
                        '.post-content',
                        '.entry-content',
                        '.article-body',
                        '.story-body',
                        '.content-body',
                        'main article',
                        '.article-text'
                    ];

                    const titleSelectors = [
                        'h1',
                        '.article-title',
                        '.post-title',
                        '.entry-title',
                        '.headline',
                        'header h1'
                    ];

                    const contentSelectors = [
                        '.article-content p',
                        '.post-content p',
                        '.entry-content p',
                        '.article-body p',
                        '.story-body p',
                        '.content-body p',
                        'article p',
                        '.article-text p'
                    ];

                    // Extract title
                    let title = '';
                    if (jsonLdData && jsonLdData.headline) {
                        title = jsonLdData.headline;
                    } else {
                        title = getMetaContent('og:title') || 
                                getMetaContent('twitter:title') || 
                                document.title;
                        
                        // Try title selectors if meta tags don't work
                        if (!title || title === document.title) {
                            for (const selector of titleSelectors) {
                                const element = document.querySelector(selector);
                                if (element && element.textContent.trim()) {
                                    title = element.textContent.trim();
                                    break;
                                }
                            }
                        }
                    }

                    // Extract description/summary
                    let description = '';
                    if (jsonLdData && jsonLdData.description) {
                        description = jsonLdData.description;
                    } else {
                        description = getMetaContent('og:description') || 
                                     getMetaContent('twitter:description') || 
                                     getMetaContent('description');
                    }

                    // Extract publication date
                    let publishDate = '';
                    if (jsonLdData && jsonLdData.datePublished) {
                        publishDate = jsonLdData.datePublished;
                    } else {
                        publishDate = getMetaContent('article:published_time') || 
                                     getMetaContent('datePublished');
                    }

                    // Extract author
                    let author = '';
                    if (jsonLdData && jsonLdData.author) {
                        if (typeof jsonLdData.author === 'string') {
                            author = jsonLdData.author;
                        } else if (jsonLdData.author.name) {
                            author = jsonLdData.author.name;
                        }
                    } else {
                        author = getMetaContent('article:author') || 
                                getMetaContent('author');
                    }

                    // Extract main content
                    let content = '';
                    let contentElements = [];

                    // Try to find article container first
                    for (const selector of articleSelectors) {
                        const container = document.querySelector(selector);
                        if (container) {
                            contentElements = Array.from(container.querySelectorAll('p'));
                            break;
                        }
                    }

                    // If no article container found, try direct paragraph selectors
                    if (contentElements.length === 0) {
                        for (const selector of contentSelectors) {
                            contentElements = Array.from(document.querySelectorAll(selector));
                            if (contentElements.length > 0) break;
                        }
                    }

                    // Extract and clean text content
                    if (contentElements.length > 0) {
                        content = contentElements
                            .map(p => p.textContent.trim())
                            .filter(text => {
                                // Filter out short paragraphs, ads, and navigation text
                                return text.length > 50 && 
                                       !text.toLowerCase().includes('advertisement') &&
                                       !text.toLowerCase().includes('click here') &&
                                       !text.toLowerCase().includes('subscribe') &&
                                       !text.toLowerCase().includes('newsletter');
                            })
                            .join('\\n\\n');
                    }

                    // If still no content, try a more general approach
                    if (!content) {
                        const allParagraphs = Array.from(document.querySelectorAll('p'));
                        content = allParagraphs
                            .map(p => p.textContent.trim())
                            .filter(text => text.length > 100)
                            .slice(0, 20) // Take first 20 substantial paragraphs
                            .join('\\n\\n');
                    }

                    return {
                        url: window.location.href,
                        title: title.trim(),
                        description: description.trim(),
                        author: author.trim(),
                        publishDate: publishDate.trim(),
                        content: content.trim()
                    };
                }
            """
            )

            # Create ArticleData object
            word_count = (
                len(article_data["content"].split()) if article_data["content"] else 0
            )

            result = ArticleData(
                url=article_data["url"],
                title=article_data["title"],
                description=article_data["description"],
                author=article_data["author"],
                publish_date=article_data["publishDate"],
                content=article_data["content"],
                word_count=word_count,
                extracted_at=datetime.now().isoformat(),
            )

            return result

        except Exception as e:
            raise Exception(f"Failed to scrape article: {str(e)}")
        finally:
            await page.close()

    async def scrape_multiple_articles(
        self, urls: List[str], concurrency: int = 3, delay: int = None
    ) -> Tuple[List[ArticleData], List[Dict]]:
        """Scrape multiple articles with controlled concurrency."""
        if delay is None:
            delay = self.delay

        results = []
        errors = []

        # Process URLs in batches
        semaphore = asyncio.Semaphore(concurrency)

        async def scrape_with_semaphore(url: str, index: int) -> Optional[ArticleData]:
            async with semaphore:
                try:
                    # Add delay between requests
                    if index > 0:
                        await asyncio.sleep(delay / 1000)

                    print(f"Scraping: {url}")
                    result = await self.scrape_article(url)
                    print(f"✓ Scraped: {result.title[:50]}...")
                    return result
                except Exception as e:
                    print(f"✗ Failed to scrape {url}: {str(e)}")
                    errors.append({"url": url, "error": str(e)})
                    return None

        # Create tasks for all URLs
        tasks = [scrape_with_semaphore(url, index) for index, url in enumerate(urls)]

        # Execute all tasks
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful results
        for result in task_results:
            if isinstance(result, ArticleData):
                results.append(result)
            elif isinstance(result, Exception):
                errors.append({"url": "unknown", "error": str(result)})

        return results, errors

    async def save_to_file(self, data: List[ArticleData], filename: str):
        """Save scraped data to a JSON file."""
        json_data = [asdict(article) for article in data]

        async with aiofiles.open(filename, "w", encoding="utf-8") as f:
            await f.write(json.dumps(json_data, indent=2, ensure_ascii=False))

        print(f"Data saved to {filename}")

    async def close(self):
        """Close the browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright"):
            await self.playwright.stop()


# Analysis utilities
class ArticleAnalyzer:
    @staticmethod
    def analyze_articles(articles: List[ArticleData]) -> Dict:
        """Perform basic analysis on scraped articles."""
        if not articles:
            return {}

        total_words = sum(article.word_count for article in articles)
        avg_words = total_words / len(articles) if articles else 0

        # Find articles by word count
        longest = max(articles, key=lambda x: x.word_count)
        shortest = min(articles, key=lambda x: x.word_count)

        # Count articles by domain
        domains = {}
        for article in articles:
            try:
                domain = article.url.split("//")[1].split("/")[0]
                domains[domain] = domains.get(domain, 0) + 1
            except:
                pass

        return {
            "total_articles": len(articles),
            "total_words": total_words,
            "average_words": round(avg_words, 2),
            "longest_article": {
                "title": longest.title,
                "word_count": longest.word_count,
            },
            "shortest_article": {
                "title": shortest.title,
                "word_count": shortest.word_count,
            },
            "articles_by_domain": domains,
        }


# Usage example
async def main():
    """Example usage of the NewsArticleScraper."""

    # Example URLs (replace with real news article URLs)
    urls = [
        "https://example-news-site.com/article1",
        "https://example-news-site.com/article2",
        "https://example-news-site.com/article3",
    ]

    # Use the scraper with context manager for automatic cleanup
    async with NewsArticleScraper(headless=True, delay=1500) as scraper:
        try:
            # Scrape multiple articles
            print("Scraping articles...")
            results, errors = await scraper.scrape_multiple_articles(
                urls, concurrency=2, delay=2000
            )

            print(f"\nSuccessfully scraped {len(results)} articles")
            print(f"Failed to scrape {len(errors)} articles")

            if errors:
                print("\nErrors:")
                for error in errors:
                    print(f"  {error['url']}: {error['error']}")

            # Save results
            if results:
                await scraper.save_to_file(results, "scraped_articles.json")

                # Analyze results
                analysis = ArticleAnalyzer.analyze_articles(results)
                print(f"\n--- Analysis Summary ---")
                print(f"Total articles: {analysis['total_articles']}")
                print(f"Total words: {analysis['total_words']}")
                print(f"Average words per article: {analysis['average_words']}")
                print(
                    f"Longest article: {analysis['longest_article']['title']} ({analysis['longest_article']['word_count']} words)"
                )
                print(
                    f"Shortest article: {analysis['shortest_article']['title']} ({analysis['shortest_article']['word_count']} words)"
                )

                print(f"\nArticle titles:")
                for i, article in enumerate(results, 1):
                    print(f"{i}. {article.title} ({article.word_count} words)")

        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
