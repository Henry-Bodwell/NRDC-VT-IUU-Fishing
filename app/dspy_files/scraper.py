import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup, Comment, Tag
from typing import List, Set
import dspy
from app.dspy_files.signatures import CleanArticleContent
from app.models.articles import ArticleData


class ContentFilter:
    """
    A general-purpose HTML cleaner that filters content in stages,
    reverting to the previous stage if any step removes too much content.
    """

    MIN_CONTENT_LENGTH = 150  # A bit higher to be safer

    def __init__(self):
        # Stage 1 Targets: Core structural junk
        self.structural_junk_tags: Set[str] = {"nav", "header", "footer", "aside"}
        # Stage 3 Targets: Ads, social widgets, recommendations, etc.
        self.pattern_junk_tags: Set[str] = {"figure", "form", "input", "button"}
        self.unwanted_patterns: Set[str] = {
            "advertisement",
            "ad-",
            "ads-",
            "banner",
            "promo",
            "promotion",
            "sidebar",
            "widget",
            "social",
            "share",
            "comment",
            "related",
            "recommended",
            "trending",
            "popular",
            "navigation",
            "nav-",
            "menu",
            "breadcrumb",
            "logo",
            "brand",
            "cookie",
            "popup",
            "modal",
            "overlay",
            "subscription",
            "newsletter",
            "signup",
            "login",
            "search",
            "filter",
            "pagination",
            "pager",
            "tags",
            "category",
            "metadata",
        }
        # Stage 2 Targets: Embedded media that isn't text
        self.media_junk_tags: Set[str] = {
            "script",
            "style",
            "iframe",
            "embed",
            "object",
            "video",
            "audio",
            "canvas",
            "svg",
            "img",
        }

    def _has_unwanted_pattern(self, element: Tag) -> bool:
        """Check if an element has unwanted class or id patterns."""
        classes = element.get("class", [])
        element_id = element.get("id", "")
        text_to_check = " ".join(classes) + " " + element_id
        return any(
            pattern in text_to_check.lower() for pattern in self.unwanted_patterns
        )

    def _run_stage(
        self, stage_name: str, soup: BeautifulSoup, last_successful_html: str, action
    ) -> str:
        """Helper to run a filtering stage and check the result."""
        print(f"Running Stage: {stage_name}...")
        action(soup)
        if len(soup.get_text(strip=True)) < self.MIN_CONTENT_LENGTH:
            print(f"Stage '{stage_name}' removed too much content. Reverting.")
            return last_successful_html
        return str(soup)

    def filter_content(self, soup: BeautifulSoup) -> str | None:
        """
        Simplifies HTML in stages, falling back to the previous good version if a
        step is too aggressive.
        """
        original_html = str(soup)
        last_successful_html = original_html
        soup_copy = BeautifulSoup(original_html, "html.parser")

        # --- Stage 1: Remove core structural junk (nav, header, footer) ---
        def stage1_action(s):
            for tag_name in self.structural_junk_tags:
                for tag in list(s.find_all(tag_name)):
                    tag.decompose()

        last_successful_html = self._run_stage(
            "Remove Structural Junk", soup_copy, last_successful_html, stage1_action
        )
        soup_copy = BeautifulSoup(last_successful_html, "html.parser")

        # --- Stage 2: Remove media and scripts ---
        def stage2_action(s):
            for tag_name in self.media_junk_tags:
                for tag in list(s.find_all(tag_name)):
                    tag.decompose()
            for comment in s.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()

        last_successful_html = self._run_stage(
            "Remove Media & Scripts", soup_copy, last_successful_html, stage2_action
        )
        soup_copy = BeautifulSoup(last_successful_html, "html.parser")

        # --- Stage 3: Remove pattern-based junk (ads, widgets, social) ---
        def stage3_action(s):
            for tag_name in self.pattern_junk_tags:
                for tag in list(s.find_all(tag_name)):
                    tag.decompose()
            for element in list(s.find_all(True)):
                if (
                    element.parent is not None
                    and isinstance(element, Tag)
                    and self._has_unwanted_pattern(element)
                ):
                    element.decompose()

        last_successful_html = self._run_stage(
            "Remove Pattern Junk", soup_copy, last_successful_html, stage3_action
        )
        soup_copy = BeautifulSoup(last_successful_html, "html.parser")

        # --- Final Processing on the best result we have so far ---
        print("Filtering complete. Preparing final HTML for LLM.")
        body = soup_copy.find("body")
        if not body:
            return original_html  # Should be very rare

        # Clean up links and non-essential tags
        for link in body.find_all("a"):
            link.unwrap()  # Replaces the link tag with its text content

        structural_tags = {
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "blockquote",
            "li",
            "ul",
            "ol",
            "br",
        }
        for child in list(body.find_all()):
            if child.name not in structural_tags:
                child.unwrap()  # Replaces non-structural tags with their content

        return str(body)


class WebScraper:
    """Simple web scraper with proper headers"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def fetch_page(self, url: str) -> BeautifulSoup:
        """Fetch and parse webpage"""
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return BeautifulSoup(response.content, "html.parser")
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch URL {url}: {str(e)}")


class ArticleExtractionPipeline:
    """Flexible pipeline: URL -> Filtered HTML -> Clean Text"""

    def __init__(self, model="openai/gpt-4o-mini", api_key: str = None):
        self.scraper = WebScraper()
        self.filter = ContentFilter()

        self.lm = dspy.LM(model, api_key=api_key)
        dspy.settings.configure(lm=self.lm)
        self.cleaner = dspy.ChainOfThought(CleanArticleContent)

    def extract_title(self, soup: BeautifulSoup) -> str | None:
        """Extract article title"""
        title_selectors = [
            "h1",
            "title",
            '[property="og:title"]',
            ".article-title",
            ".post-title",
            ".entry-title",
        ]

        for selector in title_selectors:
            element = soup.select_one(selector)
            if element:
                if selector == '[property="og:title"]':
                    title = element.get("content", "")
                else:
                    title = element.get_text(strip=True)

                if title and len(title) > 5:
                    return title
        return None

    async def process_url(self, url: str) -> ArticleData:
        """Main pipeline: URL -> Filtered HTML -> Clean Text"""

        try:
            # Step 1: Fetch the webpage
            print(f"Fetching: {url}")
            soup = self.scraper.fetch_page(url)

            # Step 2: Extract title
            title = self.extract_title(soup)
            print(f"Title: {title}")

            # Step 3: Filter content to textual HTML
            print("Filtering content...")
            filtered_html = self.filter.filter_content(soup)

            if not filtered_html:
                raise ValueError("Could not extract meaningful content after filtering")

            print(f"Filtered HTML length: {len(filtered_html)} characters")
            # Step 4: Use DSPy to clean the filtered HTML into readable text
            clean_content = filtered_html  # Fallback

            try:
                print("Processing with DSPy...")
                result = await self.cleaner.acall(filtered_html=filtered_html)
                clean_content = result.clean_article
                print("DSPy processing complete")
            except Exception as e:
                print(f"DSPy processing failed, using filtered HTML: {e}")
                # Convert HTML to text as fallback
                fallback_soup = BeautifulSoup(filtered_html, "html.parser")
                clean_content = fallback_soup.get_text(separator="\n\n", strip=True)

            # Step 5: Create validated result
            article_data = ArticleData(
                url=url,
                title=title,
                raw_html=filtered_html,
                clean_content=clean_content,
            )

            return article_data

        except Exception as e:
            raise Exception(f"Pipeline failed for {url}: {str(e)}")

    def process_multiple_urls(self, urls: List[str]) -> List[ArticleData]:
        """Process multiple URLs"""
        results = []

        for i, url in enumerate(urls, 1):
            print(f"\n--- Processing {i}/{len(urls)} ---")
            try:
                article = self.process_url(url)
                results.append(article)
            except Exception as e:
                print(f"Failed to process {url}: {e}")

        return results


# Usage examples
if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    url = "https://cbcgdf.wordpress.com/2024/08/07/beijing-customs-intercepted-at-the-capital-airport-a-box-of-oahu-tree-snail-shells-cbcgdf-expert-shen-yihang-reports/"

    pipeline = ArticleExtractionPipeline(api_key=api_key)

    result = pipeline.process_url(url)
    # You can now access the full result object
    print("\n--- Clean Content ---")
    print(result.clean_content)
