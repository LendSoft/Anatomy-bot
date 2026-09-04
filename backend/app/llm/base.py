"""Общий интерфейс языковых моделей.

Позволяет держать локальный vLLM основным провайдером и переключаться на
облачный, не трогая код RAG-пайплайна.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class GenerationParams:
    temperature: float = 0.2
    top_p: float = 0.9
    max_tokens: int = 1024
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    stop: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
            "stop": self.stop or None,
        }


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


class LLMError(RuntimeError):
    """Провайдер недоступен или вернул ошибку."""


class BaseLLM(ABC):
    provider_name: str

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    async def chat(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> LLMResponse: ...

    @abstractmethod
    async def stream_chat(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    async def health(self) -> bool: ...

    async def close(self) -> None:
        return None
