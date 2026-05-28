from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any


class MessageSchema(BaseModel):
    """Schema for a single message in conversation history."""

    role: str = Field(..., description="Role of the message sender: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequestSchema(BaseModel):
    """Schema for chat request from backend."""

    messages: List[MessageSchema] = Field(..., description="Conversation history")
    temperature: Optional[float] = Field(None, description="Temperature for randomness (0-2)")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens in response")


class ChatResponseSchema(BaseModel):
    """Schema for chat response to backend."""

    response: str = Field(..., description="AI response message")
    model: str = Field(..., description="Model used for response")
    tokens_used: Optional[Dict[str, int]] = Field(None, description="Token usage statistics")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class HealthCheckSchema(BaseModel):
    """Schema for health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    ai_service_ready: bool = Field(..., description="Whether AI service is ready")
