from pydantic import BaseModel

# Define request/response structures
class ChatRequest(BaseModel):
    message: str
    thread_id: str  # Kept for future multi-turn memory setup

class ChatResponse(BaseModel):
    response: str