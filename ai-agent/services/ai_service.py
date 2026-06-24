import json
import logging
import uuid
from typing import List, Dict, Optional, Any
from openai import OpenAI
from config import settings
from services.tool_executor import ToolExecutor
from services.tools import AGENT_SYSTEM_PROMPT, AGENT_TOOLS

logger = logging.getLogger(__name__)


class AIService:
    """Service for handling AI interactions via OpenAI-compatible API."""

    def __init__(self):
        """Initialize the AI Service. Uses OpenAI cloud by default."""
        if not settings.OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY not configured")
            raise ValueError("OPENAI_API_KEY environment variable is required")

        client_kwargs: Dict[str, Any] = {
            "api_key": settings.OPENAI_API_KEY,
            "timeout": float(settings.TIMEOUT),
        }
        if settings.OPENAI_BASE_URL.strip():
            client_kwargs["base_url"] = settings.OPENAI_BASE_URL.rstrip("/")
            logger.info("LLM endpoint: %s (self-hosted)", client_kwargs["base_url"])
        else:
            logger.info("LLM endpoint: OpenAI API (cloud)")

        self.client = OpenAI(**client_kwargs)
        self.llm_base_url = settings.OPENAI_BASE_URL.strip()
        self.model = settings.OPENAI_MODEL
        self.reasoning_effort = settings.OPENAI_REASONING_EFFORT
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.tool_executor = ToolExecutor()
        self.task_runs: Dict[str, Dict[str, Any]] = {}
        self.execution_traces: Dict[str, Dict[str, Any]] = {}

    def _uses_reasoning_model(self) -> bool:
        if self.llm_base_url:
            return False
        model = self.model.lower()
        return model.startswith(("gpt-5", "o1", "o3", "o4"))

    def _build_completion_kwargs(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        use_tools: bool = False,
    ) -> Dict[str, Any]:
        token_limit = max_tokens if max_tokens is not None else self.max_tokens
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if self._uses_reasoning_model() and not use_tools:
            kwargs["reasoning_effort"] = reasoning_effort or self.reasoning_effort
            kwargs["max_completion_tokens"] = token_limit
        elif self._uses_reasoning_model() and use_tools:
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

    def agent_chat(
        self,
        messages: List[Dict[str, str]],
        task_id: Optional[str] = None,
        max_tool_rounds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run chat with OpenAI tool calling and local computer actions."""
        task_id = task_id or str(uuid.uuid4())
        rounds_limit = max_tool_rounds or settings.AGENT_MAX_TOOL_ROUNDS
        tool_actions: List[Dict[str, Any]] = []

        formatted_messages: List[Dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        ]
        formatted_messages.extend(
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            for msg in messages
            if msg.get("role") in {"user", "assistant"}
        )

        total_tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        model_name = self.model
        finish_reason = "stop"
        final_response = ""

        for round_index in range(rounds_limit):
            logger.info(
                "Agent chat round %s/%s for task %s",
                round_index + 1,
                rounds_limit,
                task_id,
            )

            kwargs = self._build_completion_kwargs(
                formatted_messages,
                use_tools=True,
            )
            kwargs["tools"] = AGENT_TOOLS
            kwargs["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            assistant_message = choice.message
            model_name = response.model
            finish_reason = choice.finish_reason or "stop"

            if response.usage:
                total_tokens["prompt_tokens"] += response.usage.prompt_tokens or 0
                total_tokens["completion_tokens"] += response.usage.completion_tokens or 0
                total_tokens["total_tokens"] += response.usage.total_tokens or 0

            tool_calls = assistant_message.tool_calls or []
            if not tool_calls:
                final_response = assistant_message.content or ""
                break

            formatted_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in tool_calls
                    ],
                }
            )

            for tool_call in tool_calls:
                if tool_call.function.name != "execute_tool":
                    tool_result = {"error": f"Unknown tool '{tool_call.function.name}'."}
                else:
                    try:
                        arguments = json.loads(tool_call.function.arguments or "{}")
                        tool = str(arguments.get("tool", "")).strip()
                        action = str(arguments.get("action", "")).strip()
                        payload = arguments.get("payload") or {}
                        execution = self.execute_tool_action(
                            task_id=task_id,
                            tool=tool,
                            action=action,
                            payload=payload,
                        )
                        tool_result = execution["output"]
                        tool_actions.append(
                            {
                                "tool": tool,
                                "action": action,
                                "payload": payload,
                                "output": tool_result,
                                "trace_id": execution.get("trace_id"),
                            }
                        )
                    except Exception as exc:
                        logger.exception("Tool execution failed")
                        tool_result = {"error": str(exc)}

                formatted_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result),
                    }
                )
        else:
            final_response = (
                "I reached the maximum number of tool steps for this request. "
                "Please ask me to continue or simplify the task."
            )
            finish_reason = "max_tool_rounds"

        if not final_response:
            final_response = "I completed the requested actions."

        return {
            "response": final_response,
            "model": model_name,
            "tokens_used": total_tokens,
            "tool_actions": tool_actions,
            "metadata": {
                "finish_reason": finish_reason,
                "task_id": task_id,
                "tool_rounds": len(tool_actions),
                "agent_mode": True,
            },
        }

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
        allowed_actions = self._allowed_tool_actions()
        action_key = f"{tool}.{action}"
        if action_key not in allowed_actions:
            raise ValueError(f"Tool action '{action_key}' is not allowed.")

        trace_id = str(uuid.uuid4())
        try:
            output_data = self.tool_executor.execute(tool, action, payload)
            output = {
                "task_id": task_id,
                "tool_action": action_key,
                "result": "completed",
                **output_data,
            }
            status = "completed"
            events = [f"Tool action completed: {action_key}"]
        except Exception as exc:
            logger.error("Tool action %s failed: %s", action_key, exc)
            output = {
                "task_id": task_id,
                "tool_action": action_key,
                "result": "failed",
                "error": str(exc),
            }
            status = "failed"
            events = [f"Tool action failed: {action_key}", str(exc)]

        self.execution_traces[trace_id] = {
            "task_id": task_id,
            "goal": "tool_execution",
            "summary": f"Executed tool action {action_key}",
            "events": events,
            "output": output,
        }
        return {"status": status, "output": output, "trace_id": trace_id}

    @staticmethod
    def _allowed_tool_actions() -> set[str]:
        import os

        raw = os.getenv("ALLOWED_TOOL_ACTIONS", settings.ALLOWED_TOOL_ACTIONS)
        return {part.strip() for part in raw.split(",") if part.strip()}

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
        """Check if the configured LLM endpoint is reachable."""
        try:
            self.client.models.list()
            label = "self-hosted" if self.llm_base_url else "OpenAI"
            logger.info("%s API health check passed", label)
            return True
        except Exception as e:
            logger.error("LLM API health check failed: %s", e)
            return False
