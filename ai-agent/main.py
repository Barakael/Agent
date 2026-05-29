import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings
from models.schemas import ChatRequestSchema, ChatResponseSchema, HealthCheckSchema
from services.ai_service import AIService

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

@app.on_event("startup")
async def startup_event():
    if not settings.AI_SERVICE_API_KEY:
        logger.error("AI_SERVICE_API_KEY not configured")
        raise ValueError("AI_SERVICE_API_KEY environment variable is required")

    try:
        app.state.ai_service = AIService()
        app.state.ai_service_ready = app.state.ai_service.health_check()
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

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
