from typing import Dict, List, Literal
import dspy
from pydantic import BaseModel, Field, ValidationError

# Pydantic models
class Species(BaseModel):
    """Model to represent a single species involved in an incident."""
    commonName: str = Field(..., description="The common name of the species (e.g., 'Bluefin Tuna').")
    scientificName: str = Field(..., description="The scientific name of the species (e.g., 'Thunnus thynnus').")
    productType: str | None = Field( default=None, description="Form of the product (e.g., 'Fins', 'Fillets', 'Whole'), if available.")
    liveWeight: str | None = Field( default=None, description="Weight of the species when alive, if specified (e.g., '100 kg'), if available.")
    processedWeight: str | None = Field( default=None, description="Weight of the processed product, if specified (e.g., '50 kg'), if available.")

class IUUClassifications(BaseModel):
    IUUType: Literal["Illegal Fishing",
                     "Unreported Catch",
                     "Unregulated Actors",
                     "Unregulated Areas or Stocks",
                     "Fraud or Mislabeling of Species",
                     "Fraud or Mislabeling of Production Info",
                     "Fraud or Mislabeling of Processing Info",
                     "Forced Labor or Labor Abuses"] = Field(...)
    IUUTypeReason: str = Field(..., description="Reason for the IUU incident, e.g., overfishing, habitat destruction")

class ExtractedIncidentData(BaseModel):
    """The structured information extracted from an article about an incident."""

    scopeOfArticle: str = Field(..., description="Is this about a single incident, multiple incidents, or a general overview?")

    # Who
    vesselName: str = Field(..., description="Name of the vessel involved")
    vesselUniqueID: str = Field(..., description="ID of the vessel involved")
    vesselFlag: str = Field(..., description="Flag state of the vessel involved")
    internationalRadioCallSign: str | None = Field( default=None, description="Call Sign of the vessel involved, if available")
    informationOnExporter: str | None = Field( default=None, description="information on exporter, if available")
    importCompany: str | None = Field( default=None, description="information on importer, if available")
    transshipmentDeclaration: str| None = Field( default=None, description= "Declaration of transshipment, if available")
    # When
    eventDate: str = Field(..., description="Date of the incident")
    # Where
    catchArea: str = Field(..., description="Area where the incident occurred")
    authoristionToFish: str | None = Field( default=None, description="Authorisation to fish in the area, if available")
    portOfLanding: str | None = Field( default=None, description="Port where the catch was landed, if available")
    processingLocation: str | None = Field( default=None, description="Location where the catch was processed, if available")
    countryOfIncident: str = Field(..., desc="Country where the incident occurred")
    latitude: str | None = Field( default=None, description="Latitude of the incident location, if available")
    longitude: str | None = Field( default=None, description="Longitude of the incident location, if available")
    # How
    fishingMethod: str | None = Field( default=None, description="Method of fishing used in the incident, if available")
    transitMode: str | None = Field( default=None, description="Mode of transit used in the incident, if available")
    # What
    speciesInvolved: List[Species] = Field(description="List of species involved in the incident")
    
    description: str = Field(description="Short summary of the incident")

class incidentClassification(BaseModel):
    """Model to represent the classification of an IUU incident."""
    
    eventCategory: str = Field(..., description="Categorize the primary event (e.g., 'Seizure', 'Arrest', 'Investigation Initiated', 'Fine Issued').")
    resolution: str = Field(..., description="What was the outcome or resolution, if mentioned? (e.g., 'Vessel Detained', 'Crew Fined $10,000', 'Charges Dropped').")
    iuuClassifications: List[IUUClassifications] = Field(..., description="A list of all applicable IUU classifications for the incident.")

class ArticleClassification(BaseModel):
    """Model to represent the classification of an article."""
    
    articleType: Literal["Single Incident", "Multiple Incidents", "Industry Overview", "Unrelated to IUU Fishing"] = Field(..., description="Type of article: Single Incident, Multiple Incidents, or General Overview.")
    confidence: float = Field(..., description="Confidence score for the classification, between 0 and 1.")

#Signatures for DSPy
class TextToStructuredData(dspy.Signature):
    """Signature to extract structured information from text."""
    
    text: str = dspy.InputField(desc="Text to extract Incident information from")
    extracted_data: ExtractedIncidentData = dspy.OutputField()

class StructuredDataToClassification(dspy.Signature):
    """Classifier for IUU incidents."""
    
    incident_summary: str = dspy.InputField(desc="Summary of the incident to classify")
    structured_data: str = dspy.InputField(desc="Structured data extracted from the incident")
    classification: incidentClassification = dspy.OutputField()

class CorrectionSignature(dspy.Signature):
    """
    Corrects a Pydantic object based on an error message and feedback.
    """
    original_object_json: str = dspy.InputField(desc="The original Pydantic object as a JSON string, which failed validation.")
    feedback: str = dspy.InputField(desc="The error message explaining why the object was incorrect.")
    corrected_object: Species = dspy.OutputField(desc="A new, corrected version of the Species object.")

class ArticleClassificationSignature(dspy.Signature):
    """
    Classifies an article based on its content.
    """
    article_text: str = dspy.InputField(desc="The text of the article to classify.")
    classification: ArticleClassification = dspy.OutputField(desc="The classification of the article, including type and confidence score.")

# DSPy Modules
class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""
    
    def __init__(self):
        super().__init__()

        self.extractor = dspy.ChainOfThought(TextToStructuredData)
        self.classifier = dspy.ChainOfThought(StructuredDataToClassification)

    def forward(self, article_text: str) -> Dict:
        """
        Extract structured information from the article text and classify the incident.
        """
        try:
            # Extract structured information
            extraction = self.extractor(text=article_text)
            
            # This output from the LLM could be a string OR already a Pydantic object
            structured_data_output = extraction.extracted_data

            # --- SOLUTION: Check the type before parsing ---
            if isinstance(structured_data_output, str):
                # If DSPy gave us a string, we need to parse it.
                try:
                    parsed_data = ExtractedIncidentData.model_validate_json(structured_data_output)
                except ValidationError as e:
                    print(f"Pydantic Validation Error: The LLM output string could not be parsed.")
                    print(f"LLM Output String: {structured_data_output}")
                    raise e
            elif isinstance(structured_data_output, ExtractedIncidentData):
                # If DSPy already did the work and gave us the object, just use it!
                parsed_data = structured_data_output
                # We will need a string version for the next step, so we create one.
                structured_data_string = parsed_data.model_dump_json()
            else:
                raise TypeError(f"Unexpected output type from extractor: {type(structured_data_output)}")

            # For the next step, ensure we have the string representation
            if 'structured_data_string' not in locals():
                structured_data_string = parsed_data.model_dump_json()

            # Classify the incident
            classification = self.classifier(
                incident_summary=parsed_data.description, 
                structured_data=structured_data_string
            )
            
            return {
                "extraction": extraction,
                "parsed_data": parsed_data,
                "classification": classification
            }
        except Exception as e:
            raise Exception(f"Error during extraction and classification: {str(e)}")


