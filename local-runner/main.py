"""Local runner daemon — executes desktop tools on the user's Mac."""

from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import Any, Dict, Optional

# Prevent re-delegation: runner executes tools locally on this machine.
os.environ.setdefault("RUNNER_ENABLED", "false")

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# Add ai-agent to path so we can reuse ToolExecutor
AGENT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai-agent"))
if AGENT_ROOT not in sys.path:
    sys.path.insert(0, AGENT_ROOT)

from services.tool_executor import ToolExecutor  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local-runner")

RUNNER_API_KEY = os.getenv("RUNNER_API_KEY", "local-runner-dev-key")
executor = ToolExecutor()
jobs: Dict[str, Dict[str, Any]] = {}

app = FastAPI(title="Wayda Local Runner", version="1.0.0")
security = HTTPBearer()


class RunToolRequest(BaseModel):
    tool: str
    action: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None


def validate_runner_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> bool:
    if credentials.credentials != RUNNER_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def _run_job(job_id: str, body: RunToolRequest) -> None:
    try:
        result = executor.execute(body.tool, body.action, body.payload)
        jobs[job_id] = {"status": "completed", "result": result, "error": None}
    except Exception as exc:
        logger.exception("Tool execution failed")
        jobs[job_id] = {"status": "failed", "result": None, "error": str(exc)}


@app.get("/health")
async def health():
    return {"status": "ok", "platform": sys.platform}


@app.post("/runner/v1/jobs")
async def create_job(
    body: RunToolRequest,
    background_tasks: BackgroundTasks,
    auth: bool = Depends(validate_runner_key),
):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "result": None, "error": None}
    background_tasks.add_task(_run_job, job_id, body)
    return {"job_id": job_id, "status": "running"}


@app.get("/runner/v1/jobs/{job_id}")
async def get_job(job_id: str, auth: bool = Depends(validate_runner_key)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("RUNNER_HOST", "127.0.0.1"),
        port=int(os.getenv("RUNNER_PORT", "8010")),
        reload=False,
    )
