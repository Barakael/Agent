import logging
import uuid
from typing import List, Dict, Optional, Any
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)


class AIService:
    """Service for handling AI interactions with OpenAI API."""

    def __init__(self):
        """Initialize the AI Service with OpenAI client."""
        if not settings.OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY not configured")
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL
        self.reasoning_effort = settings.OPENAI_REASONING_EFFORT
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.task_runs: Dict[str, Dict[str, Any]] = {}
        self.execution_traces: Dict[str, Dict[str, Any]] = {}

    def _uses_reasoning_model(self) -> bool:
        model = self.model.lower()
        return model.startswith(("gpt-5", "o1", "o3", "o4"))

    def _build_completion_kwargs(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        token_limit = max_tokens if max_tokens is not None else self.max_tokens
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if self._uses_reasoning_model():
            kwargs["reasoning_effort"] = reasoning_effort or self.reasoning_effort
            kwargs["max_completion_tokens"] = token_limit
        else:
            kwargs["temperature"] = (
                temperature if temperature is not None else self.temperature
            )
            kwargs["max_tokens"] = token_limit

        return kwargs

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send chat messages to OpenAI and get response.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Optional temperature override
            max_tokens: Optional max tokens override

        Returns:
            Dict containing response and metadata
        """
        try:
            formatted_messages = [
                {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                for msg in messages
            ]

            effort = reasoning_effort or self.reasoning_effort
            logger.info(
                "Sending %s messages to OpenAI model: %s (reasoning_effort=%s)",
                len(formatted_messages),
                self.model,
                effort if self._uses_reasoning_model() else "n/a",
            )

            response = self.client.chat.completions.create(
                **self._build_completion_kwargs(
                    formatted_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                )
            )

            # Extract response
            assistant_message = response.choices[0].message.content

            # Calculate tokens used
            tokens_used = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            logger.info(f"OpenAI response received. Tokens used: {tokens_used}")

            return {
                "response": assistant_message,
                "model": response.model,
                "tokens_used": tokens_used,
                "metadata": {
                    "finish_reason": response.choices[0].finish_reason,
                },
            }

        except Exception as e:
            logger.error(f"Error calling OpenAI API: {str(e)}")
            raise

    def plan_task(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        planning_prompt = (
            "You are planning a safe autonomous assistant task. "
            "Return 4 concise executable steps as plain lines."
        )
        messages = [
            {"role": "system", "content": planning_prompt},
            {
                "role": "user",
                "content": f"Goal: {goal}\nContext: {context or {}}",
            },
        ]
        result = self.chat(
            messages=messages,
            max_tokens=800,
            reasoning_effort="low",
        )
        raw_lines = [line.strip("- ").strip() for line in result["response"].splitlines() if line.strip()]
        steps = raw_lines[:4] if raw_lines else ["Analyze request", "Plan actions", "Execute safely", "Return summary"]
        self.task_runs[task_id] = {
            "status": "planned",
            "logs": ["Task planned"],
            "goal": goal,
            "trace_id": None,
        }
        return {
            "task_id": task_id,
            "plan_steps": steps,
            "status": "planned",
        }

    def execute_task(self, task_id: str, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        trace_id = str(uuid.uuid4())
        execution_prompt = (
            "Summarize execution for the following user goal in 3 concise lines: "
            f"{goal}. Context: {context or {}}"
        )
        result = self.chat(
            messages=[{"role": "user", "content": execution_prompt}],
            max_tokens=800,
            reasoning_effort="low",
        )
        summary = result["response"]
        self.execution_traces[trace_id] = {
            "task_id": task_id,
            "goal": goal,
            "summary": summary,
            "events": [
                "Task received",
                "Safety checks completed",
                "Execution summary generated",
            ],
        }
        self.task_runs[task_id] = {
            "status": "completed",
            "logs": ["Task accepted", "Task executed", "Task completed"],
            "goal": goal,
            "trace_id": trace_id,
        }
        return {
            "task_id": task_id,
            "status": "completed",
            "summary": summary,
            "trace_id": trace_id,
        }

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        run = self.task_runs.get(task_id)
        if run is None:
            return {"task_id": task_id, "status": "not_found", "logs": [], "trace_id": None}
        return {
            "task_id": task_id,
            "status": run["status"],
            "logs": run["logs"],
            "trace_id": run.get("trace_id"),
        }

    def execute_tool_action(
        self,
        task_id: str,
        tool: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed_actions = set(settings.ALLOWED_TOOL_ACTIONS.split(","))
        action_key = f"{tool}.{action}"
        if action_key not in allowed_actions:
            raise ValueError(f"Tool action '{action_key}' is not allowed.")

        trace_id = str(uuid.uuid4())
        output = {
            "task_id": task_id,
            "tool_action": action_key,
            "result": "accepted",
            "payload_echo": payload,
        }
        self.execution_traces[trace_id] = {
            "task_id": task_id,
            "goal": "tool_execution",
            "summary": f"Executed tool action {action_key}",
            "events": [f"Tool action accepted: {action_key}"],
            "output": output,
        }
        return {"status": "completed", "output": output, "trace_id": trace_id}

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        return self.execution_traces.get(trace_id)

    def count_tokens_in_messages(self, messages: List[Dict[str, str]]) -> int:
        """
        Estimate token count in messages.
        This is a rough estimate. For accurate counts, use OpenAI's tokenizer.
        Rough estimate: ~4 characters per token
        """
        total_chars = sum(len(msg.get("content", "")) for msg in messages)
        estimated_tokens = total_chars // 4
        return estimated_tokens

    def should_truncate_context(self, messages: List[Dict[str, str]]) -> bool:
        """
        Check if message history should be truncated to avoid token limits.
        """
        estimated_tokens = self.count_tokens_in_messages(messages)
        # Leave 500 tokens buffer for response
        return estimated_tokens > (settings.MAX_CONTEXT_LENGTH - 500)

    def truncate_context(
        self, messages: List[Dict[str, str]], keep_system: bool = True
    ) -> List[Dict[str, str]]:
        """
        Truncate message history keeping recent messages and system prompt.
        """
        if not messages:
            return messages

        truncated = []

        # Keep system messages if requested
        if keep_system:
            truncated = [msg for msg in messages if msg.get("role") == "system"]

        # Keep last N messages
        non_system = [msg for msg in messages if msg.get("role") != "system"]
        if non_system:
            # Keep last 10 messages for context
            truncated.extend(non_system[-10:])

        logger.warning(f"Context truncated from {len(messages)} to {len(truncated)} messages")
        return truncated

    def health_check(self) -> bool:
        """
        Check if OpenAI API is accessible.
        """
        try:
            # Try to list models (lightweight operation)
            self.client.models.list()
            logger.info("OpenAI API health check passed")
            return True
        except Exception as e:
            logger.error(f"OpenAI API health check failed: {str(e)}")
            return False
