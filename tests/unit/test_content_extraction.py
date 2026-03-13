"""
Unit tests for content_extraction.py - Content extraction module.

Tests the ContentExtractor class which extracts text from:
- URLs (web articles)
- PDF files
- Images (OCR)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.dspy_files.content_extraction import ContentExtractor


def create_mock_source(
    url: str | None = None,
    article_text: str = "Test article text",
    title: str = "Test Title",
    author: str | None = None,
    input_category: str | None = None,
    status: str = "extracted",
):
    """Create a mock Source object."""
    mock_source = MagicMock()
    mock_source.url = url
    mock_source.article_text = article_text
    mock_source.article_title = title
    mock_source.author = author
    mock_source.input_category = input_category
    mock_source.status = status
    return mock_source


class TestContentExtractorInit:
    """Tests for ContentExtractor initialization."""

    @pytest.mark.unit
    def test_init_creates_scraper(self):
        """Test that ContentExtractor creates an ArticleExtractionPipeline."""
        with patch(
            "app.dspy_files.content_extraction.ArticleExtractionPipeline"
        ) as mock_pipeline:
            extractor = ContentExtractor(api_key="test-api-key")
            mock_pipeline.assert_called_once_with(api_key="test-api-key")
            assert extractor.scraper is not None


class TestContentExtractorFromUrl:
    """Tests for ContentExtractor.from_url() method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_from_url_returns_existing_source(self):
        """Test that from_url returns existing source if URL already in database."""
        existing_source = create_mock_source(
            url="https://example.com/existing",
            article_text="Existing article text",
        )

        with patch(
            "app.dspy_files.content_extraction.ArticleExtractionPipeline"
        ) as mock_pipeline:
            with patch("app.dspy_files.content_extraction.Source") as mock_source_class:
                mock_source_class.find_one = AsyncMock(return_value=existing_source)

                extractor = ContentExtractor(api_key="test-key")
                result = await extractor.from_url("https://example.com/existing")

        assert result is existing_source
        mock_pipeline.return_value.process_url.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_from_url_extracts_new_source(self):
        """Test that from_url extracts content from new URL."""
        new_source = create_mock_source(
            url="https://example.com/new-article",
            article_text="New article about fishing.",
        )

        with patch(
            "app.dspy_files.content_extraction.ArticleExtractionPipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value.process_url = AsyncMock(return_value=new_source)

            with patch("app.dspy_files.content_extraction.Source") as mock_source_class:
                mock_source_class.find_one = AsyncMock(return_value=None)

                extractor = ContentExtractor(api_key="test-key")
                result = await extractor.from_url("https://example.com/new-article")

        # Verify process_url was called
        mock_pipeline.return_value.process_url.assert_called_once_with(
            url="https://example.com/new-article"
        )

        # Verify source was updated
        assert result.input_category == "url"
        assert result.status == "extracted"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_from_url_raises_on_extraction_error(self):
        """Test that from_url raises exception on extraction failure."""
        with patch(
            "app.dspy_files.content_extraction.ArticleExtractionPipeline"
        ) as mock_pipeline:
            mock_pipeline.return_value.process_url = AsyncMock(
                side_effect=Exception("Network error")
            )

            with patch("app.dspy_files.content_extraction.Source") as mock_source_class:
                mock_source_class.find_one = AsyncMock(return_value=None)

                extractor = ContentExtractor(api_key="test-key")
                with pytest.raises(Exception, match="Network error"):
                    await extractor.from_url("https://example.com/failing")


class TestContentExtractorFromPdf:
    """Tests for ContentExtractor.from_pdf() static method."""

    @pytest.mark.unit
    def test_from_pdf_extracts_text(self):
        """Test that from_pdf extracts text from PDF bytes."""
        pdf_response = {
            "text": "This is the extracted PDF text about illegal fishing.",
            "metadata": {
                "author": "Test Author",
                "title": "Test PDF Title",
            },
        }

        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_pdf.return_value = pdf_response

            with patch("app.dspy_files.content_extraction.Source") as mock_source_class:
                mock_source_instance = MagicMock()
                mock_source_class.return_value = mock_source_instance

                ContentExtractor.from_pdf(b"fake pdf bytes")

        # Verify read_pdf was called
        mock_fn.read_pdf.assert_called_once_with(b"fake pdf bytes")

        # Verify Source was created with correct parameters
        mock_source_class.assert_called_once_with(
            article_text="This is the extracted PDF text about illegal fishing.",
            author="Test Author",
            article_title="Test PDF Title",
            input_category="pdf",
            status="extracted",
        )

    @pytest.mark.unit
    def test_from_pdf_raises_on_empty_text(self):
        """Test that from_pdf raises ValueError on empty text extraction."""
        pdf_response = {
            "text": "",
            "metadata": {},
        }

        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_pdf.return_value = pdf_response

            with pytest.raises(ValueError, match="Failed to extract text from PDF"):
                ContentExtractor.from_pdf(b"empty pdf bytes")

    @pytest.mark.unit
    def test_from_pdf_raises_on_whitespace_only_text(self):
        """Test that from_pdf raises ValueError when text is only whitespace."""
        pdf_response = {
            "text": "   \n\t  ",
            "metadata": {},
        }

        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_pdf.return_value = pdf_response

            with pytest.raises(ValueError, match="Failed to extract text from PDF"):
                ContentExtractor.from_pdf(b"whitespace pdf bytes")

    @pytest.mark.unit
    def test_from_pdf_raises_on_none_text(self):
        """Test that from_pdf raises ValueError when text is None."""
        pdf_response = {
            "text": None,
            "metadata": {},
        }

        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_pdf.return_value = pdf_response

            with pytest.raises(ValueError, match="Failed to extract text from PDF"):
                ContentExtractor.from_pdf(b"none text pdf bytes")

    @pytest.mark.unit
    def test_from_pdf_handles_missing_metadata(self):
        """Test that from_pdf handles PDFs without metadata."""
        pdf_response = {
            "text": "PDF text without metadata",
            "metadata": {},
        }

        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_pdf.return_value = pdf_response

            with patch("app.dspy_files.content_extraction.Source") as mock_source_class:
                mock_source_instance = MagicMock()
                mock_source_class.return_value = mock_source_instance

                ContentExtractor.from_pdf(b"no metadata pdf")

        # Verify Source was created with None for author/title
        mock_source_class.assert_called_once_with(
            article_text="PDF text without metadata",
            author=None,
            article_title=None,
            input_category="pdf",
            status="extracted",
        )

    @pytest.mark.unit
    def test_from_pdf_raises_on_read_error(self):
        """Test that from_pdf raises exception on PDF read failure."""
        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_pdf.side_effect = Exception("PDF corrupted")

            with pytest.raises(Exception, match="PDF corrupted"):
                ContentExtractor.from_pdf(b"corrupted pdf bytes")


class TestContentExtractorFromImage:
    """Tests for ContentExtractor.from_image() method."""

    @pytest.mark.unit
    def test_from_image_extracts_text(self):
        """Test that from_image extracts text using OCR."""
        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_image.return_value = "Extracted OCR text from image"

            text, path = ContentExtractor.from_image(
                "/path/to/image.png", language="eng"
            )

        mock_fn.read_image.assert_called_once_with("/path/to/image.png", language="eng")
        assert text == "Extracted OCR text from image"
        assert path == "/path/to/image.png"

    @pytest.mark.unit
    def test_from_image_uses_default_language(self):
        """Test that from_image uses English as default language."""
        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_image.return_value = "Text"

            ContentExtractor.from_image("/path/to/image.jpg")

        mock_fn.read_image.assert_called_once_with("/path/to/image.jpg", language="eng")

    @pytest.mark.unit
    def test_from_image_supports_different_languages(self):
        """Test that from_image supports different OCR languages."""
        with patch("app.dspy_files.content_extraction.fn") as mock_fn:
            mock_fn.read_image.return_value = "Spanish text"

            ContentExtractor.from_image("/path/to/spanish.png", language="spa")

        mock_fn.read_image.assert_called_once_with(
            "/path/to/spanish.png", language="spa"
        )
