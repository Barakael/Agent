import logging
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
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
            # Use provided values or defaults from settings
            temp = temperature if temperature is not None else self.temperature
            max_tok = max_tokens if max_tokens is not None else self.max_tokens

            # Ensure messages are in correct format
            formatted_messages = [
                {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                for msg in messages
            ]

            logger.info(f"Sending {len(formatted_messages)} messages to OpenAI model: {self.model}")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=formatted_messages,
                temperature=temp,
                max_tokens=max_tok,
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
