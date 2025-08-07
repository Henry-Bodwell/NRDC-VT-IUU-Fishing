from app.models.articles import Source
from app.models.incidents import IncidentReport

Source.model_rebuild()
IncidentReport.model_rebuild()
