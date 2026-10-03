from fastapi import APIRouter
router = APIRouter()
@router.get("/")
async def root():
    return {
        "name": "App API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }

@router.get("/health")
async def health_check():
    return {"status": "ok"}