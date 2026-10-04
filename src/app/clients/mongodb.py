from pymongo import MongoClient

from src.config import settings


def create_mongodb_client() -> MongoClient:
    """Create the MongoDB client used as the LangGraph checkpointer.

    Unlike immutable helpers elsewhere in this module, this client owns a
    connection pool and needs explicit shutdown. FastAPI lifespan therefore owns
    this instance instead of hiding it behind ``@lru_cache``.
    """
    return MongoClient(settings.MONGODB_CONNECTION_STRING)
