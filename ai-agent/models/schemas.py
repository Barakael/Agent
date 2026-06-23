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
    tool_actions: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Tool actions executed during agent chat",
    )


class AgentChatRequestSchema(BaseModel):
    """Schema for agent chat request with computer tools."""

    messages: List[MessageSchema] = Field(..., description="Conversation history")
    task_id: Optional[str] = Field(None, description="Optional task id for tracing")
    max_tool_rounds: Optional[int] = Field(None, description="Maximum tool execution rounds")


class HealthCheckSchema(BaseModel):
    """Schema for health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    ai_service_ready: bool = Field(..., description="Whether AI service is ready")


class TaskPlanRequestSchema(BaseModel):
    goal: str = Field(..., description="Task goal")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional planning context")


class TaskPlanResponseSchema(BaseModel):
    task_id: str = Field(..., description="Generated task id")
    plan_steps: List[str] = Field(..., description="Generated execution steps")
    status: str = Field(..., description="Planning status")


class TaskExecuteRequestSchema(BaseModel):
    task_id: str = Field(..., description="Task id from planning endpoint")
    goal: str = Field(..., description="Task goal")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Execution context")


class TaskExecuteResponseSchema(BaseModel):
    task_id: str = Field(..., description="Task id")
    status: str = Field(..., description="Execution state")
    summary: str = Field(..., description="Result summary")
    trace_id: str = Field(..., description="Execution trace id")


class TaskStatusResponseSchema(BaseModel):
    task_id: str = Field(..., description="Task id")
    status: str = Field(..., description="Current execution state")
    trace_id: Optional[str] = Field(default=None, description="Trace id for execution")
    logs: List[str] = Field(default_factory=list, description="Task logs")


class ToolExecutionRequestSchema(BaseModel):
    task_id: str = Field(..., description="Associated task id")
    tool: str = Field(..., description="Tool namespace")
    action: str = Field(..., description="Action name")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Tool payload")


class ToolExecutionResponseSchema(BaseModel):
    status: str = Field(..., description="Execution status")
    output: Dict[str, Any] = Field(default_factory=dict, description="Execution output")
    trace_id: str = Field(..., description="Trace id")


class TradingDailyAnalysisResponseSchema(BaseModel):
    decision: str = Field(..., description="GO or NO-GO")
    summary: str = Field(..., description="Narrative summary")
    reasons: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)


class VoiceTranscribeResponseSchema(BaseModel):
    text: str = Field(..., description="Transcribed speech text")


class VoiceSpeakRequestSchema(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096, description="Text to synthesize")


class RunnerStatusSchema(BaseModel):
    runner_enabled: bool = Field(..., description="Whether runner delegation is enabled")
    online: bool = Field(..., description="Whether runner health check passed")
    platform: Optional[str] = Field(None, description="Runner OS platform when online")
