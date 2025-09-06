from typing import Dict
import app.dspy_files.functions as fn
from app.dspy_files.scraper import ArticleExtractionPipeline
from app.models.articles import Source
import logging

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Extracts text content from various sources like URLs, PDFs, and images."""

    def __init__(self, api_key: str):
        self.scraper = ArticleExtractionPipeline(api_key=api_key)

    async def from_url(self, url: str) -> Source:
        """Extracts cleaned text content from a URL."""
        try:
            existing_source = await Source.find_one(Source.url == url)
            if existing_source:
                logging.warning(f"Source already exists for URL: {url}")
                return existing_source

            prediction = await self.scraper.process_url(url=url)
            source = prediction.source
            source.url = url
            source.category = "url"

            logger.info(f"Successfully extracted content from: {url}")

            return source

        except Exception as e:
            logger.error(f"Failed to extract content from {url}: {e}")
            raise

    @staticmethod
    def from_pdf(pdf_bytes: bytes) -> Source:
        """Extracts text from a PDF file."""
        response = fn.read_pdf(pdf_bytes)
        text = response.get("text")
        author = response.get("metadata", {}).get("author")
        title = response.get("metadata", {}).get("title")
        # date = response.get("metadata", {}).get("date")
        source = Source(
            article_text=text, author=author, article_title=title, category="pdf"
        )
        logger.info(f"Source from PDF: {source}")
        return source

    @staticmethod
    def from_image(self, image_path: str, language: str = "eng") -> tuple[str, str]:
        """Extracts text from an image file using OCR."""
        return fn.read_image(image_path, language=language), image_path
