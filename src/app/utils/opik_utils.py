import opik
from loguru import logger

from src.config import settings


def configure() -> None:
    """Configure the observability backend selected by the FastAPI example.

    This active assembly fails at startup when its required Opik settings are
    missing instead of discovering the problem on the first chat request. An
    inherited project that does not use Opik should remove this startup dependency,
    its tracer wiring, and the prompt integration together.
    """
    if not settings.COMET_API_KEY or not settings.COMET_PROJECT:
        raise RuntimeError("COMET_API_KEY and COMET_PROJECT are required for Opik")

    opik.configure(
        api_key=settings.COMET_API_KEY,
        project_name=settings.COMET_PROJECT,
        use_local=False,
        force=True,
    )
    logger.info(f"Opik configured successfully for project '{settings.COMET_PROJECT}'")
