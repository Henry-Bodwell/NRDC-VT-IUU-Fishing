import dspy
from app.models.incidents import IncidentReport
import app.dspy_files.functions as fn
import logging

logger = logging.getLogger(__name__)


def _convert_to_dict(obj):
    """Helper to convert Pydantic models to dictionaries."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj


def format_report(prediction: dspy.Prediction) -> IncidentReport | None:
    """Formats a dspy.Prediction object into a structured IncidentReport."""
    if not prediction:
        return None

    report_data = {
        "extracted_information": _convert_to_dict(
            getattr(prediction, "parsed_data", None)
        ),
        "incident_classification": _convert_to_dict(
            getattr(prediction, "incident_classification", None)
        ),
    }
    return IncidentReport(**report_data)


def verify_species_in_report(report: IncidentReport) -> IncidentReport:
    """
    Verifies scientific names in an IncidentReport against known species.
    Modifies the report in-place by adding a 'verified' flag to each species.
    """
    if not report or not report.extracted_information:
        logger.warning("No extracted information to verify.")
        return report

    species_list = report.extracted_information.speciesInvolved
    if not species_list:
        return report  # No species to verify

    for species in species_list:
        if not isinstance(species, dict):
            continue

        common_name = species.get("commonName")
        sci_name = species.get("predictedScientificName") or species.get(
            "scientificName"
        )

        if not common_name or not sci_name:
            species["verified"] = False
            continue

        try:
            is_verified = fn.verify_sci_name(common_name, sci_name)
            species["verified"] = is_verified
            logger.info(f"Verified {common_name} -> {sci_name}: {is_verified}")
        except Exception as e:
            logger.error(f"Could not verify {common_name}: {e}")
            species["verified"] = False

    return report
