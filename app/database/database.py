import os
from pymongo import AsyncMongoClient
from beanie import init_beanie
from app.models.iuu_models import IncidentReport
from dotenv import dotenv_values


config = dotenv_values(".env")

MONGO_URI = (
    f"mongodb://{config['MONGO_DB_USER']}:{config['MONGO_DB_PW']}" f"@localhost:27017/"
)


async def init_db():
    """
    Initializes the Beanie connection to the database.
    """
    client = AsyncMongoClient(os.getenv("MONGO_URI"))
    await init_beanie(
        database=client.get_database("iuuIncidents"),  # Use get_database() for clarity
        document_models=[IncidentReport],  # Pass all Beanie Documents here
    )
