"""LLM Provider abstraction and answer generation service supporting OpenAI and Mock providers."""

from abc import ABC, abstractmethod
import asyncio
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_llm_metrics

logger = get_logger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate_answer(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> Dict[str, Any]:
        """Generate a complete answer asynchronously."""
        pass

    @abstractmethod
    async def generate_answer_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> AsyncGenerator[str, None]:
        """Stream answer tokens asynchronously."""
        pass


class OpenAIProvider(BaseLLMProvider):
    """Production provider using the official OpenAI Async SDK."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("OpenAI API key must be provided.")
        self.api_key = api_key
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)

    async def generate_answer(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1500,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Call OpenAI chat completion API with timeout and rate-limit handling."""
        t0 = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=timeout,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }
            return {
                "content": content,
                "usage": usage,
                "model": self.model,
                "generation_time_ms": elapsed_ms,
            }
        except asyncio.TimeoutError:
            logger.error(f"OpenAI request timed out after {timeout} seconds.")
            raise RuntimeError(f"LLM provider request timed out after {timeout}s.")
        except openai.RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {e}")
            raise RuntimeError("LLM rate limit reached. Please retry in a moment.") from e
        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise RuntimeError(f"LLM provider error: {e}") from e

    async def generate_answer_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1500,
        timeout: float = 30.0,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from OpenAI chat completions."""
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                timeout=timeout,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except asyncio.TimeoutError:
            logger.error("OpenAI streaming request timed out.")
            raise RuntimeError("Streaming connection to LLM timed out.")
        except openai.RateLimitError as e:
            logger.error(f"OpenAI rate limit during stream: {e}")
            raise RuntimeError("LLM rate limit reached during streaming.") from e
        except openai.APIError as e:
            logger.error(f"OpenAI API streaming error: {e}")
            raise RuntimeError(f"LLM streaming provider error: {e}") from e


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock provider generating grounded answers with citations for testing."""

    def __init__(self, model_name: str = "mock-gpt-4o"):
        self.model_name = model_name
        self.custom_response: Optional[str] = None
        self.should_fail: bool = False
        self.failure_reason: str = "Mock simulated provider failure"

    def set_custom_response(self, text: Optional[str]) -> None:
        self.custom_response = text

    def set_failure(self, should_fail: bool, reason: str = "Mock simulated provider failure") -> None:
        self.should_fail = should_fail
        self.failure_reason = reason

    def _generate_mock_content(self, messages: List[Dict[str, str]]) -> str:
        if self.should_fail:
            raise RuntimeError(self.failure_reason)

        if self.custom_response is not None:
            return self.custom_response

        # Look at context in the last user message
        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break

        # Check for abstention condition
        if "No relevant document passages were retrieved" in last_user_msg or not last_user_msg.strip():
            return "The requested information could not be found in the uploaded enterprise documents."

        # Parse retrieved document sources from the context prompt to ground mock answers in real text
        import re
        source_pattern = re.compile(
            r"\[SOURCE:\s*(S\d+)\]\s*\nDocument:\s*([^\n]+)\s*\n(?:Page\s*([^\n]+))?\s*\nContent:\s*\n(.*?)(?=\n\[SOURCE:|\n\[/DOCUMENT CONTEXT\]|\Z)",
            re.DOTALL,
        )
        matches = source_pattern.findall(last_user_msg)
        if matches:
            paragraphs = []
            for tag, doc_name, page_str, content_text in matches[:3]:
                lines = [line.strip() for line in content_text.strip().split("\n") if line.strip()]
                clean_text = " ".join(lines)
                sentences = [s.strip() for s in clean_text.split(".") if len(s.strip()) > 20]
                if sentences:
                    excerpt = sentences[0]
                    paragraphs.append(f"{excerpt}. [{tag}]")
                elif clean_text:
                    paragraphs.append(f"{clean_text[:180]}... [{tag}]")

            if paragraphs:
                return (
                    "Based on the retrieved enterprise policy documentation:\n\n"
                    + "\n\n".join(f"• {p}" for p in paragraphs)
                )

        # Default fallback response citing [S1] and [S2] if present
        return (
            "Based on the provided enterprise documentation, the architecture implements multi-tenant "
            "isolation and secure document retrieval [S1]. The platform combines dense vector search with "
            "BM25 keyword retrieval and neural reranking [S2]."
        )

    async def generate_answer(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1500,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        await asyncio.sleep(0.02)  # simulate brief async invocation
        content = self._generate_mock_content(messages)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "content": content,
            "usage": {
                "prompt_tokens": len(str(messages)) // 4,
                "completion_tokens": len(content) // 4,
                "total_tokens": (len(str(messages)) + len(content)) // 4,
            },
            "model": self.model_name,
            "generation_time_ms": elapsed_ms,
        }

    async def generate_answer_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1500,
        timeout: float = 30.0,
    ) -> AsyncGenerator[str, None]:
        content = self._generate_mock_content(messages)
        words = content.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.005)


class LLMService:
    """Singleton service routing answer generation to the configured LLM provider."""

    _instance: Optional["LLMService"] = None

    def __init__(self):
        self._provider: Optional[BaseLLMProvider] = None
        self._init_provider()

    @classmethod
    def get_instance(cls) -> "LLMService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_provider_for_testing(self, provider: BaseLLMProvider) -> None:
        """Inject mock provider for automated unit testing."""
        self._provider = provider

    def _init_provider(self) -> None:
        provider_name = settings.LLM_PROVIDER.lower()
        api_key = settings.OPENAI_API_KEY

        if provider_name == "openai" and api_key and not api_key.startswith("your_"):
            logger.info(f"Initializing OpenAIProvider with model '{settings.LLM_MODEL}'")
            self._provider = OpenAIProvider(api_key=api_key, model=settings.LLM_MODEL)
        else:
            logger.info("No active OpenAI API key detected. Initializing MockLLMProvider for deterministic operation.")
            self._provider = MockLLMProvider(model_name=f"mock-{settings.LLM_MODEL}")

    @property
    def provider(self) -> BaseLLMProvider:
        if self._provider is None:
            self._init_provider()
        return self._provider

    async def generate_answer(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate answer via active provider."""
        temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
        max_tok = max_tokens if max_tokens is not None else settings.LLM_MAX_OUTPUT_TOKENS
        t0 = time.perf_counter()
        provider_name = settings.LLM_PROVIDER
        model_name = getattr(self.provider, "model", getattr(self.provider, "model_name", "unknown"))

        try:
            result = await self.provider.generate_answer(
                messages=messages,
                temperature=temp,
                max_tokens=max_tok,
                timeout=settings.LLM_REQUEST_TIMEOUT,
            )
            elapsed_s = time.perf_counter() - t0
            usage = result.get("usage", {})
            record_llm_metrics(
                provider=provider_name,
                model=model_name,
                duration_s=elapsed_s,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
            return result
        except Exception as exc:
            elapsed_s = time.perf_counter() - t0
            record_llm_metrics(
                provider=provider_name,
                model=model_name,
                duration_s=elapsed_s,
                error_type=exc.__class__.__name__,
            )
            raise exc

    async def generate_answer_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream answer tokens via active provider."""
        temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
        max_tok = max_tokens if max_tokens is not None else settings.LLM_MAX_OUTPUT_TOKENS
        async for chunk in self.provider.generate_answer_stream(
            messages=messages,
            temperature=temp,
            max_tokens=max_tok,
            timeout=settings.LLM_REQUEST_TIMEOUT,
        ):
            yield chunk
