import json
from pydantic import BaseModel
from app.models.articles import Source
from app.models.incidents import IncidentReport


source_schema = Source.model_json_schema()
with open("source_schema.json", "w") as f:
    json.dump(source_schema, f, indent=2)
incident_schema = IncidentReport.model_json_schema()
with open("incident_schema.json", "w") as f:
    json.dump(incident_schema, f, indent=2)
