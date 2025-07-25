from external_apis import get_name_pairs
from pypdf import PdfReader
import pytesseract
import pandas as pd


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


def read_pdf(file_path: str) -> str:
    """
    Read the content of a PDF file and return it as a string.

    Args:
        file_path (str): The path to the PDF file.

    Returns:
        str: The text content of the PDF file.
    """
    reader = PdfReader(file_path)
    text = ""

    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text.strip()


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
