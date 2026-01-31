from typing import Dict
from pdf2image import convert_from_bytes
from app.dspy_files.external_apis import get_name_pairs
import fitz
import pytesseract
import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)


def clean_extracted_text(text: str) -> str:
    """
    Clean extracted text by normalizing whitespace and removing excessive newlines.

    Args:
        text: Raw extracted text

    Returns:
        Cleaned text with normalized spacing
    """
    # Replace multiple newlines with double newline (paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Replace single newlines with spaces (join broken lines)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    # Replace multiple spaces with single space
    text = re.sub(r" {2,}", " ", text)

    # Replace tabs with spaces
    text = text.replace("\t", " ")

    # Remove spaces at the beginning and end of lines
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Remove empty lines that are just whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text)

    return text.strip()


def verify_sci_name(common_name: str, predicted_sci_name: str) -> bool:
    """
    Verify if the predicted scientific name matches any scientific name for the given common name.

    Args:
        common_name (str): The common name of the species.
        predicted_sci_name (str): The predicted scientific name to verify.

    Returns:
        bool: True if the predicted scientific name matches any known scientific names, False otherwise.
    """
    name_pairs = get_name_pairs(common_name)
    for sci_name, _ in name_pairs:
        if sci_name.lower() == predicted_sci_name.lower():
            return True
    return False


def extract_text_pdf(pdf_bytes: bytes) -> Dict[str, any]:
    """
    Extracts text and metadata from PDF using PyMuPDF.

    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename for logging/metadata

    Returns:
        Dictionary containing extracted text and metadata
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text = ""

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            full_text += page_text

        metadata = doc.metadata
        doc_info = {
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "date": metadata.get("creationDate", ""),
            "modification_date": metadata.get("modDate", ""),
            "total_pages": len(doc),
        }

        doc.close()
        if not full_text.strip():
            logger.warning("No text extracted from PDF")
            raise ValueError(
                "No text content found in PDF. Document may be scanned or image-based."
            )

        # Clean the extracted text to remove excessive newlines and formatting
        cleaned_text = clean_extracted_text(full_text)

        return {"text": cleaned_text, "metadata": doc_info}
    except IOError:
        logger.error("IO Exception when reading pdf bytes")
        raise


def ocr_pdf_with_pytesseract(pdf_bytes: bytes) -> Dict[str, any]:
    """
    Performs OCR on each page of a scanned PDF and extracts text.

    Args:
        pdf_bytes (bytes): The raw bytes of the PDF file.
        language (str): Language(s) to use for OCR.

    Returns:
        Dict[str, any]: Extracted text and basic metadata.
    """
    try:
        images = convert_from_bytes(pdf_bytes)
        full_text = ""

        for idx, image in enumerate(images):
            page_text = pytesseract.image_to_string(image).strip()
            full_text += f"\n\n--- Page {idx + 1} ---\n" + page_text

        if not full_text.strip():
            logger.warning("No text extracted via OCR from PDF.")
            raise ValueError("OCR found no readable text in the PDF.")

        metadata = {"total_pages": len(images), "ocr": True}

        # Clean the extracted text to remove excessive newlines and formatting
        cleaned_text = clean_extracted_text(full_text)

        return {"text": cleaned_text, "metadata": metadata}

    except Exception as e:
        logger.error(f"OCR failed on scanned PDF: {e}")
        raise


def needs_ocr_sampled(
    pdf_bytes: bytes, sample_pages: int = 3, min_text_length: int = 10
) -> bool:
    """
    Check the first few pages of a PDF to determine if OCR is likely needed.

    Args:
        pdf_bytes (bytes): PDF content.
        sample_pages (int): Number of pages to sample.
        min_text_length (int): Minimum total text length to assume it's not scanned.

    Returns:
        bool: True if OCR is likely needed, False otherwise.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        pages_to_check = min(sample_pages, total_pages)

        total_text = ""
        for i in range(pages_to_check):
            page = doc[i]
            text = page.get_text().strip()
            total_text += text

        doc.close()

        return len(total_text) < min_text_length

    except fitz.FileDataError as e:
        logger.error(f"Invalid or corrupted PDF file: {e}")
        raise ValueError("PDF file is corrupted or invalid")
    except Exception as e:
        logger.warning(f"Error checking PDF text content, defaulting to OCR: {e}")
        # If we can't determine, assume OCR is needed as a fallback
        return True


def read_pdf(pdf_bytes: bytes) -> Dict[str, any]:
    if needs_ocr_sampled(pdf_bytes):
        logger.info("PDF appears to be scanned; using OCR.")
        return ocr_pdf_with_pytesseract(pdf_bytes)
    else:
        logger.info("PDF appears to contain text; using text extraction.")
        return extract_text_pdf(pdf_bytes)


def verify_name_against_asfis(common_name: str, predicted_sci_name: str) -> bool:
    """
    Verify the scientific name against the ASFI database.

    Args:
        common_name (str): The common name of the species.
        predicted_sci_name (str): The predicted scientific name to verify.

    Returns:
        bool: True if the scientific name is verified, False otherwise.
    """

    asfis = pd.read_csv("data/ASFIS_sp_2025.csv")

    if predicted_sci_name.lower() in asfis["Scientific Name"].str.lower().values:
        return
