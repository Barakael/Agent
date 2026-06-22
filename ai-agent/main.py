import logging

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings
from models.schemas import (
    AgentChatRequestSchema,
    ChatRequestSchema,
    ChatResponseSchema,
    HealthCheckSchema,
    TaskExecuteRequestSchema,
    TaskExecuteResponseSchema,
    TaskPlanRequestSchema,
    TaskPlanResponseSchema,
    TaskStatusResponseSchema,
    ToolExecutionRequestSchema,
    ToolExecutionResponseSchema,
    TradingDailyAnalysisResponseSchema,
)
from services.ai_service import AIService
from services.trading_analysis import synthesize_daily_analysis

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ai-agent")

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

def validate_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> bool:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or credentials.credentials != settings.AI_SERVICE_API_KEY
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def validate_approval_token(approval_token: str | None) -> bool:
    if not settings.TOOL_APPROVAL_TOKEN:
        logger.error("TOOL_APPROVAL_TOKEN is not configured")
        raise HTTPException(status_code=503, detail="Approval token workflow not configured")
    if approval_token != settings.TOOL_APPROVAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid approval token")
    return True

@app.on_event("startup")
async def startup_event():
    if not settings.AI_SERVICE_API_KEY:
        logger.error("AI_SERVICE_API_KEY not configured")
        raise ValueError("AI_SERVICE_API_KEY environment variable is required")

    try:
        app.state.ai_service = AIService()
        app.state.ai_service_ready = app.state.ai_service.health_check()
        allowed = AIService._allowed_tool_actions()
        logger.info("Allowed tool actions: %s", ", ".join(sorted(allowed)))
        if "cursor.prompt" in allowed:
            logger.info("Cursor prompt integration enabled")
        else:
            logger.warning("cursor.prompt is missing from ALLOWED_TOOL_ACTIONS")
    except Exception as exc:
        app.state.ai_service = None
        app.state.ai_service_ready = False
        logger.error("AI service failed to initialize: %s", exc)

@app.get("/", response_class=JSONResponse)
async def root():
    return {"message": "Agent AI Service is running"}

@app.get("/health", response_model=HealthCheckSchema)
async def health_check(auth: bool = Depends(validate_api_key)):
    return HealthCheckSchema(
        status="ok",
        version=settings.API_VERSION,
        ai_service_ready=bool(getattr(app.state, "ai_service_ready", False)),
    )

@app.post("/chat", response_model=ChatResponseSchema)
async def chat(request: ChatRequestSchema, auth: bool = Depends(validate_api_key)):
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        logger.error("AI service is not initialized")
        raise HTTPException(status_code=503, detail="AI service not available")

    payload = request.model_dump()
    messages = payload.get("messages", [])

    if ai_service.should_truncate_context(messages):
        messages = ai_service.truncate_context(messages)

    try:
        result = ai_service.chat(
            messages=messages,
            temperature=payload.get("temperature"),
            max_tokens=payload.get("max_tokens"),
        )
        return ChatResponseSchema(**result)
    except Exception as exc:
        logger.exception("Failed to process chat request")
        raise HTTPException(status_code=502, detail="AI API request failed")


@app.post("/chat/agent", response_model=ChatResponseSchema)
async def agent_chat(
    request: AgentChatRequestSchema,
    auth: bool = Depends(validate_api_key),
    approval_token: str | None = Header(default=None, alias="X-Approval-Token"),
):
    validate_approval_token(approval_token)
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        logger.error("AI service is not initialized")
        raise HTTPException(status_code=503, detail="AI service not available")

    payload = request.model_dump()
    messages = payload.get("messages", [])

    if ai_service.should_truncate_context(messages):
        messages = ai_service.truncate_context(messages)

    try:
        result = ai_service.agent_chat(
            messages=messages,
            task_id=payload.get("task_id"),
            max_tool_rounds=payload.get("max_tool_rounds"),
        )
        return ChatResponseSchema(**result)
    except Exception:
        logger.exception("Failed to process agent chat request")
        raise HTTPException(status_code=502, detail="AI agent request failed")


@app.post("/tasks/plan", response_model=TaskPlanResponseSchema)
async def plan_task(request: TaskPlanRequestSchema, auth: bool = Depends(validate_api_key)):
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    return TaskPlanResponseSchema(**ai_service.plan_task(goal=request.goal, context=request.context))


@app.post("/tasks/execute", response_model=TaskExecuteResponseSchema)
async def execute_task(request: TaskExecuteRequestSchema, auth: bool = Depends(validate_api_key)):
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    return TaskExecuteResponseSchema(
        **ai_service.execute_task(task_id=request.task_id, goal=request.goal, context=request.context)
    )


@app.get("/tasks/{task_id}", response_model=TaskStatusResponseSchema)
async def task_status(task_id: str, auth: bool = Depends(validate_api_key)):
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    return TaskStatusResponseSchema(**ai_service.get_task_status(task_id))


@app.post("/tools/execute", response_model=ToolExecutionResponseSchema)
async def execute_tool(
    request: ToolExecutionRequestSchema,
    auth: bool = Depends(validate_api_key),
    approval_token: str | None = Header(default=None, alias="X-Approval-Token"),
):
    validate_approval_token(approval_token)
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    try:
        result = ai_service.execute_tool_action(
            task_id=request.task_id,
            tool=request.tool,
            action=request.action,
            payload=request.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return ToolExecutionResponseSchema(**result)


@app.post("/trading/daily-analysis", response_model=TradingDailyAnalysisResponseSchema)
async def trading_daily_analysis(
    payload: dict,
    auth: bool = Depends(validate_api_key),
):
    """Synthesize preflight + metrics into daily GO/NO-GO (never places orders)."""
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    try:
        result = synthesize_daily_analysis(ai_service, payload)
        return TradingDailyAnalysisResponseSchema(**result)
    except Exception:
        logger.exception("Daily trading analysis failed")
        raise HTTPException(status_code=502, detail="Daily analysis failed")


@app.get("/traces/{trace_id}", response_class=JSONResponse)
async def fetch_trace(trace_id: str, auth: bool = Depends(validate_api_key)):
    ai_service: AIService = getattr(app.state, "ai_service", None)
    if ai_service is None:
        raise HTTPException(status_code=503, detail="AI service not available")
    trace = ai_service.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"data": trace}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
