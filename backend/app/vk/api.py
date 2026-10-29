"""Тонкий клиент VK API.

Своя обёртка вместо библиотеки: нужны ровно четыре метода, а зависимость
пришлось бы тащить и обновлять вслед за версией API.
"""

from __future__ import annotations

import contextlib
import random
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

API_URL = "https://api.vk.com/method"


class VkError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"VK API error {code}: {message}")
        self.code = code


class VkApi:
    def __init__(
        self,
        token: str,
        api_version: str | None = None,
        group_id: str | None = None,
    ) -> None:
        self.token = token
        self.version = api_version or settings.vk_api_version
        self.group_id = group_id
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))

    async def call(self, method: str, **params: Any) -> Any:
        payload = {
            **{k: v for k, v in params.items() if v is not None},
            "access_token": self.token,
            "v": self.version,
        }
        response = await self._client.post(f"{API_URL}/{method}", data=payload)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error = data["error"]
            raise VkError(error.get("error_code", 0), error.get("error_msg", "unknown"))

        return data.get("response")

    async def get_long_poll_server(self, group_id: str) -> dict:
        return await self.call("groups.getLongPollServer", group_id=group_id)

    async def send_message(
        self,
        peer_id: int,
        text: str,
        attachment: str | None = None,
        keyboard: str | None = None,
    ) -> None:
        # random_id обязателен: без него VK может задублировать сообщение
        await self.call(
            "messages.send",
            peer_id=peer_id,
            message=text,
            attachment=attachment,
            keyboard=keyboard,
            random_id=random.getrandbits(31),
        )

    async def set_typing(self, peer_id: int) -> None:
        """Показывает «печатает» — ответ занимает секунды, без индикатора
        студент решит, что бот завис."""
        # Индикатор необязателен: если не отправился, ответ всё равно придёт
        with contextlib.suppress(VkError, httpx.HTTPError):
            await self.call("messages.setActivity", peer_id=peer_id, type="typing")

    async def upload_photo(self, peer_id: int, image_path: Path) -> str | None:
        """Загружает картинку в диалог и возвращает идентификатор вложения."""
        try:
            server = await self.call("photos.getMessagesUploadServer", peer_id=peer_id)

            with image_path.open("rb") as file:
                upload = await self._client.post(
                    server["upload_url"], files={"photo": (image_path.name, file)}
                )
            upload.raise_for_status()
            uploaded = upload.json()

            saved = await self.call(
                "photos.saveMessagesPhoto",
                photo=uploaded["photo"],
                server=uploaded["server"],
                hash=uploaded["hash"],
            )
            photo = saved[0]
            return f"photo{photo['owner_id']}_{photo['id']}"

        except (VkError, httpx.HTTPError, KeyError, IndexError) as exc:
            log.warning("vk_photo_upload_failed", error=str(exc))
            return None

    async def upload_document(self, peer_id: int, document_path: Path) -> str | None:
        """Загружает документ в диалог и возвращает идентификатор вложения."""
        try:
            server = await self.call(
                "docs.getMessagesUploadServer",
                peer_id=peer_id,
                type="doc",
                group_id=self.group_id,
            )

            with document_path.open("rb") as file:
                upload = await self._client.post(
                    server["upload_url"],
                    files={"file": (document_path.name, file)},
                )
            upload.raise_for_status()
            uploaded = upload.json()

            saved = await self.call(
                "docs.save", file=uploaded["file"], title=document_path.name
            )
            document = saved.get("doc")
            if not document:
                raise KeyError("doc")
            return f"doc{document['owner_id']}_{document['id']}"

        except (VkError, httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            log.warning("vk_document_upload_failed", error=str(exc))
            return None

    async def get_users(self, user_ids: list[int]) -> list[dict]:
        if not user_ids:
            return []
        try:
            return await self.call(
                "users.get", user_ids=",".join(map(str, user_ids))
            ) or []
        except VkError:
            return []

    async def close(self) -> None:
        await self._client.aclose()
