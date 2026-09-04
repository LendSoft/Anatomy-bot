"""Тесты клиента GigaChat.

Сеть не трогаем — подменяем httpx транспортом-заглушкой. Проверяем то, что
легко сломать при правках: обмен ключа на токен, повторное использование
живого токена, обновление протухшего и обработку отказов.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from app.llm.base import ChatMessage, GenerationParams, LLMError
from app.llm.gigachat_client import MIN_TEMPERATURE, GigaChatLLM

AUTH_KEY = base64.b64encode(b"client-id:client-secret").decode()


def make_client(handler, **kwargs) -> GigaChatLLM:
    """Клиент с подменённым транспортом."""
    llm = GigaChatLLM(auth_key=AUTH_KEY, **kwargs)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return llm


def token_response(ttl_seconds: int = 1800) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "test-token",
            "expires_at": int((time.time() + ttl_seconds) * 1000),
        },
    )


def chat_response(text: str = "Ответ по учебнику [1].") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "model": "GigaChat-2",
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        },
    )


@pytest.mark.asyncio
async def test_auth_then_chat():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "oauth" in str(request.url):
            assert request.headers["Authorization"] == f"Basic {AUTH_KEY}"
            # RqUID обязателен, без него сервер отвечает ошибкой
            assert request.headers["RqUID"]
            return token_response()

        assert request.headers["Authorization"] == "Bearer test-token"
        return chat_response()

    llm = make_client(handler)
    result = await llm.chat(
        [ChatMessage(role="user", content="Ветви наружной сонной артерии?")],
        GenerationParams(max_tokens=512),
    )

    assert result.content == "Ответ по учебнику [1]."
    assert result.provider == "gigachat"
    assert result.prompt_tokens == 120
    assert len(calls) == 2  # токен + запрос
    await llm.close()


@pytest.mark.asyncio
async def test_token_is_reused():
    """Живой токен не должен запрашиваться повторно на каждый вопрос."""
    oauth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal oauth_calls
        if "oauth" in str(request.url):
            oauth_calls += 1
            return token_response()
        return chat_response()

    llm = make_client(handler)
    params = GenerationParams()
    for _ in range(3):
        await llm.chat([ChatMessage(role="user", content="Вопрос")], params)

    assert oauth_calls == 1
    await llm.close()


@pytest.mark.asyncio
async def test_expired_token_is_refreshed():
    oauth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal oauth_calls
        if "oauth" in str(request.url):
            oauth_calls += 1
            # Токен уже на грани истечения — с учётом запаса считается протухшим
            return token_response(ttl_seconds=30)
        return chat_response()

    llm = make_client(handler)
    params = GenerationParams()
    await llm.chat([ChatMessage(role="user", content="Раз")], params)
    await llm.chat([ChatMessage(role="user", content="Два")], params)

    assert oauth_calls == 2
    await llm.close()


@pytest.mark.asyncio
async def test_retries_once_on_401():
    """Отозванный раньше срока токен обновляется, запрос повторяется."""
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if "oauth" in str(request.url):
            return token_response()

        chat_calls += 1
        if chat_calls == 1:
            return httpx.Response(401, json={"message": "Unauthorized"})
        return chat_response()

    llm = make_client(handler)
    result = await llm.chat(
        [ChatMessage(role="user", content="Вопрос")], GenerationParams()
    )

    assert chat_calls == 2
    assert result.content
    await llm.close()


@pytest.mark.asyncio
async def test_zero_temperature_is_lifted():
    """Судья задаёт нулевую температуру, а GigaChat её не принимает."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth" in str(request.url):
            return token_response()
        captured.update(json.loads(request.content))
        return chat_response()

    llm = make_client(handler)
    await llm.chat(
        [ChatMessage(role="user", content="Вопрос")],
        GenerationParams(temperature=0.0),
    )

    assert captured["temperature"] == MIN_TEMPERATURE
    await llm.close()


@pytest.mark.asyncio
async def test_blacklist_finish_reason_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth" in str(request.url):
            return token_response()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": ""},
                     "finish_reason": "blacklist"}
                ],
                "model": "GigaChat-2",
            },
        )

    llm = make_client(handler)
    with pytest.raises(LLMError, match="ограничения"):
        await llm.chat([ChatMessage(role="user", content="Вопрос")], GenerationParams())
    await llm.close()


@pytest.mark.asyncio
async def test_missing_key_gives_clear_error():
    llm = GigaChatLLM(auth_key=None)
    with pytest.raises(LLMError, match="GIGACHAT_AUTH_KEY"):
        await llm.chat([ChatMessage(role="user", content="Вопрос")], GenerationParams())
    await llm.close()


@pytest.mark.asyncio
async def test_auth_key_built_from_id_and_secret():
    llm = GigaChatLLM(client_id="client-id", client_secret="client-secret")
    assert llm.auth_key == AUTH_KEY
    await llm.close()


@pytest.mark.asyncio
async def test_system_message_passed_through():
    """У GigaChat системный промпт — обычное сообщение, не отдельное поле."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth" in str(request.url):
            return token_response()
        captured.update(json.loads(request.content))
        return chat_response()

    llm = make_client(handler)
    await llm.chat(
        [
            ChatMessage(role="system", content="Отвечай только по учебнику"),
            ChatMessage(role="user", content="Вопрос"),
        ],
        GenerationParams(),
    )

    assert captured["messages"][0] == {
        "role": "system",
        "content": "Отвечай только по учебнику",
    }
    await llm.close()
