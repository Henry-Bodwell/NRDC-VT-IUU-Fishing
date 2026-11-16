from app.models.sources import Source
from app.models.incidents import IncidentReport, IndustryOverview
from app.dspy_files.news_analysis import PipelineOutput
from app.models.clusters import Cluster

Source.model_rebuild()
IndustryOverview.model_rebuild()
IncidentReport.model_rebuild()
PipelineOutput.model_rebuild()
Cluster.model_rebuild()
