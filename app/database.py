import os
from pymongo import AsyncMongoClient
from beanie import init_beanie

from app.models.incidents import IndustryOverview


MONGO_URI = os.getenv("MONGO_URI")


async def init_db():
    """
    Initializes the Beanie connection to the database.
    """
    from app.models.articles import Source
    from app.models.incidents import IncidentReport

    if not MONGO_URI:
        raise ValueError("MONGO_URI environment variable is not set")
    client = AsyncMongoClient(MONGO_URI)

    await init_beanie(
        database=client.get_database("iuuIncidents"),  # Use get_database() for clarity
        document_models=[
            IncidentReport,
            Source,
            IndustryOverview,
        ],  # Pass all Beanie Documents here
    )
    print("Database initialized successfully.")
