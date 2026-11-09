import os
from pymongo import AsyncMongoClient
from beanie import init_beanie

from app.audit.models import AuditLog
from app.models.incidents import IndustryOverview
from app.models.task import TaskStatus

MONGO_URI = os.getenv("MONGO_URI")


async def init_db():
    """
    Initializes the Beanie connection to the database.
    """
    from app.models.sources import Source
    from app.models.incidents import IncidentReport
    from app.models.users import User
    from app.models.validation import ValidationSession
    from app.models.duplicates import DuplicateCandidate
    from app.models.clusters import Cluster

    if not MONGO_URI:
        raise ValueError("MONGO_URI environment variable is not set")
    client = AsyncMongoClient(MONGO_URI)

    await init_beanie(
        database=client.get_database("iuuIncidents"),
        document_models=[
            IncidentReport,
            Source,
            IndustryOverview,
            AuditLog,
            TaskStatus,
            User,
            ValidationSession,
            DuplicateCandidate,
            Cluster,
        ],  # Pass all Beanie Documents here
    )
    print("Database initialized successfully.")

    # Ensure the vector-store collection exists for the chunking/RAG path.
    # Non-fatal: ingestion falls back to the full-text path if the vector store
    # is unavailable, and VectorStore also ensures the collection lazily.
    try:
        from app.rag.vector_store import get_document_store, get_vector_store

        await get_vector_store().ensure_collection()
        await get_document_store().ensure_collection()
        print("Vector store (Qdrant) collections ensured.")
    except Exception as e:
        print(f"Warning: could not ensure vector store collection: {e}")
