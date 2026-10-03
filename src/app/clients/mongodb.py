from pymongo import MongoClient

from src.config import settings


def create_mongodb_client() -> MongoClient:
    """Create the MongoDB client selected by the integrated FastAPI example.

    Unlike immutable helpers elsewhere in the blueprint, this client owns a
    connection pool and needs explicit shutdown. FastAPI lifespan therefore owns
    this instance instead of hiding it behind ``@lru_cache``. Projects choosing the
    SQLite/Postgres examples *could* delete this client and wire their selected saver.
    """
    return MongoClient(settings.MONGODB_CONNECTION_STRING)
