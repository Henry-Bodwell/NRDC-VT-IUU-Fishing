import json
from pydantic import BaseModel

import extraction_schemas


class Schema(BaseModel):
    """
    Schema for IUU Fishing Incident Data.
    """

    source: extraction_schemas.BaseIntake
    extracted_information: extraction_schemas.ExtractedIncidentData
    incident_classification: extraction_schemas.IncidentClassification


schema = Schema.model_json_schema()
with open("webscraping/schema.json", "w") as f:
    json.dump(schema, f, indent=2)
