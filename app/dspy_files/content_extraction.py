import app.dspy_files.functions as fn
from app.dspy_files.scraper import ArticleExtractionPipeline


class ContentExtractor:
    """Extracts text content from various sources like URLs, PDFs, and images."""

    def __init__(self):
        self.scraper = ArticleExtractionPipeline()

    async def from_url(self, url: str) -> tuple[str, str]:
        """Extracts cleaned text content from a URL."""
        article_object = await self.scraper.process_url(url=url)
        return article_object.clean_content, url

    def from_pdf(self, pdf_path: str) -> tuple[str, str]:
        """Extracts text from a PDF file."""
        return fn.read_pdf(pdf_path), pdf_path

    def from_image(self, image_path: str, language: str = "eng") -> tuple[str, str]:
        """Extracts text from an image file using OCR."""
        return fn.read_image(image_path, language=language), image_path
