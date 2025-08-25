from typing import Dict
from app.dspy_files.external_apis import get_name_pairs
import pymupdf
import pytesseract
import pandas as pd
import logging

logger = logging.getLogger(__name__)


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


def read_pdf(pdf_byes: bytes) -> Dict[str, any]:
    """
    Extracts text and metadata from PDF using PyMuPDF.

    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename for logging/metadata

    Returns:
        Dictionary containing extracted text and metadata
    """
    try:
        doc = pymupdf.open(stream=pdf_byes, filetype="pdf")
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
            logger.warning(f"No text extracted from PDF")
            raise ValueError(
                "No text content found in PDF. Document may be scanned or image-based."
            )

        return {"text": full_text.strip(), "metadata": doc_info}
    except IOError:
        logger.error(f"IO Exception when reading pdf bytes")
        raise


def read_image(file_path: str, language: str = "eng") -> str:
    """
    Read the content of an image file and return it as a string.

    Args:
        file_path (str): The path to the image file.

    Returns:
        str: The text content extracted from the image using OCR.
    """

    text = pytesseract.image_to_string(file_path, lang=language)
    return text.strip()


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
