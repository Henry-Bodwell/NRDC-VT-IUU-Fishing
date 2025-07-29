import os
from pymongo import AsyncMongoClient
from beanie import init_beanie
from app.models.iuu_models import IncidentReport



MONGO_URI = os.getenv("MONGO_URI")


async def init_db():
    """
    Initializes the Beanie connection to the database.
    """

    if not MONGO_URI:
        raise ValueError("MONGO_URI environment variable is not set")
    client = AsyncMongoClient(MONGO_URI)
    
    await init_beanie(
        database=client.get_database("iuuIncidents"),  # Use get_database() for clarity
        document_models=[IncidentReport],  # Pass all Beanie Documents here
    )
