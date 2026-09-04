"""Клиент локальной модели: vLLM и Ollama.

Оба сервера отдают OpenAI-совместимый API (`/v1/chat/completions`) — это
просто формат протокола, а не обращение к OpenAI. Все запросы идут внутрь
compose, наружу ничего не уходит.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import get_logger
from app.llm.base import BaseLLM, ChatMessage, GenerationParams, LLMError, LLMResponse

log = get_logger(__name__)


class OpenAICompatibleLLM(BaseLLM):
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: int = 180,
        provider_name: str = "vllm",
    ) -> None:
        super().__init__(model)
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    def _payload(
        self, messages: list[ChatMessage], params: GenerationParams, stream: bool
    ) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            **params.as_dict(),
        }
        # vLLM ругается на stop=null, проще убрать пустые значения
        return {k: v for k, v in payload.items() if v is not None}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
        reraise=True,
    )
    async def chat(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> LLMResponse:
        try:
            resp = await self._client.post(
                "/chat/completions", json=self._payload(messages, params, stream=False)
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            log.error("llm_http_error", status=exc.response.status_code, body=body)
            raise LLMError(f"LLM вернула {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:
            log.error("llm_transport_error", error=str(exc))
            raise LLMError(f"Не удалось обратиться к LLM: {exc}") from exc

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}

        return LLMResponse(
            content=choice["message"]["content"] or "",
            model=data.get("model", self.model),
            provider=self.provider_name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )

    async def stream_chat(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, params, stream=True)
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if content := delta.get("content"):
                        yield content
        except httpx.HTTPError as exc:
            raise LLMError(f"Ошибка потоковой генерации: {exc}") from exc

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/models", timeout=10.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
